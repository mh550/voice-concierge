"""The extractor (spec §4.4; plan C4 "The extractor"): an isolated LLM call that reports memory changes through the
emit_ops tool, read from LLMStream.collect()."""

import json

import pytest
from livekit.agents import APIStatusError, llm

from concierge.claude_llm import ClaudeLLM
from concierge.config import build_llm
from concierge.extractor import (
    EMIT_OPS,
    EXTRACTOR_SYSTEM,
    WINDOW_MAX_TURNS,
    build_extractor_ctx,
    extract,
    extraction_window,
    ops_from,
)
from concierge.knowledge import load_pack
from concierge.models import Fact, SlotName
from concierge.ops import AddOp, OpArg
from concierge.prompt import MEMORY_HEADER, STATIC_INSTRUCTIONS
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.turns import Turn


def _fact(id: int, slot: SlotName, value: str) -> Fact:
    return Fact(
        id=id, thread_id="t", slot=slot, value=value, confidence=1.0, source="user_said", channel="voice",
        turn_id=f"turn-{id}", created_at=1, valid_from=1,
    )


def _user(n: int, text: str = "hello") -> Turn:
    return Turn(turn_id=f"item_u{n}", role="user", text=text, channel="voice")


def _agent(n: int, text: str = "hi there") -> Turn:
    return Turn(turn_id=f"item_a{n}", role="agent", text=text, channel="voice")


def _op(**fields: object) -> dict[str, object]:
    # The strict schema sends every field; the ones an op doesn't use are null.
    base: dict[str, object] = dict.fromkeys(("slot", "value", "fact_id", "confidence", "turn_id", "reason"))
    return base | fields


def _emit(ops: list[dict[str, object]], prompt_tokens: int = 0) -> FakeResponse:
    return FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": ops}), prompt_tokens=prompt_tokens)


def _ctx_text(ctx: llm.ChatContext) -> str:
    return "\n".join(m.text_content or "" for m in ctx.messages())


def _data(ctx: llm.ChatContext) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The facts and turns JSON in the extractor's user message."""
    body = ctx.messages()[-1].text_content or ""
    facts_part, turns_part = body.split("\n\nTurns since", 1)
    facts = json.loads(facts_part.split("\n", 1)[1])
    turns = json.loads(turns_part.split("\n", 1)[1])
    return facts, turns


TWO_ADDS = [
    _op(op="ADD", slot="name", value="Ada", turn_id="item_u1", confidence=0.9),
    _op(op="ADD", slot="company", value="Initech", turn_id="item_u1"),
]


async def test_two_add_ops_yield_two_ops() -> None:
    fake = FakeLLM([_emit(TWO_ADDS)])
    result = await extract(fake, [_user(1, "I'm Ada from Initech")], [])
    assert len(result.ops) == 2
    assert all(isinstance(op, AddOp) for op in result.ops)
    assert [op.value for op in result.ops] == ["Ada", "Initech"]
    assert result.tool_called is True
    assert result.dropped == []


async def test_plain_text_reply_is_zero_ops_and_no_error() -> None:
    fake = FakeLLM(["Nothing changed about the visitor."])
    result = await extract(fake, [_user(1)], [])
    assert result.ops == []
    assert result.tool_called is False


async def test_another_tool_name_is_zero_ops() -> None:
    fake = FakeLLM([FakeResponse(tool_call=FakeToolCall(name="remember", arguments={"fact": "x"}))])
    result = await extract(fake, [_user(1)], [])
    assert result.ops == [] and result.tool_called is False


async def test_malformed_ops_are_dropped_and_reported() -> None:
    fake = FakeLLM([_emit([TWO_ADDS[0], _op(op="ADD", slot="name")])])  # the second has no value or turn_id
    result = await extract(fake, [_user(1)], [])
    assert len(result.ops) == 1
    assert [d.index for d in result.dropped] == [1]


def test_extractor_ctx_is_isolated_from_the_session_prompt() -> None:
    ctx = build_extractor_ctx([_agent(0), _user(1)], [_fact(3, "name", "Ada")])
    text = _ctx_text(ctx)
    assert STATIC_INSTRUCTIONS not in text
    assert STATIC_INSTRUCTIONS[:80] not in text
    assert MEMORY_HEADER not in text
    pack_lines = [line for line in load_pack().splitlines() if len(line) > 40]
    assert pack_lines
    assert not any(line in text for line in pack_lines)
    assert [m.role for m in ctx.messages()] == ["system", "user"]
    assert not any(item.type != "message" for item in ctx.items)


def test_extractor_ctx_ends_on_a_user_message() -> None:
    ctx = build_extractor_ctx([_user(1), _agent(1)], [])
    assert ctx.items[-1].type == "message"
    assert ctx.messages()[-1].role == "user"


def test_current_facts_are_listed_with_ids() -> None:
    facts, _ = _data(build_extractor_ctx([_user(1)], [_fact(12, "company", "Initech"), _fact(14, "interests", "Rust")]))
    assert facts == [
        {"fact_id": 12, "slot": "company", "value": "Initech", "channel": "voice"},
        {"fact_id": 14, "slot": "interests", "value": "Rust", "channel": "voice"},
    ]


def test_turns_are_quoted_as_data_with_speaker_and_channel() -> None:
    low = Turn(turn_id="item_u2", role="user", text="I'm at Initeck", channel="text", confidence=0.4)
    _, turns = _data(build_extractor_ctx([_agent(1, "Did I get that right, Ada?"), _user(1, "Yes"), low], []))
    assert turns == [
        {"turn_id": "item_a1", "speaker": "agent", "text": "Did I get that right, Ada?"},
        {"turn_id": "item_u1", "speaker": "visitor", "channel": "voice", "text": "Yes"},
        {"turn_id": "item_u2", "speaker": "visitor", "channel": "text", "text": "I'm at Initeck", "confidence": 0.4},
    ]


def test_window_includes_the_agent_turn_before_the_first_new_user_turn() -> None:
    history = [_user(1), _agent(1, "Did I get that right, Ada?"), _user(2, "Yes"), _agent(2)]
    window = extraction_window(history, first_new=2)
    assert [t.turn_id for t in window] == ["item_a1", "item_u2", "item_a2"]
    # The turn before isn't an agent turn: the window starts at the first new turn.
    assert [t.turn_id for t in extraction_window(history, first_new=1)] == ["item_a1", "item_u2", "item_a2"]
    assert [t.turn_id for t in extraction_window([_user(1), _user(2)], first_new=1)] == ["item_u2"]
    assert [t.turn_id for t in extraction_window(history, first_new=0)] == [t.turn_id for t in history]
    assert extraction_window(history, first_new=4) == []


def test_window_keeps_the_newest_24_turns() -> None:
    assert WINDOW_MAX_TURNS == 24
    history = [_user(n) for n in range(30)]
    window = extraction_window(history, first_new=0)
    assert [t.turn_id for t in window] == [f"item_u{n}" for n in range(6, 30)]
    _, turns = _data(build_extractor_ctx(history, []))
    assert [t["turn_id"] for t in turns] == [f"item_u{n}" for n in range(6, 30)]


OP_ARG_DESCRIPTION = "One change to the visitor's memory. Fields the op doesn't use are null."


def test_emit_ops_strict_schema_lists_every_field() -> None:
    assert OpArg.__doc__ == OP_ARG_DESCRIPTION  # the model reads it as the item's description
    (schema,) = llm.ToolContext([EMIT_OPS]).parse_function_tools("anthropic", strict=True)
    assert schema["name"] == "emit_ops"
    assert schema["strict"] is True
    assert "exactly once" in schema["description"]
    assert schema["input_schema"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["ops"],
        "properties": {"ops": {"type": "array", "items": {"$ref": "#/$defs/OpArg"}}},
        "$defs": {
            "OpArg": {
                "description": OP_ARG_DESCRIPTION,
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "slot", "value", "fact_id", "confidence", "turn_id", "reason"],
                "properties": {
                    "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE"]},
                    "slot": {
                        "type": ["string", "null"],
                        "enum": ["name", "role", "company", "follow_up_wanted", "interests", "asked_about", None],
                    },
                    "value": {"type": ["string", "null"]},
                    "fact_id": {"type": ["integer", "null"]},
                    "confidence": {"type": ["number", "null"]},
                    "turn_id": {"type": ["string", "null"]},
                    "reason": {
                        "type": ["string", "null"],
                        "enum": ["no_longer_true", "asked_to_forget", "corrected", None],
                    },
                },
            }
        },
    }


def test_extractor_llm_keeps_the_strict_tool_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")  # never leaves the process: nothing is sent
    monkeypatch.delenv("CONCIERGE_LLM_PROVIDER", raising=False)
    built = build_llm("extractor")
    assert isinstance(built, ClaudeLLM)
    assert built._opts.strict_tool_schema is True


async def test_extractor_passes_parallel_tool_calls_false() -> None:
    fake = FakeLLM([_emit([])])
    await extract(fake, [_user(1)], [])
    assert fake.calls[0].parallel_tool_calls is False


def test_second_emit_ops_call_is_ignored() -> None:
    def call(ops: list[dict[str, object]]) -> llm.FunctionToolCall:
        return llm.FunctionToolCall(name="emit_ops", arguments=json.dumps({"ops": ops}), call_id="c")

    response = llm.CollectedResponse(tool_calls=[call(TWO_ADDS[:1]), call(TWO_ADDS)])
    result = ops_from(response)
    assert [op.value for op in result.ops] == ["Ada"]
    assert result.ignored_calls == 1


async def test_result_reports_ms_and_prompt_tokens() -> None:
    fake = FakeLLM([_emit([], prompt_tokens=321)])
    result = await extract(fake, [_user(1)], [])
    assert result.prompt_tokens == 321
    assert isinstance(result.ms, int) and result.ms >= 0


async def test_provider_error_propagates() -> None:
    fake = FakeLLM([FakeResponse(error="overloaded")])
    with pytest.raises(APIStatusError):
        await extract(fake, [_user(1)], [])


def test_system_prompt_asks_for_the_turn_on_update_and_delete() -> None:
    # UpdateOp needs a turn_id: an UPDATE without one is dropped as malformed and the correction is lost.
    assert "UPDATE fact_id" in EXTRACTOR_SYSTEM
    update_rule = next(line for line in EXTRACTOR_SYSTEM.splitlines() if "UPDATE fact_id" in line)
    assert "turn_id" in update_rule


async def test_an_update_citing_its_turn_parses() -> None:
    update = _op(op="UPDATE", fact_id=12, value="Globex", turn_id="item_u1")
    fake = FakeLLM([_emit([update])])
    result = await extract(fake, [_user(1, "actually I'm at Globex now")], [_fact(12, "company", "Initech")])
    assert [(type(op).__name__, op.fact_id) for op in result.ops] == [("UpdateOp", 12)]


async def test_no_visitor_turn_means_no_call() -> None:
    unheard = Turn(turn_id="item_a1", role="agent", text="Globex", channel="voice", interrupted=True)
    for turns in ([], [_agent(1)], [unheard]):
        fake = FakeLLM([])
        result = await extract(fake, turns, [_fact(3, "name", "Ada")])
        assert fake.calls == []
        assert result.ops == [] and result.tool_called is False


def test_window_rejects_a_negative_start() -> None:
    with pytest.raises(ValueError):
        extraction_window([_user(1), _user(2)], first_new=-1)


def test_system_prompt_states_the_confidence_range() -> None:
    # Review C4-06 M6: an op with confidence 90 fails validation and is dropped whole.
    rule = next(line for line in EXTRACTOR_SYSTEM.splitlines() if "confidence" in line)
    assert "0 to 1" in rule

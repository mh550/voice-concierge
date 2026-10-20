"""ClaudeLLM against a fake AsyncAnthropic: what each stage puts on the wire (spec D5, B1, §4.10), all offline."""

from typing import Any

import pytest
from livekit.agents import APIStatusError, llm

from concierge import claude_llm
from concierge.claude_llm import (
    FALLBACK_BETA,
    TRAILING_USER_TEXT,
    ClaudeLLM,
    ClaudeLLMStream,
    build_claude_llm,
    ends_on_user,
    merge_kwargs,
)
from concierge.config import Settings
from concierge.testing.fake_anthropic import FakeAnthropicClient, reply_events

STAGES = ["conversation", "extractor", "summarizer"]
BACKGROUND = ["extractor", "summarizer"]


@pytest.fixture(autouse=True)
def offline_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The plugin checks for a key even when given a client; this one never leaves the process.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    for name in ("LLM_PROVIDER", *(f"{stage.upper()}_MODEL" for stage in STAGES)):
        monkeypatch.delenv(f"CONCIERGE_{name}", raising=False)


def _ctx(*turns: tuple[str, str]) -> llm.ChatContext:
    ctx = llm.ChatContext.empty()
    ctx.add_message(role="system", content="You are Michael's portfolio concierge.")
    for role, text in turns or (("user", "hello"),):
        ctx.add_message(role=role, content=text)  # type: ignore[arg-type]
    return ctx


async def _send(stage: str, ctx: llm.ChatContext | None = None, **chat_kwargs: Any) -> tuple[str, dict[str, Any]]:
    client = FakeAnthropicClient([reply_events("Hi there.")])
    model = getattr(Settings(), f"{stage}_model")
    stream = build_claude_llm(stage, model, client=client).chat(chat_ctx=ctx or _ctx(), **chat_kwargs)  # type: ignore[arg-type]
    text = (await stream.collect()).text
    assert len(client.fake_messages.calls) == 1
    return text, client.fake_messages.calls[0]


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list | tuple):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.mark.parametrize(
    ("stage", "model"),
    [("conversation", "claude-haiku-5-5"), ("extractor", "claude-sonnet-5-5"), ("summarizer", "claude-sonnet-5-5")],
)
async def test_stage_sends_its_model_and_streams_text(stage: str, model: str) -> None:
    text, sent = await _send(stage)
    assert text == "Hi there."
    assert sent["model"] == model
    assert sent["stream"] is True


async def test_conversation_disables_thinking_and_caches_the_system_block() -> None:
    _, sent = await _send("conversation")
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert sent["max_tokens"] == 1024  # the plugin's default; a spoken reply is short
    assert "output_config" not in sent and "extra_body" not in sent


@pytest.mark.parametrize("stage", BACKGROUND)
async def test_background_stage_runs_at_low_effort_with_server_side_fallback(stage: str) -> None:
    _, sent = await _send(stage)
    assert sent["output_config"] == {"effort": "low"}
    assert sent["max_tokens"] == 4096
    assert sent["extra_headers"] == {"anthropic-beta": FALLBACK_BETA}
    assert FALLBACK_BETA == "server-side-fallback-2026-07-01"
    assert sent["extra_body"] == {"fallbacks": "default"}
    assert "thinking" not in sent


@pytest.mark.parametrize("stage", STAGES)
async def test_no_sampling_parameters_are_sent(stage: str) -> None:
    _, sent = await _send(stage)
    assert not _keys(sent) & {"temperature", "top_k", "top_p"}


@pytest.mark.parametrize("stage", STAGES)
async def test_a_context_ending_on_the_assistant_is_sent_ending_on_the_user(stage: str) -> None:
    ctx = _ctx(("user", "Who is Michael?"), ("assistant", "He builds voice agents."))
    before = [item.id for item in ctx.items]
    _, sent = await _send(stage, ctx)
    assert sent["messages"][-1]["role"] == "user"
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    assert [item.id for item in ctx.items] == before  # the caller's context is left alone


async def test_a_context_ending_on_the_user_is_sent_unchanged() -> None:
    _, sent = await _send("conversation", _ctx(("user", "Hi"), ("assistant", "Hello!"), ("user", "Tell me more")))
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    assert sent["messages"][-1]["content"][-1]["text"] == "Tell me more"


async def test_thinking_before_the_text_yields_only_the_text() -> None:
    client = FakeAnthropicClient([reply_events("Only this is spoken.", thinking="private reasoning")])
    stream = build_claude_llm("conversation", "claude-haiku-5-5", client=client).chat(chat_ctx=_ctx())
    async with stream:
        content = [c.delta.content for c in [chunk async for chunk in stream] if c.delta and c.delta.content]
    assert "".join(content) == "Only this is spoken."


async def test_caller_kwargs_merge_with_the_stage_kwargs() -> None:
    _, sent = await _send(
        "extractor",
        extra_kwargs={"extra_headers": {"x-trace": "1"}, "extra_body": {"metadata": {"k": "v"}}, "max_tokens": 50},
    )
    assert sent["extra_headers"] == {"anthropic-beta": FALLBACK_BETA, "x-trace": "1"}
    assert sent["extra_body"] == {"fallbacks": "default", "metadata": {"k": "v"}}
    assert sent["max_tokens"] == 4096  # chat() overwrites max_tokens from extra_kwargs (plugin llm.py:183)


def test_merge_kwargs_replaces_tagged_unions_and_merges_config_bags() -> None:
    base = {"thinking": {"type": "enabled", "budget_tokens": 5}, "output_config": {"effort": "low"}}
    extra = {"thinking": {"type": "disabled"}, "output_config": {"format": {"type": "json_schema"}}}
    assert merge_kwargs(base, extra) == {
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low", "format": {"type": "json_schema"}},
    }


async def test_caller_thinking_replaces_the_stage_thinking() -> None:
    _, sent = await _send("conversation", extra_kwargs={"thinking": {"type": "adaptive"}})
    assert sent["thinking"] == {"type": "adaptive"}


async def test_stage_kwargs_are_not_shared_between_requests() -> None:
    client = FakeAnthropicClient([reply_events("a"), reply_events("b")])
    model = build_claude_llm("summarizer", "claude-sonnet-5-5", client=client)
    for _ in range(2):
        await model.chat(chat_ctx=_ctx()).collect()
    first, second = client.fake_messages.calls
    first["extra_body"]["fallbacks"] = "mutated"
    assert second["extra_body"] == {"fallbacks": "default"}
    assert claude_llm.BACKGROUND_KWARGS["extra_body"] == {"fallbacks": "default"}


def test_is_the_plugin_llm() -> None:
    from livekit.plugins import anthropic

    built = build_claude_llm("conversation", "claude-haiku-5-5", client=FakeAnthropicClient())
    assert isinstance(built, ClaudeLLM) and isinstance(built, anthropic.LLM)
    assert built.model == "claude-haiku-5-5"
    assert built.provider == "api.anthropic.com"


async def test_the_fake_rejects_a_keyword_the_sdk_lacks() -> None:
    with pytest.raises(TypeError):
        await FakeAnthropicClient().messages.create(model="m", max_tokens=1, messages=[], output_confg={})


async def test_stop_reason_is_recorded() -> None:
    stream = build_claude_llm("conversation", "claude-haiku-5-5", client=FakeAnthropicClient()).chat(chat_ctx=_ctx())
    await stream.collect()
    assert isinstance(stream, ClaudeLLMStream)
    assert stream.stop_reason == "end_turn"


@pytest.mark.parametrize("stage", BACKGROUND)
async def test_a_refused_background_call_raises_and_is_not_retried(stage: str) -> None:
    client = FakeAnthropicClient([reply_events("partial summ", stop_reason="refusal")])
    stream = build_claude_llm(stage, "claude-sonnet-5-5", client=client).chat(chat_ctx=_ctx())
    with pytest.raises(APIStatusError, match="refus"):
        await stream.collect()
    assert len(client.fake_messages.calls) == 1


async def test_a_refused_conversation_reply_is_kept_and_marked() -> None:
    client = FakeAnthropicClient([reply_events("I can't help with that.", stop_reason="refusal")])
    stream = build_claude_llm("conversation", "claude-haiku-5-5", client=client).chat(chat_ctx=_ctx())
    assert (await stream.collect()).text == "I can't help with that."  # already spoken; raising can't unsay it
    assert stream.stop_reason == "refusal"


def _call(ctx: llm.ChatContext, name: str = "lookup") -> None:
    call = llm.FunctionCall(call_id=f"c-{len(ctx.items)}", name=name, arguments="{}")
    ctx.items.append(call)
    ctx.items.append(llm.FunctionCallOutput(call_id=call.call_id, name=name, output="ok", is_error=False))


def _ends_on_output() -> llm.ChatContext:
    ctx = _ctx(("user", "Projects?"))
    _call(ctx)
    return ctx


def _output_then_assistant() -> llm.ChatContext:
    ctx = _ends_on_output()
    ctx.add_message(role="assistant", content="He built three.")
    return ctx


def _ends_on_system() -> llm.ChatContext:
    ctx = _ctx(("user", "Hi"), ("assistant", "Hello!"))
    ctx.add_message(role="system", content="The visitor is back.")
    return ctx


def _ends_on_empty_assistant() -> llm.ChatContext:
    ctx = _ctx(("user", "Hi"))
    ctx.add_message(role="assistant", content=[])
    return ctx


@pytest.mark.parametrize(
    ("make", "appended"),
    [
        (_ends_on_output, False),
        (_output_then_assistant, True),
        (_ends_on_system, False),
        (_ends_on_empty_assistant, False),
    ],
)
def test_ends_on_user_looks_at_the_formatted_messages(make: Any, appended: bool) -> None:
    ctx = make()
    out = ends_on_user(ctx)
    messages, _ = out.to_provider_format(format="anthropic")
    assert messages[-1]["role"] == "user"
    assert (out is not ctx) == appended
    assert (messages[-1]["content"][-1].get("text") == TRAILING_USER_TEXT) == appended

"""Only what was heard (spec §4.0; plan C4 "Heard text"): an interrupted agent turn reaches the extractor as the
text the visitor heard, never the text the LLM generated."""

from types import SimpleNamespace

from livekit.agents import llm

from concierge.config import Settings
from concierge.dispatch import DispatchInfo
from concierge.extractor import build_extractor_ctx, extract
from concierge.session import room_start_kwargs
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.text_input import ChannelTags
from concierge.turns import Turn, turn_from_message

FULL = "Michael worked at Acme and at Globex"
HEARD = "Michael worked at Acme"


def _empty_ops() -> FakeLLM:
    return FakeLLM([FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": []}))])


def _ctx_text(ctx: llm.ChatContext) -> str:
    return "\n".join(m.text_content or "" for m in ctx.messages())


def _turns() -> list[Turn]:
    return [
        Turn(turn_id="item_u1", role="user", text="Where did Michael work?", channel="voice"),
        Turn(turn_id="item_a1", role="agent", text=FULL, channel="voice", interrupted=True, heard_text=HEARD),
        Turn(turn_id="item_u2", role="user", text="I work at Initech myself", channel="voice"),
    ]


async def test_interrupted_agent_turn_reaches_the_extractor_as_heard_text_only() -> None:
    fake = _empty_ops()
    await extract(fake, _turns(), [])
    text = _ctx_text(fake.calls[0].chat_ctx)
    assert "Acme" in text
    assert "Globex" not in text


def test_turn_from_an_interrupted_message_keeps_its_recorded_content() -> None:
    # 1.8.8 records an interrupted reply's content as the forwarded (heard) text (agent_activity.py:3905-3936).
    msg = llm.ChatMessage(role="assistant", content=[HEARD], interrupted=True)
    turn = turn_from_message(msg)
    assert turn is not None
    assert turn.role == "agent"
    assert turn.interrupted is True
    assert turn.heard_text == HEARD
    assert turn.turn_id == msg.id


def test_turn_from_a_user_message_takes_the_channel_and_low_confidence() -> None:
    msg = llm.ChatMessage(role="user", content=["I'm Ada"], transcript_confidence=0.62)
    turn = turn_from_message(msg, "text")
    assert turn is not None
    assert (turn.role, turn.text, turn.channel, turn.interrupted) == ("user", "I'm Ada", "text", False)
    assert turn.confidence == 0.62
    sure = turn_from_message(llm.ChatMessage(role="user", content=["hi"], transcript_confidence=1.0))
    assert sure is not None and sure.confidence is None and sure.channel == "voice"


def test_turn_from_message_skips_other_roles_and_empty_text() -> None:
    assert turn_from_message(llm.ChatMessage(role="system", content=["rules"])) is None
    assert turn_from_message(llm.ChatMessage(role="developer", content=["rules"])) is None
    assert turn_from_message(llm.ChatMessage(role="user", content=["  "])) is None
    assert turn_from_message(llm.ChatMessage(role="assistant", content=[])) is None


def test_interrupted_turn_without_heard_text_is_left_out() -> None:
    turns = [
        Turn(turn_id="item_a0", role="agent", text="Globex was great", channel="voice", interrupted=True),
        Turn(turn_id="item_u1", role="user", text="hello", channel="voice"),
    ]
    text = _ctx_text(build_extractor_ctx(turns, []))
    assert "item_a0" not in text
    assert "Globex" not in text
    assert "item_u1" in text


def test_expr_markup_is_stripped_from_agent_turns() -> None:
    msg = llm.ChatMessage(role="assistant", content=['<expr name="laugh"/>Nice to meet you.'])
    turn = turn_from_message(msg)
    assert turn is not None
    assert "<expr" not in turn.text
    assert "Nice to meet you." in turn.text


async def test_extractor_call_uses_tool_choice_auto() -> None:
    fake = _empty_ops()
    await extract(fake, _turns(), [])
    assert fake.calls[0].tool_choice == "auto"


async def test_extractor_ctx_tells_the_model_to_call_emit_ops_once() -> None:
    fake = _empty_ops()
    await extract(fake, _turns(), [])
    ctx = fake.calls[0].chat_ctx
    system = ctx.messages()[0]
    assert system.role == "system"
    assert "Call the emit_ops tool exactly once." in (system.text_content or "")
    assert "empty ops list" in (system.text_content or "")


async def test_extractor_call_has_exactly_one_tool_named_emit_ops() -> None:
    fake = _empty_ops()
    await extract(fake, _turns(), [])
    tools = fake.calls[0].tools
    assert len(tools) == 1
    assert isinstance(tools[0], llm.FunctionTool)
    assert tools[0].info.name == "emit_ops"


def test_room_options_keep_transcription_sync() -> None:
    # RoomIO syncs the transcript to playback unless sync_transcription is False (room_io.py:177); with it off, an
    # interrupted reply would record its whole forwarded text, not what was heard.
    kwargs = room_start_kwargs(
        SimpleNamespace(room=object()),  # type: ignore[arg-type]
        DispatchInfo(visitor_id="9b2f0c4e-0d7a-4a59-9a43-5b1c6a0e4b11", channel_hint="web"),
        Settings(),
        ChannelTags(),
    )
    text_output = kwargs["room_options"].get_text_output_options()
    assert text_output is not None
    assert text_output.sync_transcription is not False


async def test_an_interrupted_message_reaches_the_extractor_as_its_recorded_content() -> None:
    # End to end from what 1.8 adds to the chat context: the message's content is what played.
    agent = turn_from_message(llm.ChatMessage(role="assistant", content=[HEARD], interrupted=True))
    user = turn_from_message(llm.ChatMessage(role="user", content=["I work at Initech myself"]))
    assert agent is not None and user is not None
    fake = _empty_ops()
    await extract(fake, [agent, user], [])
    text = _ctx_text(fake.calls[0].chat_ctx)
    assert HEARD in text and "Globex" not in text

import ast
import asyncio
import json
import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.voice.agent_session import RecordingOptions
from livekit.agents.voice.room_io import RoomOptions, TextInputOptions
from livekit.agents.voice.room_io.types import TextInputEvent, _default_text_input_cb

from concierge import session, worker
from concierge.agent import ConciergeAgent
from concierge.greeting import INTRODUCTION
from concierge.knowledge import load_pack
from concierge.testing.fake_llm import FakeLLM
from concierge.testing.recording_session import RecordingSession
from concierge.text_input import ChannelTags, make_text_input_cb

VISITOR = "3f2b8c1e-9a4d-4c7b-8e21-5d6f7a8b9c0d"
WORKER_PY = Path(worker.__file__)


# --- recording options (B11) ---------------------------------------------------------------------------------


def test_recording_options_default_keeps_audio_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONCIERGE_RECORD_AUDIO", raising=False)
    assert session.recording_options() == {"audio": False, "redaction": True}


def test_recording_options_audio_on_for_michaels_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONCIERGE_RECORD_AUDIO", "1")
    assert session.recording_options() == {"audio": True, "redaction": True}


def test_recording_option_keys_are_those_of_recording_options() -> None:
    assert set(session.recording_options()) <= set(RecordingOptions.__annotations__)


# --- import and registration ---------------------------------------------------------------------------------


def test_import_needs_no_keys() -> None:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LIVEKIT_", "CONCIERGE_"))
        and k not in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "DEEPGRAM_API_KEY")
    }
    code = (
        "import concierge.worker as w; "
        "s = w.server; "
        "print(type(s).__name__, s._agent_name, s._shutdown_process_timeout, "
        "s._entrypoint_fnc is w.entrypoint, s._request_fnc is w.on_request, s.setup_fnc is w.prewarm)"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["AgentServer", "concierge", "30", "True", "True", "True"]


def _module_level_calls(tree: ast.Module) -> set[str]:
    """Names of everything called by module-level code (function and class bodies excluded, decorators included)."""
    names: set[str] = set()
    stack: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            stack.extend(node.decorator_list)
        else:
            stack.append(node)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
        stack.extend(ast.iter_child_nodes(node))
    return names


@pytest.mark.parametrize("path", [WORKER_PY, Path(session.__file__)])
def test_no_provider_is_built_at_import(path: Path) -> None:
    calls = _module_level_calls(ast.parse(path.read_text()))
    if path == WORKER_PY:
        assert "AgentServer" in calls and "rtc_session" in calls  # the walker sees module-level calls
    assert not calls & {"with_openrouter", "build_llm", "build_stt", "build_tts", "load", "AgentSession", "LLM"}


async def test_on_request_accepts() -> None:
    seen: list[str] = []

    class FakeRequest:
        async def accept(self, **_: Any) -> None:
            seen.append("accept")

        async def reject(self, **_: Any) -> None:
            seen.append("reject")

    await worker.on_request(FakeRequest())  # type: ignore[arg-type]
    assert seen == ["accept"]


def test_prewarm_loads_silero_vad_once(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[object] = []
    monkeypatch.setattr(worker.silero.VAD, "load", lambda: loads.append(object()) or loads[-1])

    class FakeProc:
        def __init__(self) -> None:
            self.userdata: dict[str, Any] = {}

    proc = FakeProc()
    worker.prewarm(proc)  # type: ignore[arg-type]
    assert len(loads) == 1 and proc.userdata["vad"] is loads[0]


# --- text input wrapper (§4.5) -------------------------------------------------------------------------------


class FakeTextSession:
    """Just what `_default_text_input_cb` touches on an AgentSession (voice/room_io/types.py)."""

    def __init__(self, order: list[str]) -> None:
        self.order = order

    @asynccontextmanager
    async def _claim_user_turn(self) -> AsyncIterator[None]:
        self.order.append("claim")
        yield

    async def interrupt(self) -> None:
        self.order.append("interrupt")

    def generate_reply(self, *, user_input: str) -> None:
        self.order.append(f"generate_reply:{user_input}")


async def test_text_cb_tags_before_the_default_generates_a_reply() -> None:
    order: list[str] = []
    cb = make_text_input_cb(lambda ev: order.append(f"on_text:{ev.text}"))
    await cb(FakeTextSession(order), TextInputEvent(text="hello"))  # type: ignore[arg-type]
    assert order == ["on_text:hello", "claim", "interrupt", "generate_reply:hello"]


async def test_text_cb_delegates_to_the_framework_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # The wrapper must delegate (keep the framework's turn handling), not reimplement it.
    seen: list[str] = []

    async def spy(sess: Any, ev: TextInputEvent) -> None:
        seen.append(ev.text)

    monkeypatch.setattr("concierge.text_input._default_text_input_cb", spy)
    await make_text_input_cb(lambda ev: None)(object(), TextInputEvent(text="hi"))  # type: ignore[arg-type]
    assert seen == ["hi"]


def test_channel_tags_match_typed_messages_once() -> None:
    tags = ChannelTags()
    tags.on_text(TextInputEvent(text="I'm Ada"))
    assert tags.channel_of("What does Michael do?") == "voice"
    assert tags.channel_of("I'm Ada") == "text"
    assert tags.channel_of("I'm Ada") == "voice"  # the same words spoken later are voice


def test_channel_tags_are_bounded() -> None:
    tags = ChannelTags()
    for i in range(ChannelTags.MAX_PENDING + 5):
        tags.on_text(TextInputEvent(text=f"t{i}"))
    assert tags.channel_of("t0") == "voice"  # the oldest unmatched tags were dropped
    assert tags.channel_of(f"t{ChannelTags.MAX_PENDING + 4}") == "text"


async def test_text_cb_still_delegates_when_on_text_raises() -> None:
    order: list[str] = []

    def broken(ev: TextInputEvent) -> None:
        raise RuntimeError("tagging failed")

    await make_text_input_cb(broken)(FakeTextSession(order), TextInputEvent(text="hello"))  # type: ignore[arg-type]
    assert order == ["claim", "interrupt", "generate_reply:hello"]


async def test_text_cb_untags_a_turn_the_default_drops() -> None:
    # interrupt() raises during uninterruptible speech; RoomIO then drops the typed turn, so its tag must go too,
    # or the same words spoken later would be recorded as typed.
    class Uninterruptible(FakeTextSession):
        async def interrupt(self) -> None:
            raise RuntimeError("speech is not interruptible")

    tags = ChannelTags()
    cb = make_text_input_cb(tags.on_text, on_dropped=tags.on_dropped)
    with pytest.raises(RuntimeError):
        await cb(Uninterruptible([]), TextInputEvent(text="my name is Ada"))  # type: ignore[arg-type]
    assert tags.channel_of("my name is Ada") == "voice"


async def test_typed_turn_through_a_real_session_is_tagged_text() -> None:
    tags = ChannelTags()
    cb = make_text_input_cb(tags.on_text)
    added: list[tuple[str, str]] = []
    replied = asyncio.Event()

    with fake_job_context():
        async with AgentSession(llm=FakeLLM(["Hi, I'm Michael's concierge."])) as session:

            @session.on("conversation_item_added")
            def _on_item(ev: Any) -> None:
                item = ev.item
                if isinstance(item, llm.ChatMessage) and item.text_content:
                    channel = tags.channel_of(item.text_content) if item.role == "user" else "-"
                    added.append((item.role, channel))
                    if item.role == "assistant":
                        replied.set()

            await session.start(ConciergeAgent(load_pack()))
            await cb(session, TextInputEvent(text="I'm Ada, typing"))
            await asyncio.wait_for(replied.wait(), timeout=5)

    assert added == [("user", "text"), ("assistant", "-")]


# --- entrypoint ----------------------------------------------------------------------------------------------


async def test_entrypoint_starts_the_session(recording_session: type[RecordingSession]) -> None:
    metadata = json.dumps({"visitor_id": VISITOR, "channel_hint": "web"})
    with fake_job_context(job_metadata=metadata) as ctx:
        ctx.proc.userdata["vad"] = "vad"
        await worker.entrypoint(ctx)

    (session,) = recording_session.instances
    assert session.kwargs["stt"] == "stt" and session.kwargs["tts"] == "tts" and session.kwargs["vad"] == "vad"
    assert isinstance(session.kwargs["llm"], FakeLLM)
    # D7: VAD only, and interruptions by VAD too (otherwise dev/console mode builds the hosted adaptive detector).
    assert session.kwargs["turn_handling"] == {"turn_detection": "vad", "interruption": {"mode": "vad"}}

    started = session.started
    assert started is not None
    assert isinstance(started["agent"], ConciergeAgent)
    assert session.replies == [{"instructions": INTRODUCTION}]  # the greeting, queued after start
    assert started["room"] is ctx.room
    assert started["record"] == {"audio": False, "redaction": True}
    options = started["room_options"]
    assert isinstance(options, RoomOptions)
    assert options.participant_identity == f"visitor-{VISITOR}"  # §6
    assert isinstance(options.text_input, TextInputOptions)
    assert options.text_input.text_input_cb is not _default_text_input_cb

    # The installed callback tags the channel before the default turn handling runs.
    order: list[str] = []
    await options.text_input.text_input_cb(FakeTextSession(order), TextInputEvent(text="typed hello"))
    assert order == ["claim", "interrupt", "generate_reply:typed hello"]
    (tags,) = recording_session.tags
    assert tags.channel_of("typed hello") == "text"

    # A typed turn the default drops is untagged (on_dropped is wired to the same tags).
    class Uninterruptible(FakeTextSession):
        async def interrupt(self) -> None:
            raise RuntimeError("speech is not interruptible")

    with pytest.raises(RuntimeError):
        await options.text_input.text_input_cb(Uninterruptible([]), TextInputEvent(text="dropped"))
    assert tags.channel_of("dropped") == "voice"


@pytest.mark.parametrize("metadata", ["", '{"visitor_id": "nope"}'])
async def test_entrypoint_logs_and_ends_the_job_on_bad_metadata(
    metadata: str,
    recording_session: type[RecordingSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reasons: list[str] = []
    with fake_job_context(job_metadata=metadata) as ctx:
        monkeypatch.setattr(ctx, "shutdown", lambda reason="": reasons.append(reason))
        with caplog.at_level(logging.WARNING, logger="concierge.worker"):
            await worker.entrypoint(ctx)

    assert reasons == ["bad dispatch metadata"]
    assert recording_session.instances == []
    assert any("dispatch metadata" in r.getMessage() for r in caplog.records)
    assert "nope" not in caplog.text  # visitor-supplied values stay out of the journal
    assert not Path(os.environ["CONCIERGE_DB_PATH"]).parent.exists()  # ended before the store was opened

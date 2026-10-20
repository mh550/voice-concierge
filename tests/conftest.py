import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from livekit.agents import AgentSession

from concierge import session
from concierge.config import Settings
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.recording_session import RecordingSession
from concierge.text_input import ChannelTags


class FakeClock:
    """A settable ms clock for Store(clock=...)."""

    def __init__(self, start_ms: int = 1_760_000_000_000) -> None:
        self.now = start_ms

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


@pytest.fixture(autouse=True)
def _temp_db_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The entrypoint opens Settings().db_path: no test may touch ~/.local/share/voice-concierge/."""
    monkeypatch.setenv("CONCIERGE_DB_PATH", str(tmp_path / "concierge-db" / "concierge.db"))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(tmp_path, clock):
    s = Store(tmp_path / "memory.db", clock=clock)
    yield s
    s.close()


@pytest.fixture
def visitor_id() -> str:
    return str(uuid.uuid4())


# --- the session's AgentSession seam (tests/test_worker.py, tests/test_preload.py) ---------------------------


@pytest.fixture
def recording_session(monkeypatch: pytest.MonkeyPatch) -> type[RecordingSession]:
    RecordingSession.instances = []
    monkeypatch.setattr(session, "AgentSession", RecordingSession)
    fake = FakeLLM([])
    monkeypatch.setattr(session, "build_llm", lambda stage, settings=None: fake)
    monkeypatch.setattr(session, "build_stt", lambda settings=None: "stt")
    monkeypatch.setattr(session, "build_tts", lambda settings=None: "tts")
    monkeypatch.delenv("CONCIERGE_RECORD_AUDIO", raising=False)
    RecordingSession.tags = []

    class KeptChannelTags(ChannelTags):
        def __init__(self) -> None:
            super().__init__()
            RecordingSession.tags.append(self)

    monkeypatch.setattr(session, "ChannelTags", KeptChannelTags)
    return RecordingSession


# --- a real AgentSession over FakeLLMs (tests/test_session.py, tests/test_erasure_wins.py) --------------------

NO_OPS = FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": []}))


@pytest.fixture
def extractor() -> FakeLLM:
    """The extractor LLM start_session's MemoryWriter builds (via build_llm("extractor")): no change, 8 times."""
    return FakeLLM([NO_OPS] * 8)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, extractor: FakeLLM) -> list[FakeLLM]:
    """Each build_session gets a real AgentSession over a new FakeLLM (kept here, in order); the extractor is
    `extractor`, so no test builds a real provider."""
    made: list[FakeLLM] = []

    def build(ctx: Any, settings: Settings) -> AgentSession:
        made.append(FakeLLM(["Hello there.", "Michael builds voice agents."]))
        return AgentSession(llm=made[-1])

    monkeypatch.setattr(session, "build_session", build)
    monkeypatch.setattr(session, "room_start_kwargs", lambda *args: {})
    monkeypatch.setattr(session, "build_llm", lambda stage, settings=None: extractor)
    return made


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Store]:
    s = Store(tmp_path / "session.db")
    yield s
    try:
        s.close()
    except sqlite3.ProgrammingError:  # the shutdown callback closed it
        pass

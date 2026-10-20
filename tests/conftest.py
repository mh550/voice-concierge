import uuid

import pytest

from concierge import session
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM
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

import uuid

import pytest

from concierge.store import Store


class FakeClock:
    """A settable ms clock for Store(clock=...)."""

    def __init__(self, start_ms: int = 1_760_000_000_000) -> None:
        self.now = start_ms

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


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

"""DepartureWatcher (spec 2026-10-21 §3; plan 2026-10-21-V1 "The watcher"): the visitor's participant_disconnected
starts a grace, a participant_connected with the same identity cancels it, and when it runs out on_left is awaited
once. Driven by FakeRoom (a real rtc.Room), whose emit reaches handlers registered with room.on."""

import asyncio
import inspect
from dataclasses import dataclass

import pytest

from concierge.departure import DEPARTURE_GRACE_S, DepartureWatcher
from concierge.testing.fake_room import FakeRoom

VISITOR = "visitor-3f2b8c1e"
GRACE_S = 0.05


@dataclass
class Participant:  # what the handlers read of an rtc.RemoteParticipant: .identity (rtc/participant.py:164)
    identity: str


class Calls:
    def __init__(self) -> None:
        self.n = 0

    async def on_left(self) -> None:
        self.n += 1


@pytest.fixture
async def room() -> FakeRoom:  # async: rtc.Room takes the running loop
    return FakeRoom()


@pytest.fixture
def calls() -> Calls:
    return Calls()


@pytest.fixture
async def watcher(room: FakeRoom, calls: Calls) -> DepartureWatcher:
    w = DepartureWatcher(room, VISITOR, calls.on_left, grace_s=GRACE_S)
    w.start()
    return w


def test_the_default_grace_is_twenty_seconds() -> None:
    assert DEPARTURE_GRACE_S == 20.0


async def test_the_visitor_leaving_calls_on_left_once_after_the_grace(
    room: FakeRoom, calls: Calls, watcher: DepartureWatcher
) -> None:
    room.emit("participant_disconnected", Participant(VISITOR))
    assert watcher.pending
    await asyncio.sleep(GRACE_S / 2)
    assert calls.n == 0
    await asyncio.sleep(GRACE_S * 2)
    assert calls.n == 1
    assert not watcher.pending


async def test_the_visitor_returning_inside_the_grace_cancels_it(
    room: FakeRoom, calls: Calls, watcher: DepartureWatcher
) -> None:
    room.emit("participant_disconnected", Participant(VISITOR))
    await asyncio.sleep(GRACE_S / 2)
    room.emit("participant_connected", Participant(VISITOR))
    assert not watcher.pending
    await asyncio.sleep(GRACE_S * 3)
    assert calls.n == 0
    assert not watcher.pending


async def test_another_participant_leaving_starts_nothing(
    room: FakeRoom, calls: Calls, watcher: DepartureWatcher
) -> None:
    room.emit("participant_disconnected", Participant("visitor-someone-else"))
    assert not watcher.pending
    await asyncio.sleep(GRACE_S * 3)
    assert calls.n == 0


async def test_another_participant_joining_does_not_cancel_the_grace(
    room: FakeRoom, calls: Calls, watcher: DepartureWatcher
) -> None:
    room.emit("participant_disconnected", Participant(VISITOR))
    room.emit("participant_connected", Participant("visitor-someone-else"))
    assert watcher.pending
    await asyncio.sleep(GRACE_S * 3)
    assert calls.n == 1


async def test_cancel_during_the_grace_stops_on_left(room: FakeRoom, calls: Calls, watcher: DepartureWatcher) -> None:
    room.emit("participant_disconnected", Participant(VISITOR))
    watcher.cancel()
    assert not watcher.pending
    await asyncio.sleep(GRACE_S * 3)
    assert calls.n == 0
    watcher.cancel()  # idempotent


async def test_cancel_stops_a_later_departure_too(room: FakeRoom, calls: Calls, watcher: DepartureWatcher) -> None:
    watcher.cancel()
    room.emit("participant_disconnected", Participant(VISITOR))
    assert not watcher.pending
    await asyncio.sleep(GRACE_S * 3)
    assert calls.n == 0


async def test_two_disconnects_in_a_row_start_one_grace(
    room: FakeRoom, calls: Calls, watcher: DepartureWatcher
) -> None:
    room.emit("participant_disconnected", Participant(VISITOR))
    await asyncio.sleep(GRACE_S / 2)
    room.emit("participant_disconnected", Participant(VISITOR))  # no restart: the first grace still ends on time
    await asyncio.sleep(GRACE_S * 0.75)
    assert calls.n == 1
    await asyncio.sleep(GRACE_S * 2)
    assert calls.n == 1


async def test_the_handlers_are_plain_functions(room: FakeRoom, watcher: DepartureWatcher) -> None:
    # rtc.Room.emit calls handlers synchronously (EventEmitter); a coroutine handler would never be awaited.
    for event in ("participant_disconnected", "participant_connected"):
        handlers = room._events[event]
        assert handlers and not any(inspect.iscoroutinefunction(h) for h in handlers)


async def test_a_failing_on_left_is_logged_not_raised(room: FakeRoom, caplog: pytest.LogCaptureFixture) -> None:
    async def boom() -> None:
        raise RuntimeError("closing failed")

    w = DepartureWatcher(room, VISITOR, boom, grace_s=GRACE_S)
    w.start()
    room.emit("participant_disconnected", Participant(VISITOR))
    await asyncio.sleep(GRACE_S * 3)
    assert not w.pending
    assert "RuntimeError" in caplog.text


async def test_cancel_from_inside_on_left_does_not_cut_it_short(room: FakeRoom) -> None:
    # end_session cancels the watcher first, and on_left is what calls end_session.
    done: list[str] = []
    w: DepartureWatcher

    async def on_left() -> None:
        w.cancel()
        await asyncio.sleep(0)
        done.append("closed")

    w = DepartureWatcher(room, VISITOR, on_left, grace_s=GRACE_S)
    w.start()
    room.emit("participant_disconnected", Participant(VISITOR))
    await asyncio.sleep(GRACE_S * 3)
    assert done == ["closed"]

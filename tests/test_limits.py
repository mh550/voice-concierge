"""The abuse limits (spec B7; plan C6 "concierge/limits.py"): the 10-minute timer and the daily cap."""

import asyncio
import inspect
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from livekit.agents import AgentSession
from livekit.agents.testing import fake_job_context

from concierge import limits
from concierge import session as concierge_session
from concierge.contract import FORGET_ME_METHOD, GET_MEMORY_METHOD
from concierge.limits import (
    DAILY_CAP_LINE,
    TIME_UP_LINE,
    over_daily_cap,
    say_and_end,
    start_session_timer,
    utc_day,
)
from concierge.store import Store, now_ms
from concierge.testing.fake_llm import FakeLLM
from concierge.testing.fake_room import FakeRoom
from concierge.testing.sessions import METADATA, VISITOR, shutdown, start
from concierge.testing.speaking_session import FakeSpeakingSession

DAY = "2026-10-20"


async def test_session_timer_says_one_line_and_ends() -> None:
    session = FakeSpeakingSession()
    ended: list[str] = []
    began = time.monotonic()
    timer = start_session_timer(session, 0.2, ended.append)
    while not ended:
        assert time.monotonic() - began < 0.5, "the session did not end within 0.5 s"
        await asyncio.sleep(0.01)
    assert time.monotonic() - began >= 0.2
    assert [text for text, _ in session.said] == [TIME_UP_LINE]
    assert ended == ["time limit"]
    await timer


async def test_session_timer_is_cancelled_before_it_fires() -> None:
    session = FakeSpeakingSession()
    ended: list[str] = []
    timer = start_session_timer(session, 0.2, ended.append)
    timer.cancel()
    await asyncio.sleep(0.3)
    assert session.said == [] and ended == []


async def test_say_and_end_keeps_the_line_out_of_the_chat_and_uninterruptible() -> None:
    session = FakeSpeakingSession()
    ended: list[str] = []
    await say_and_end(session, "Bye.", ended.append, "test")
    ((text, kwargs),) = session.said
    assert text == "Bye." and kwargs == {"allow_interruptions": False, "add_to_chat_ctx": False}
    inspect.signature(AgentSession.say).bind(None, text, **kwargs)  # the real say takes these
    assert ended == ["test"]


async def test_say_and_end_ends_even_when_say_raises() -> None:
    session = FakeSpeakingSession(fail=RuntimeError("AgentSession isn't running"))  # agent_session.py:1553
    ended: list[str] = []
    await say_and_end(session, "Bye.", ended.append, "test")
    assert ended == ["test"]


async def test_say_and_end_ends_when_the_playout_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "SAY_TIMEOUT_S", 0.05)
    session = FakeSpeakingSession(say_s=10)
    ended: list[str] = []
    await asyncio.wait_for(say_and_end(session, "Bye.", ended.append, "test"), 1)
    assert ended == ["test"]


async def test_say_and_end_interrupts_the_reply_that_is_playing_before_it_speaks() -> None:
    # Review A-I1: say() queues behind the current reply (agent_activity.py _schedule_speech), so the line must cut it.
    session = FakeSpeakingSession(current_reply_s=10)
    ended: list[str] = []
    await asyncio.wait_for(say_and_end(session, "Bye.", ended.append, "test"), 1)
    assert session.interrupts == [True]  # force: a non-interruptible line already queued (the cap line) yields too
    inspect.signature(AgentSession.interrupt).bind(None, force=True)  # the real interrupt takes it
    ((handle,),) = [session.handles]
    assert handle.played_out and ended == ["test"]


async def test_say_and_end_still_speaks_when_interrupt_raises() -> None:
    class Uninterruptible(FakeSpeakingSession):
        def interrupt(self, *, force: bool = False) -> asyncio.Future[None]:
            raise RuntimeError("the speech currently playing disallows interruptions")

    session = Uninterruptible()
    ended: list[str] = []
    await say_and_end(session, "Bye.", ended.append, "test")
    assert [text for text, _ in session.said] == ["Bye."] and ended == ["test"]


async def test_the_time_up_line_cuts_a_long_reply() -> None:
    session = FakeSpeakingSession(current_reply_s=10)
    ended: list[str] = []
    await asyncio.wait_for(start_session_timer(session, 0.01, ended.append), 1)
    assert session.interrupts == [True] and session.handles[0].played_out and ended == ["time limit"]


def test_utc_day() -> None:
    assert utc_day(1_792_454_400_000) == "2026-10-20"  # 2026-10-20T00:00:00Z
    assert utc_day(1_792_454_400_000 - 1) == "2026-10-19"


async def test_sixth_session_of_the_day_is_capped_and_the_fifth_is_not(store: Store, visitor_id: str) -> None:
    results = [await over_daily_cap(store, visitor_id, 5, day=DAY) for _ in range(6)]
    assert results == [False] * 5 + [True]
    assert not await over_daily_cap(store, visitor_id, 5, day="2026-10-21")  # a new UTC day starts over


async def test_daily_count_survives_forget_me(store: Store, visitor_id: str) -> None:
    store.get_or_create_thread(visitor_id)
    for _ in range(5):
        assert not await over_daily_cap(store, visitor_id, 5, day=DAY)
    assert store.forget_me(visitor_id)
    assert store.thread_for(visitor_id) is None
    assert await over_daily_cap(store, visitor_id, 5, day=DAY)  # erasing doesn't reset the cap (B7)


# --- through start_session (a real AgentSession over FakeLLMs, a FakeRoom as ctx.room) ----------------------------


async def until(cond: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


@pytest.fixture
def said(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Every AgentSession.say, recorded before the real one runs."""
    lines: list[tuple[str, dict[str, Any]]] = []
    real = AgentSession.say

    def spy(self: AgentSession, text: Any, **kwargs: Any) -> Any:
        lines.append((text, kwargs))
        return real(self, text, **kwargs)

    monkeypatch.setattr(AgentSession, "say", spy)
    return lines


def ending(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """ctx.shutdown's reasons (fake_job_context's shutdown does nothing)."""
    reasons: list[str] = []
    monkeypatch.setattr(ctx, "shutdown", lambda reason="user requested": reasons.append(reason))
    return reasons


def count_today(db: Store, n: int) -> None:
    for _ in range(n):
        db.count_session(VISITOR, utc_day(now_ms()))


async def test_capped_session_does_not_preload(
    fakes: list[FakeLLM], db: Store, said: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    count_today(db, 5)  # five sessions today: this is the sixth
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        ended = ending(ctx, monkeypatch)
        started = await start(ctx, db)
        await until(lambda: ended != [], 10)
        assert ended == ["daily cap"]
        assert [text for text, _ in said] == [DAILY_CAP_LINE]
        assert started.greeting is None and started.preloaded is None and started.writer is None
        assert db.thread_for(VISITOR) is None  # the preload would have created the thread
        assert fakes[0].calls == []  # no greeting
        assert set(room.local_participant.rpc_handlers) == {FORGET_ME_METHOD, GET_MEMORY_METHOD}
        await shutdown(ctx, started, "daily cap")


async def test_fifth_session_of_the_day_runs(fakes: list[FakeLLM], db: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    count_today(db, 4)
    with fake_job_context(job_metadata=METADATA, room=FakeRoom()) as ctx:
        ended = ending(ctx, monkeypatch)
        started = await start(ctx, db)
        assert started.greeting is not None and started.writer is not None and ended == []
        assert db.thread_for(VISITOR) is not None
        await shutdown(ctx, started)


async def test_daily_cap_holds_when_the_preload_misses_its_deadline(
    fakes: list[FakeLLM], db: Store, said: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    count_today(db, 5)
    real_count = db.count_session

    def slow_count(visitor_id: str, day: str) -> int:
        time.sleep(0.5)  # another job holds the write lock
        return real_count(visitor_id, day)

    monkeypatch.setattr(db, "count_session", slow_count)
    monkeypatch.setattr(concierge_session, "PRELOAD_TIMEOUT_S", 0.1)
    with fake_job_context(job_metadata=METADATA, room=FakeRoom()) as ctx:
        ended = ending(ctx, monkeypatch)
        started = await start(ctx, db)
        await until(lambda: ended != [], 10)
        assert ended == ["daily cap"] and [text for text, _ in said] == [DAILY_CAP_LINE]
        assert started.greeting is None and db.thread_for(VISITOR) is None
        await shutdown(ctx, started)


async def test_a_count_that_misses_its_deadline_ends_the_session(
    fakes: list[FakeLLM], db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stuck(visitor_id: str, day: str) -> int:
        time.sleep(0.5)
        return 1

    monkeypatch.setattr(db, "count_session", stuck)
    monkeypatch.setattr(concierge_session, "PRELOAD_TIMEOUT_S", 0.05)
    monkeypatch.setattr(limits, "COUNT_TIMEOUT_S", 0.1)
    with fake_job_context(job_metadata=METADATA, room=FakeRoom()) as ctx:
        ended = ending(ctx, monkeypatch)
        started = await start(ctx, db)
        await until(lambda: ended != [], 10)
        assert ended == ["daily cap"]  # fails closed on time
        await shutdown(ctx, started)  # waits for the count's thread
    with Store(db.path) as reopened:  # the count came back under the cap after the session was ended (review I1)
        assert reopened.thread_for(VISITOR) is None  # but no preload ran: no thread, no visit counted


async def test_a_slow_count_does_not_hold_up_session_start(
    fakes: list[FakeLLM], db: Store, said: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review I3: RoomIO's lk.chat and pre-connect audio handlers register at session.start, so a count that's
    still running when the preload's deadline passes is awaited after session.start, not before it."""
    order: list[str] = []
    count_today(db, 5)
    real_count = db.count_session
    started_session = threading.Event()

    def slow_count(visitor_id: str, day: str) -> int:
        started_session.wait(2.0)  # comes back once the session has started (or after 2 s if it never does)
        order.append("count")
        return real_count(visitor_id, day)

    real_start = AgentSession.start

    async def spy_start(self: AgentSession, *args: Any, **kwargs: Any) -> Any:
        order.append("session.start")
        started_session.set()
        return await real_start(self, *args, **kwargs)

    monkeypatch.setattr(db, "count_session", slow_count)
    monkeypatch.setattr(AgentSession, "start", spy_start)
    monkeypatch.setattr(concierge_session, "PRELOAD_TIMEOUT_S", 0.05)
    with fake_job_context(job_metadata=METADATA, room=FakeRoom()) as ctx:
        ended = ending(ctx, monkeypatch)
        started = await start(ctx, db)
        await until(lambda: ended != [], 10)
        assert order == ["session.start", "count"]
        assert ended == ["daily cap"] and [text for text, _ in said] == [DAILY_CAP_LINE]
        assert started.greeting is None and fakes[0].calls == []  # capped: no greeting
        await shutdown(ctx, started)


async def test_session_ends_after_session_max_s(
    fakes: list[FakeLLM], db: Store, said: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONCIERGE_SESSION_MAX_S", "1")
    with fake_job_context(job_metadata=METADATA, room=FakeRoom()) as ctx:
        ended = ending(ctx, monkeypatch)
        started = await start(ctx, db)
        assert started.timer is not None and ended == []
        await until(lambda: ended != [], 5)
        assert ended == ["time limit"] and [text for text, _ in said] == [TIME_UP_LINE]
        await shutdown(ctx, started, "time limit")


async def test_session_timer_is_cancelled_at_shutdown(fakes: list[FakeLLM], db: Store) -> None:
    with fake_job_context(job_metadata=METADATA, room=FakeRoom()) as ctx:
        started = await start(ctx, db)
        assert started.timer is not None and not started.timer.done()
        await shutdown(ctx, started)
        await asyncio.sleep(0)
        assert started.timer.cancelled()

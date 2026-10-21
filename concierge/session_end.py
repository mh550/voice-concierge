"""The ends of a session (plan C5 "The shutdown sequence"; plan 2026-10-21-V1 "one end_session"): one journal row off
the loop, the visit summary after the final extraction, and the one closing run every end goes through.

Every end (the visitor left, the 10-minute cap, the daily cap, a server-side close) runs the same closing work once:
the final extraction, the visit summary, `session_ended`, then the last `concierge.memory`. A departure or a cap runs it
while the room is still connected and then calls `ctx.shutdown(reason)`: the job disconnects the room before it runs
the shutdown callbacks (agents/ipc/job_proc_lazy_main.py:477-497), so a send from `on_shutdown` never reaches the page.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from livekit.agents import llm
from pydantic import ValidationError

from concierge.forget_match import value_requests
from concierge.memory_writer import MemoryWriter
from concierge.models import JournalType
from concierge.store import StaleSummary, Store, StoreError, ThreadMissing
from concierge.summary import failed, summarize

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from concierge.compactor import Compactor
    from concierge.departure import DepartureWatcher
    from concierge.metrics import TurnMetricsCollector
    from concierge.preload import Preloaded
    from concierge.publish import MemoryPublisher

logger = logging.getLogger("concierge.session")

_STORE_ERRORS = (StoreError, sqlite3.Error, ValidationError)
SUMMARY_ATTEMPTS = 2  # one more when another session stored a summary during the call
# The closing work's own deadline (plan C5 "Timing"): the flush (15 s), the summary (5 s) and a busy wait (5 s) fit, and
# it leaves the worker's shutdown_process_timeout=30 room for the session close before the callbacks. A second
# summary attempt (another session stored one during the first) only runs in what is left of it.
SHUTDOWN_WORK_S = 25.0


async def journal_row(
    store: Store, thread_id: str, session_id: str, kind: JournalType, payload: dict[str, Any],
    writer: MemoryWriter | None = None,
) -> None:
    """One journal row, off the loop (on the writer's store thread when given, in order with its writes). A failure
    is logged by type and never raised: the session goes on."""
    try:
        if writer is not None:
            await writer.call(store.journal, thread_id, session_id, kind, payload)
        else:
            await asyncio.to_thread(store.journal, thread_id, session_id, kind, payload)
    except ThreadMissing:
        logger.info("not journaling %s: the visitor's memory was erased", kind)
    except _STORE_ERRORS as exc:
        logger.warning("could not journal %s (%s)", kind, type(exc).__name__)


def forgotten_values(writer: MemoryWriter) -> list[str]:
    """The value_keys the visit summary may not name: what the forget tool deleted, what a forget request kept the
    extraction from storing, and the values the requests name themselves (C5 review A-I2)."""
    return ([key for _, key, _ in writer.forgotten] + writer.withheld
            + value_requests(about for about, _ in writer.forget_requests))


async def write_summary(writer: MemoryWriter, summarizer: Callable[[], llm.LLM]) -> None:
    """The visit summary after the final extraction. It starts from the summary stored now, not the preloaded one
    (another session for this visitor may have stored one since), and is swapped in compare-and-set: if another
    session stores one during the call, it summarizes once more from that one, then gives up (`error` StaleSummary;
    review A-I3). A failure (building the LLM included) journals `error` and keeps the previous summary, or clears
    it when it names a forgotten value; a new one is journaled as counts, never text. All on the writer's thread."""
    store, thread_id, session_id = writer.store, writer.thread_id, writer.session_id
    about, values = [about for about, _ in writer.forget_requests], forgotten_values(writer)
    llm_: llm.LLM | None = None
    try:
        llm_ = summarizer()
    except Exception as exc:  # e.g. the provider can't be built: no key
        build_error = type(exc).__name__
    for _ in range(SUMMARY_ATTEMPTS):
        try:
            previous = (await writer.call(store.state, thread_id)).last_visit_summary
        except ThreadMissing:
            return
        except _STORE_ERRORS as exc:
            logger.warning("could not read the visit summary (%s)", type(exc).__name__)
            return
        if llm_ is None:
            outcome = failed(previous, values, build_error)
        else:
            outcome = await summarize(llm_, previous, writer.history, forgotten_about=about, forgotten_values=values)
        if writer.erased:  # forget_me landed during the call
            return
        if outcome.error is not None:
            logger.warning("the visit summary failed (%s)", outcome.error)
            await journal_row(store, thread_id, session_id, "error", {"stage": "summary", "type": outcome.error},
                              writer)
        if not outcome.changed:
            return
        try:
            await writer.call(store.swap_summary, thread_id, previous, outcome.text)
        except StaleSummary:
            continue
        except ThreadMissing:
            logger.info("not storing the visit summary: the visitor's memory was erased")
            return
        except _STORE_ERRORS as exc:
            logger.warning("could not store the visit summary (%s)", type(exc).__name__)
            return
        written = {"chars": len(outcome.text or ""), "sentences": outcome.sentences, "ms": outcome.ms}
        await journal_row(store, thread_id, session_id, "summary_written", written, writer)
        return
    logger.warning("the visit summary was not stored: another session kept storing its own")
    await journal_row(store, thread_id, session_id, "error", {"stage": "summary", "type": "StaleSummary"}, writer)


@dataclass
class Closing:
    """What the closing work needs; start_session fills it in as the objects exist."""

    end: Callable[[str], None]  # ctx.shutdown
    store: Store | None
    session_id: str
    visitor_id: str
    began: float  # time.monotonic() at start
    tasks: set[asyncio.Task[Any]]  # the session's tracked tasks: the work waits for them first
    make_summarizer: Callable[[], llm.LLM]  # built only when a summary runs; closed at shutdown
    session: AgentSession | None = None
    preloaded: Preloaded | None = None
    writer: MemoryWriter | None = None
    compactor: Compactor | None = None
    publisher: MemoryPublisher | None = None
    collector: TurnMetricsCollector | None = None
    timer: asyncio.Task[None] | None = None  # the session_max_s limit
    watcher: DepartureWatcher | None = None
    summarizers: list[llm.LLM] = field(default_factory=list)
    ending: asyncio.Task[None] | None = None  # the one run of the closing work; never one of `tasks`
    stopped: bool = False  # an end began ("Forget me" included): start_session starts nothing more

    def build_summarizer(self) -> llm.LLM:
        self.summarizers.append(self.make_summarizer())
        return self.summarizers[-1]

    def stop(self) -> None:
        """No other end starts: the cap timer and the departure watch are cancelled (idempotent; "Forget me" too)."""
        self.stopped = True
        if self.timer is not None:  # a sleeping 10-minute task would hold the shutdown up
            self.timer.cancel()
        if self.watcher is not None:
            self.watcher.cancel()


def _begin(closing: Closing, reason: str, leave: bool, left_grace_s: float | None = None) -> asyncio.Task[None]:
    if closing.ending is None:  # outside `closing.tasks`: the work's gather never waits for itself
        closing.stop()  # now, not when the task first runs: start_session sees it at once
        closing.ending = asyncio.create_task(_close(closing, reason, leave, left_grace_s), name="end_session")
    return closing.ending


def begin_end(closing: Closing, reason: str) -> None:
    """`end_session(closing, reason)` started, not awaited: the `end` that `say_and_end` calls (limits.End)."""
    _begin(closing, reason, leave=True)


async def end_session(
    closing: Closing, reason: str, *, leave: bool = True, left_grace_s: float | None = None
) -> None:
    """Run the closing work, then (with `leave`) `ctx.shutdown(reason)`. Once per session: a later call (the cap and
    the departure racing, or on_shutdown after either) waits for the first one's run and adds nothing. With
    `left_grace_s` (the DepartureWatcher's on_left), `visitor_left` (no values, D8) is journaled first in the run."""
    await asyncio.shield(_begin(closing, reason, leave, left_grace_s))


async def _close(closing: Closing, reason: str, leave: bool, left_grace_s: float | None) -> None:
    try:
        async with asyncio.timeout(SHUTDOWN_WORK_S):
            if left_grace_s is not None:  # in the one run: no other end can follow the row with its own reason
                await _journal(closing, "visitor_left", {"grace_s": left_grace_s})
            if leave and closing.session is not None:
                # First: the agent stops listening and replying, so every turn is in the writer's history before the
                # final extraction (V1-02 review I2). The room and the job stay up (agent_session.py:1309, room_io:552).
                await closing.session.aclose()
            await _work(closing, reason)
            # A "Forget me" begun during the work sends its empty memory before ctx.shutdown closes the room (V1-03).
            await asyncio.gather(*closing.tasks, return_exceptions=True)
    except TimeoutError:
        logger.warning("the shutdown work missed its %.0f s deadline; the rest was skipped", SHUTDOWN_WORK_S)
    except Exception as exc:  # by type only; the session still leaves
        logger.warning("the closing work failed (%s)", type(exc).__name__)
    finally:
        if leave:
            closing.end(reason)


async def _work(closing: Closing, reason: str) -> None:
    writer, preloaded, publisher = closing.writer, closing.preloaded, closing.publisher
    await asyncio.gather(*closing.tasks, return_exceptions=True)  # errors are logged by track's callback
    if closing.compactor is not None:  # first: no compaction overlaps the final extraction or the summary
        await closing.compactor.aclose()
    if writer is not None:
        await writer.flush()  # the final extraction; nothing when erased
        # Checked after the flush too: forget_me can land during it. No visitor turn: nothing new.
        if not writer.erased and preloaded is not None and any(t.role == "user" for t in writer.history):
            await write_summary(writer, closing.build_summarizer)
    if not (writer is not None and writer.erased):
        ended = {"reason": reason, "duration_s": round(time.monotonic() - closing.began, 1)}
        await _journal(closing, "session_ended", ended)
    if publisher is None:
        return
    if publisher.closed:  # on_shutdown (the room is gone), or forget_me already sent the empty memory
        logger.info("no closing concierge.memory: the publisher is closed")
        return
    # One more concierge.memory, built and sent in turn like every other (publisher.final would close it): a
    # forget_me that lands while it is built still sends the empty memory after it (review of V1-02, I1).
    publisher.schedule()
    await publisher.idle()


async def _journal(closing: Closing, kind: JournalType, payload: dict[str, Any]) -> None:
    """A closing row: only with a thread; on the writer's thread, after a cancelled run's last store call (M7)."""
    if closing.store is not None and closing.preloaded is not None:
        await journal_row(closing.store, closing.preloaded.thread_id, closing.session_id, kind, payload, closing.writer)


async def shut_down(closing: Closing, reason: str) -> None:
    """The job's shutdown callback, one ordered run (the job runs its callbacks concurrently). The room is disconnected
    by now, so nothing more is sent; then the closing work (done already after a departure or a cap: this only waits),
    then every part closes, the store last."""
    closing.stop()
    if closing.collector is not None:
        closing.collector.stop_publishing()
    if closing.publisher is not None:
        await closing.publisher.aclose()
    try:
        await end_session(closing, reason, leave=False)
    finally:
        for part in (closing.collector, closing.compactor, closing.writer, *closing.summarizers):
            if part is None:  # the collector waits ≤ 5 s for its writes
                continue
            try:
                await part.aclose()  # the writer waits for its store thread: before store.close
            except Exception as exc:  # e.g. an LLM's close: the store still closes
                logger.warning("closing %s failed (%s)", type(part).__name__, type(exc).__name__)
        if closing.store is not None:
            await asyncio.to_thread(closing.store.close)

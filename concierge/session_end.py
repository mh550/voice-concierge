"""The ends of a session (plan C5 "The shutdown sequence"; plan 2026-10-21-V1 "one end_session"): the one closing run
every end goes through. The visit summary and the visit's episode row are in `concierge/summary_step.py`.

Every end (the visitor left, the 10-minute cap, the daily cap, a server-side close) runs the same closing work once:
the final extraction, the visit summary, the visit's episode closed (`end_visit`), `session_ended`, then the last
`concierge.memory`. A departure or a cap runs it
while the room is still connected and then calls `ctx.shutdown(reason)`: the job disconnects the room before it runs
the shutdown callbacks (agents/ipc/job_proc_lazy_main.py:477-497), so a send from `on_shutdown` never reaches the page.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from livekit.agents import llm

from concierge.memory_writer import MemoryWriter
from concierge.models import JournalType
from concierge.store import Store, now_ms
from concierge.summary_step import end_visit, journal_row, write_summary

if TYPE_CHECKING:
    from livekit.agents import AgentSession

    from concierge.compactor import Compactor
    from concierge.departure import DepartureWatcher
    from concierge.metrics import TurnMetricsCollector
    from concierge.preload import Preloaded
    from concierge.publish import MemoryPublisher

logger = logging.getLogger("concierge.session")

# The closing work's own deadline (plan C5 "Timing"): the flush (15 s), the summary (5 s) and a busy wait (5 s) fit, and
# it leaves the worker's shutdown_process_timeout=30 room for the session close before the callbacks. A second
# summary attempt (another session stored one during the first) only runs in what is left of it.
SHUTDOWN_WORK_S = 25.0


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
        # Checked after the flush too: forget_me can land during it. No visitor turn: nothing new, a null summary.
        if not writer.erased and preloaded is not None:
            summary = None
            if any(t.role == "user" for t in writer.history):
                summary = await write_summary(writer, closing.build_summarizer)
            if not writer.erased:  # the visit's episode, closed before the final concierge.memory reads it
                await end_visit(writer, preloaded.visits, now_ms(), summary)
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

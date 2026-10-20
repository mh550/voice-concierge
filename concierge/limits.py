"""The abuse limits (spec B7; plan C6 "concierge/limits.py"): a session ends after `session_max_s`, and a visitor's
session over the day's cap is told so in one line and ended.

Every end says one line first, then calls `end(reason)`: `ctx.shutdown` in a session, because closing the
`AgentSession` alone leaves the agent in the room (RoomIO deletes the room only with `delete_room_on_close`,
voice/room_io/room_io.py:548-559). The lines are not added to the chat context, so the writer never journals them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from concierge.store import Store, now_ms

logger = logging.getLogger("concierge.limits")

TIME_UP_LINE = "We've reached the ten-minute limit for a call, so I'll say goodbye here. Thanks for stopping by."
DAILY_CAP_LINE = "You've reached today's limit of calls with me. Please come back tomorrow."
GOODBYE_LINE = "Done: I've forgotten everything about you. Goodbye."
SAY_TIMEOUT_S = 8.0  # a line that can't play out (the TTS is down) still ends the session
# The daily count isn't under the preload's 1 s deadline (plan C6 "The daily cap and the preload"): a session whose
# preload missed it waits this much longer for the count after session.start. A count blocked on another writer's
# lock raises at the store's 5 s busy timeout first and fails open (like a failed store); this catches a count that
# is slow for any other reason.
COUNT_TIMEOUT_S = 5.0

End = Callable[[str], None]  # ctx.shutdown(reason)


class Speaker(Protocol):
    """What the limits need of an AgentSession: `say` (agent_session.py:1544), `interrupt` (:1648) and `aclose`
    (:1445)."""

    def say(self, text: str, *, allow_interruptions: bool = ..., add_to_chat_ctx: bool = ...) -> Any: ...  # noqa: ANN401

    def interrupt(self, *, force: bool = ...) -> Any: ...  # noqa: ANN401

    async def aclose(self) -> None: ...


async def say_and_end(session: Speaker, line: str, end: End | None, reason: str) -> None:
    """Cut the reply that is playing and any queued behind it, then say `line` (no interruptions, not in the chat
    context), wait for its playout up to SAY_TIMEOUT_S, then `end(reason)`; with no `end`, close the session. Without
    the interrupt, `say` would queue behind the current reply (agent_activity.py `_schedule_speech`): a goodbye after
    "Forget me" would wait while erased memory is still spoken. `force` also cuts a non-interruptible line already
    playing (the cap line). A session that can't speak (closing, `say` raises) still ends."""
    try:
        session.interrupt(force=True)
    except RuntimeError as exc:  # the session isn't running; `say` below raises too and the session ends
        logger.info("nothing interrupted before the %s line (%s)", reason, type(exc).__name__)
    try:
        handle = session.say(line, allow_interruptions=False, add_to_chat_ctx=False)
        async with asyncio.timeout(SAY_TIMEOUT_S):
            await handle.wait_for_playout()
    except Exception as exc:
        logger.warning("the %s line wasn't played out (%s)", reason, type(exc).__name__)
    if end is None:
        await session.aclose()
    else:
        end(reason)


def _log_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.warning("the session timer failed (%s)", type(exc).__name__)


def start_session_timer(session: Speaker, max_s: float, end: End | None = None) -> asyncio.Task[None]:
    """After `max_s` (Settings.session_max_s, 600), say TIME_UP_LINE and end. Not one of the session's tracked
    tasks (on_shutdown waits for those): the shutdown cancels it first."""

    async def run() -> None:
        await asyncio.sleep(max_s)
        await say_and_end(session, TIME_UP_LINE, end, "time limit")

    task = asyncio.create_task(run())
    task.add_done_callback(_log_failure)
    return task


def utc_day(ms: int) -> str:
    """The UTC date of epoch milliseconds, YYYY-MM-DD (the daily count's day)."""
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


async def over_daily_cap(store: Store, visitor_id: str, cap: int, day: str | None = None) -> bool:
    """Count this session (in a thread: the store can block 5 s) and return whether the day's count is over `cap`
    (Settings.sessions_per_day, 5: the 6th session of a UTC day is over). The count survives "Forget me"."""
    count = await asyncio.to_thread(store.count_session, visitor_id, day or utc_day(now_ms()))
    return count > cap


async def preload_unless_capped[T](counting: asyncio.Task[bool], load: Callable[[], Awaitable[T]]) -> T | None:
    """`load()` (the preload) once this session is counted; None over the cap ("closes without preloading
    memory"). A failed count fails it too: a session without memory, as a failed store gives. The count is
    shielded: the session cancels this task when a late count is over the cap or timed out, never the count."""
    if await asyncio.shield(counting):
        return None
    return await load()


async def was_capped(counting: asyncio.Task[bool] | None) -> bool:
    """Whether the session's count (a tracked task, its failure logged by `track`) is over the cap. Fails open on a
    store error (the busy timeout included), closed on time: still running after COUNT_TIMEOUT_S counts as capped.
    No count (no store): False."""
    if counting is None:
        return False
    try:
        async with asyncio.timeout(COUNT_TIMEOUT_S):
            return await asyncio.shield(counting)
    except TimeoutError:
        logger.warning("ending the session: the daily count missed its deadline (TimeoutError)")
        return True
    except Exception:
        return False


async def enforce_daily_cap(
    store: Store, visitor_id: str, session: Speaker, cap: int, end: End | None = None, day: str | None = None
) -> bool:
    """`over_daily_cap`, then, when over, DAILY_CAP_LINE and the end. True when capped. The session counts and
    checks before its preload (session.py), so a capped session never loads the visitor's memory."""
    if not await over_daily_cap(store, visitor_id, cap, day):
        return False
    await say_and_end(session, DAILY_CAP_LINE, end, "daily cap")
    return True

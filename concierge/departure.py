"""The session ends when the visitor leaves (spec 2026-10-21 §3; plan 2026-10-21-V1 "The watcher").

`rtc.Room` emits `participant_disconnected` and `participant_connected` with the `RemoteParticipant`
(rtc/room.py:768-775); its `.identity` (rtc/participant.py:164) is the visitor's `visitor-<visitor_id>`. A visitor
who leaves starts a grace (D16: a reload or a client-side route change that remounts the page reconnects with the same
identity inside it); the same identity joining again cancels it; when it runs out, `on_left` is awaited once. The
handlers are plain defs (`EventEmitter.on` refuses a coroutine function) that only start or cancel a task. A visitor
not in `room.remote_participants` (rtc/room.py:249) when the watch starts (gone during `ctx.connect()` or the preload,
or never joined) gets the longer join grace instead (D16, V1-03 review I3): a page may ask for the mic before it joins.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from livekit import rtc

logger = logging.getLogger("concierge.departure")

DEPARTURE_GRACE_S = 20.0  # D16 *default*
JOIN_GRACE_S = 60.0  # D16 *default*: a visitor absent when the watch starts


class DepartureWatcher:
    """One session's watch on its visitor's participant. `cancel()` (the session is ending some other way) stops it
    for good: no grace runs after it and later events are ignored. Once the grace has run out, `on_left` runs to the
    end: `cancel()` from inside it (end_session cancels the watcher first) doesn't cut it short."""

    def __init__(
        self, room: rtc.Room, visitor_identity: str, on_left: Callable[[], Awaitable[None]],
        grace_s: float = DEPARTURE_GRACE_S, join_grace_s: float = JOIN_GRACE_S,
    ) -> None:
        self._room = room
        self._identity = visitor_identity
        self._on_left = on_left
        self._grace_s = grace_s
        self._join_grace_s = join_grace_s
        self._grace: asyncio.Task[None] | None = None  # the grace while it runs
        self._leaving: asyncio.Task[None] | None = None  # on_left, once the grace ran out
        self._stopped = False
        self.waited_s: float | None = None  # the grace that ran out (the join grace or the departure grace)
        self._handlers: dict[str, Callable[[Any], None]] = {
            "participant_disconnected": self._on_disconnected,
            "participant_connected": self._on_connected,
        }

    @property
    def pending(self) -> bool:
        """True while the grace runs."""
        return self._grace is not None

    def start(self) -> None:
        for event, handler in self._handlers.items():
            self._room.on(event, handler)
        if self._identity not in self._room.remote_participants:  # left before the watch, or not joined yet
            self._grace = asyncio.create_task(self._wait(self._join_grace_s), name="join_grace")

    def cancel(self) -> None:
        """Idempotent: the grace is cancelled and the handlers come off the room."""
        if self._stopped:
            return
        self._stopped = True
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None
        for event, handler in self._handlers.items():
            self._room.off(event, handler)  # a no-op for a handler never registered

    def _on_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        if self._stopped or self._leaving is not None or participant.identity != self._identity:
            return
        if self._grace is None:  # a second disconnect doesn't restart the grace
            self._grace = asyncio.create_task(self._wait(self._grace_s), name="departure_grace")

    def _on_connected(self, participant: rtc.RemoteParticipant) -> None:
        if self._grace is not None and participant.identity == self._identity:
            logger.info("the visitor reconnected inside the departure grace")
            self._grace.cancel()
            self._grace = None

    async def _wait(self, grace_s: float) -> None:
        await asyncio.sleep(grace_s)
        self._grace = None  # from here a cancel() no longer reaches on_left
        self.waited_s = grace_s
        self._leaving = asyncio.create_task(self._leave(), name="departure_on_left")

    async def _leave(self) -> None:
        try:
            await self._on_left()
        except Exception as exc:  # by type only: an error message can quote visitor data
            logger.warning("ending the session after the visitor left failed (%s)", type(exc).__name__)

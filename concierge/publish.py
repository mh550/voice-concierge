"""Sending the §6 topics to the page (plan C6 Part 2).

`publish` sends one JSON body with `room.local_participant.send_text(body, topic=...)` (rtc 1.1.20,
participant.py:864). `MemoryPublisher` sends every `concierge.memory` of a session: at start, after every merge and
the empty one after "Forget me". Its sends are serialized and built just before they go out, so they reach the page
in order and each carries the memory as it is then. `final` closes it first, so a send built before the erase is
dropped and the empty body is the last one the page sees. Nothing here runs on the turn path: `schedule` only
starts a task.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from livekit import rtc
from pydantic import BaseModel

from concierge.contract import MAX_BODY_BYTES, MEMORY_TOPIC, MemoryPayload
from concierge.tasks import track

logger = logging.getLogger("concierge.publish")


class PayloadTooLarge(ValueError):
    """A body over §6's 15 KiB. Names the topic and the size, never the body (it can hold visitor values)."""

    def __init__(self, topic: str, size: int) -> None:
        super().__init__(f"{topic} body is {size} bytes; the cap is {MAX_BODY_BYTES}")
        self.topic = topic
        self.size = size


async def publish(room: rtc.Room, topic: str, payload: BaseModel) -> None:
    """Send `payload` as JSON on `topic` to everyone in the room (the visitor's page). Raises PayloadTooLarge, and
    whatever `send_text` raises (`rtc.StreamError` when the send fails)."""
    body = payload.model_dump_json()
    size = len(body.encode())
    if size > MAX_BODY_BYTES:
        raise PayloadTooLarge(topic, size)
    await room.local_participant.send_text(body, topic=topic)


class MemoryPublisher:
    """Every `concierge.memory` send of one session. `build` makes the payload when its turn comes (the session
    passes one that reads the store on the writer's thread). A failed build or send is logged by type and dropped:
    the page can ask again with `concierge.get_memory`."""

    def __init__(self, room: rtc.Room, build: Callable[[], Awaitable[MemoryPayload]]) -> None:
        self.closed = False  # no new sends: "Forget me" sent the last one, or the session is ending
        self._shut = False  # the session is ending (aclose): not even final's send goes out
        self._room = room
        self._build = build
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()

    def schedule(self) -> None:
        """Send the current memory soon (sync: the writer's `on_merged` calls it). Nothing once closed."""
        if not self.closed:
            track(self._tasks, self._send_current(), log=logger)

    async def final(self, payload: MemoryPayload) -> None:
        """Send `payload` as the last memory and close ("Forget me"). Closed before the lock: a send already
        waiting or building is dropped when it re-checks."""
        if self.closed:
            return
        self.closed = True
        async with self._lock:
            if not self._shut:  # aclose ran while this waited: the room is gone
                await self._send(payload)

    async def idle(self) -> None:
        """Wait for the sends scheduled so far."""
        while self._tasks:
            await asyncio.wait(set(self._tasks))

    async def aclose(self) -> None:
        """Closed, pending sends cancelled, a waiting `final` dropped. First in the shutdown: the room is disconnected
        by then, and a send to it could wait for a callback that never comes."""
        self.closed = self._shut = True
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.wait(set(self._tasks))

    async def _send_current(self) -> None:
        async with self._lock:
            if self.closed:
                return
            try:
                payload = await self._build()
            except Exception as exc:
                logger.warning("the concierge.memory payload wasn't built (%s)", type(exc).__name__)
                return
            if not self.closed:  # "Forget me" landed during the build
                await self._send(payload)

    async def _send(self, payload: MemoryPayload) -> None:
        try:
            await publish(self._room, MEMORY_TOPIC, payload)
        except Exception as exc:  # StreamError, PayloadTooLarge, a room that never connected
            logger.warning("a concierge.memory send was dropped (%s)", type(exc).__name__)

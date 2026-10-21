"""The page's RPC methods (spec §6; plan C6 Part 4): `concierge.forget_me` and `concierge.get_memory`.

Registered with `room.local_participant.register_rpc_method(method_name, handler)` (rtc 1.1.20,
participant.py:518-522); a handler gets one `rtc.RpcInvocationData` and returns the response string, under the
caller's 10 s `response_timeout`. So `forget_me` answers `{"ok": true}` at once and does the erase in a task: cancel
the pending memory work, erase, send the empty `concierge.memory` last, say goodbye, end the session.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from livekit import rtc

from concierge.contract import FORGET_ME_METHOD, GET_MEMORY_METHOD, MemoryPayload, empty_memory_payload
from concierge.erasure_hooks import forget_visitor
from concierge.limits import GOODBYE_LINE, End, Speaker, say_and_end
from concierge.memory_view import current_memory
from concierge.memory_writer import MemoryWriter
from concierge.publish import MemoryPublisher
from concierge.store import Store
from concierge.tasks import track

logger = logging.getLogger("concierge.rpc")

FORGET_ME_OK = json.dumps({"ok": True})  # '{"ok": true}'
NOT_THIS_VISITOR = 4403  # an application code (rtc's built-in ones are 1001-1999, rpc.py:160-168)


@dataclass(frozen=True)
class RpcHandlers:
    visitor_identity: str  # f"visitor-{visitor_id}" (§6): the only caller answered
    erase: Callable[[], Awaitable[None]]  # cancel the pending memory work, then store.forget_me
    memory: Callable[[], Awaitable[MemoryPayload]]  # what concierge.memory carries now
    publish_memory: Callable[[MemoryPayload], Awaitable[None]]  # the last concierge.memory (MemoryPublisher.final)
    end: Callable[[str, str], Awaitable[None]]  # (line, reason): say it, then end the session
    tasks: set[asyncio.Task[Any]]  # the session's tracked tasks: on_shutdown waits for the forget task
    stop_timer: Callable[[], None] = lambda: None  # cancels the session_max_s timer: no time-up line after goodbye


async def erase_visitor(
    store: Store | None, writer: MemoryWriter | None, visitor_id: str, preloading: asyncio.Task[Any] | None = None
) -> None:
    """Spec §4.2 "Erasure wins over pending work": through the writer (cancel first, then erase on its thread), or
    straight through the store when there is no writer, or once more when the writer's attempt failed (closed, or
    the store's busy timeout). Without a writer, a preload still running (it missed its deadline) is waited for
    first: it would re-create the thread after the erase (review I2)."""
    if writer is not None:
        try:
            await forget_visitor(writer, visitor_id)
            return
        except Exception as exc:
            logger.warning("erasing through the store instead of the writer (%s)", type(exc).__name__)
    elif preloading is not None and not preloading.done():
        await asyncio.wait({preloading})  # bounded by the store's busy timeout; its errors are logged by `track`
    if store is not None:
        await asyncio.to_thread(store.forget_me, visitor_id)


def build_handlers(
    *,
    visitor_id: str,
    store: Store | None,
    writer: MemoryWriter | None,
    publisher: MemoryPublisher,
    session: Speaker,
    end: End,
    tasks: set[asyncio.Task[Any]],
    preloading: asyncio.Task[Any] | None = None,
    stop_timer: Callable[[], None] = lambda: None,
    memory: Callable[[], Awaitable[MemoryPayload]] | None = None,
) -> RpcHandlers:
    """`memory`: the session's build callable, the one its MemoryPublisher sends, so `concierge.get_memory` answers
    with what `concierge.memory` last carried (V2-05); None reads the store alone."""
    async def erase() -> None:
        await erase_visitor(store, writer, visitor_id, preloading)

    async def stored() -> MemoryPayload:
        return await current_memory(store, writer, visitor_id)

    async def end_with(line: str, reason: str) -> None:
        await say_and_end(session, line, end, reason)

    return RpcHandlers(
        f"visitor-{visitor_id}", erase, memory or stored, publisher.final, end_with, tasks, stop_timer
    )


async def _forget(handlers: RpcHandlers) -> None:
    """Erase, send the empty memory last, say goodbye and end. A failed erase is logged by type only (the message
    can quote visitor data) and the rest still runs: the page already shows "forgotten"."""
    handlers.stop_timer()
    try:
        await handlers.erase()
    except Exception as exc:
        logger.warning("forget_me: the erase failed (%s)", type(exc).__name__)
    try:
        await handlers.publish_memory(empty_memory_payload())
    except Exception as exc:
        logger.warning("forget_me: the empty concierge.memory wasn't sent (%s)", type(exc).__name__)
    await handlers.end(GOODBYE_LINE, "forget_me")


def register_rpcs(room: rtc.Room, handlers: RpcHandlers) -> None:
    """Register both §6 methods on the agent's participant. Call after `ctx.connect()`: before it,
    `room.local_participant` raises (rtc/room.py:228-235)."""
    forgetting: list[asyncio.Task[None]] = []  # at most one forget task per session

    def check_caller(data: rtc.RpcInvocationData) -> None:
        if data.caller_identity != handlers.visitor_identity:
            raise rtc.RpcError(NOT_THIS_VISITOR, "not this visitor")

    async def on_forget_me(data: rtc.RpcInvocationData) -> str:
        check_caller(data)
        if not forgetting:  # a second press answers the same and starts nothing
            forgetting.append(track(handlers.tasks, _forget(handlers), log=logger))
        return FORGET_ME_OK

    async def on_get_memory(data: rtc.RpcInvocationData) -> str:
        check_caller(data)
        try:
            return (await handlers.memory()).model_dump_json()
        except Exception as exc:  # rtc would log the message, which can quote visitor data (participant.py:629-634)
            logger.warning("get_memory failed (%s)", type(exc).__name__)
            raise rtc.RpcError(rtc.RpcError.ErrorCode.APPLICATION_ERROR, "memory unavailable") from None

    room.local_participant.register_rpc_method(FORGET_ME_METHOD, on_forget_me)
    room.local_participant.register_rpc_method(GET_MEMORY_METHOD, on_get_memory)


def serve_rpcs(room: rtc.Room, **handlers: Any) -> None:  # noqa: ANN401 (build_handlers' keywords)
    """`register_rpcs(room, build_handlers(**handlers))` for a session. A room whose participant can't take them (one
    that never connected) is logged by type, like a failed publish: the session still runs."""
    try:
        register_rpcs(room, build_handlers(**handlers))
    except Exception as exc:
        logger.warning("the RPCs weren't registered (%s)", type(exc).__name__)

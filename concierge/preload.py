"""The preload: one off-loop store call at job start that counts the visit and reads the thread, rendered into the
memory block (spec §4.0 "Just-in-time vs preload"; plan C3 "The preload sequence").

It runs concurrently with `ctx.connect()`, so it adds nothing to the time before the greeting unless the store is
slower than the room connection.
"""

from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, ConfigDict

from concierge.memory_block import render_memory_block
from concierge.models import Fact, Thread, ThreadSnapshot, VisitorState
from concierge.store import Store

logger = logging.getLogger("concierge.session")  # its warnings are the session's


class Preloaded(BaseModel):
    """What the session knows about its visitor at start. `version` is the snapshot's and only informational: the
    `memory_preloaded` journal row has already moved it on, so writers go through `apply_fact_ops`' reload loop.
    A visitor with nothing to recall (`block is None`) is greeted as new."""

    model_config = ConfigDict(frozen=True)

    thread_id: str
    version: int
    visits: int
    state: VisitorState
    facts: list[Fact]
    block: str | None
    ms: float


def _read(store: Store, visitor_id: str, session_id: str) -> tuple[Thread, ThreadSnapshot, float]:
    """The blocking part, in a worker thread: count the visit, read one snapshot, journal how long the two took."""
    start = time.perf_counter()
    thread = store.get_or_create_thread(visitor_id)
    snapshot = store.load(thread.id)
    ms = round((time.perf_counter() - start) * 1000, 1)
    payload = {"ms": ms, "facts": len(snapshot.facts), "summary": bool(snapshot.state.last_visit_summary)}
    store.journal(thread.id, session_id, "memory_preloaded", payload)
    return thread, snapshot, ms


async def preload(store: Store, visitor_id: str, session_id: str = "") -> Preloaded:
    """Count the visit and load the visitor's memory, off the event loop. Raises what the store raises (StoreError,
    sqlite3.Error, ValidationError); the caller decides to run without memory."""
    thread, snapshot, ms = await asyncio.to_thread(_read, store, visitor_id, session_id)
    return Preloaded(
        thread_id=thread.id,
        version=snapshot.version,
        visits=thread.visits,
        state=snapshot.state,
        facts=snapshot.facts,
        block=render_memory_block(snapshot.state, snapshot.facts),
        ms=ms,
    )


async def preload_or_none(task: asyncio.Task[Preloaded] | None, timeout: float) -> Preloaded | None:
    """The visitor's memory, or None (a session without memory). On the deadline the task is left running, not
    cancelled: its store thread can't be stopped, so on_shutdown waits for it before closing the store. Only the
    error type is logged (by `track`): a message can quote visitor data. Any error, not only the store's: a
    session without memory beats no session."""
    if task is None:
        return None
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        logger.warning("no memory this session: the preload missed its deadline (TimeoutError)")
        return None
    if task.exception() is not None:
        logger.warning("no memory this session: the preload failed")
        return None
    return task.result()

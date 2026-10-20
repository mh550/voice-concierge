"""The journaled ends of a session (plan C5 "The shutdown sequence"): one journal row off the loop, and the visit
summary after the final extraction. Split out of session.py, which wires them."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from livekit.agents import llm
from pydantic import ValidationError

from concierge.memory_writer import MemoryWriter
from concierge.models import JournalType
from concierge.store import Store, StoreError, ThreadMissing
from concierge.summary import SummaryOutcome, summarize

logger = logging.getLogger("concierge.session")

_STORE_ERRORS = (StoreError, sqlite3.Error, ValidationError)


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


async def write_summary(writer: MemoryWriter, previous: str | None, summarizer: Callable[[], llm.LLM]) -> None:
    """The visit summary after the final extraction: a failure (building the LLM included) journals `error` and keeps
    the previous summary (or clears it, when it names a value forgotten this visit); a new one is stored (on the
    writer's store thread) and journaled as counts, never text."""
    store, thread_id, session_id = writer.store, writer.thread_id, writer.session_id
    forgotten = {"forgotten_about": [about for about, _ in writer.forget_requests],
                 "forgotten_values": [key for _, key, _ in writer.forgotten]}
    try:
        outcome = await summarize(summarizer(), previous, writer.history, **forgotten)
    except Exception as exc:  # e.g. the provider can't be built: no key
        outcome = SummaryOutcome(text=previous, changed=False, ms=0, error=type(exc).__name__)
    if writer.erased:  # forget_me landed during the call
        return
    if outcome.error is not None:
        logger.warning("the visit summary failed (%s)", outcome.error)
        await journal_row(store, thread_id, session_id, "error", {"stage": "summary", "type": outcome.error}, writer)
    if not outcome.changed:
        return
    try:
        await writer.call(store.set_summary, thread_id, None, outcome.text)
    except ThreadMissing:
        logger.info("not storing the visit summary: the visitor's memory was erased")
        return
    except _STORE_ERRORS as exc:
        logger.warning("could not store the visit summary (%s)", type(exc).__name__)
        return
    written = {"chars": len(outcome.text or ""), "sentences": outcome.sentences, "ms": outcome.ms}
    await journal_row(store, thread_id, session_id, "summary_written", written, writer)

"""The visit's own rows (plan C5 "The shutdown sequence"; plan 2026-10-21-V2 "Store and session"), moved out of
`concierge/session_end.py` by V2-03: a journal row off the loop, the visit summary after the final extraction, and the
visit's `visit_summaries` row, opened at session start (`begin_visit`) and closed with the summary this visit wrote
(`end_visit`). Every store call runs on the writer's thread when there is one; a failure is logged by type, never
raised, and an erased visitor's rows are never re-created (the fence raises ThreadMissing).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from livekit.agents import llm
from pydantic import ValidationError

from concierge.forget_match import value_requests
from concierge.memory_writer import MemoryWriter
from concierge.models import JournalType
from concierge.store import StaleSummary, Store, StoreError, ThreadMissing
from concierge.summary import failed, summarize

logger = logging.getLogger("concierge.session")

_STORE_ERRORS = (StoreError, sqlite3.Error, ValidationError)
SUMMARY_ATTEMPTS = 2  # one more when another session stored a summary during the call


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


async def write_summary(writer: MemoryWriter, summarizer: Callable[[], llm.LLM]) -> str | None:
    """The visit summary after the final extraction. It starts from the summary stored now, not the preloaded one
    (another session for this visitor may have stored one since), and is swapped in compare-and-set: if another
    session stores one during the call, it summarizes once more from that one, then gives up (`error` StaleSummary;
    review A-I3). A failure (building the LLM included) journals `error` and keeps the previous summary, or clears
    it when it names a forgotten value; a new one is journaled as counts, never text. All on the writer's thread.
    Returns the summary this visit wrote (the episode's, D17 (c)), or None: failed, stale, erased or not stored."""
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
            return None
        except _STORE_ERRORS as exc:
            logger.warning("could not read the visit summary (%s)", type(exc).__name__)
            return None
        if llm_ is None:
            outcome = failed(previous, values, build_error)
        else:
            outcome = await summarize(llm_, previous, writer.history, forgotten_about=about, forgotten_values=values)
        if writer.erased:  # forget_me landed during the call
            return None
        written = outcome.text if outcome.error is None else None  # a failure keeps (or clears) the previous one
        if outcome.error is not None:
            logger.warning("the visit summary failed (%s)", outcome.error)
            await journal_row(store, thread_id, session_id, "error", {"stage": "summary", "type": outcome.error},
                              writer)
        if not outcome.changed:
            return written
        try:
            await writer.call(store.swap_summary, thread_id, previous, outcome.text)
        except StaleSummary:
            continue
        except ThreadMissing:
            logger.info("not storing the visit summary: the visitor's memory was erased")
            return None
        except _STORE_ERRORS as exc:
            logger.warning("could not store the visit summary (%s)", type(exc).__name__)
            return None
        counts = {"chars": len(outcome.text or ""), "sentences": outcome.sentences, "ms": outcome.ms}
        await journal_row(store, thread_id, session_id, "summary_written", counts, writer)
        return written
    logger.warning("the visit summary was not stored: another session kept storing its own")
    await journal_row(store, thread_id, session_id, "error", {"stage": "summary", "type": "StaleSummary"}, writer)
    return None


async def begin_visit(writer: MemoryWriter, visit: int, started_at: int) -> None:
    """The visit's open episode (`ended_at` and `summary` null), on the writer's thread. Queued there before the start
    `concierge.memory` is read, so that body already lists the visit (D17 (b))."""
    try:
        await writer.call(writer.store.begin_visit, writer.thread_id, visit, started_at)
    except ThreadMissing:
        logger.info("not opening the visit: the visitor's memory was erased")
    except _STORE_ERRORS as exc:
        logger.warning("could not open the visit (%s)", type(exc).__name__)


async def session_started(writer: MemoryWriter, visit: int, started_at: int, payload: dict[str, Any]) -> None:
    """The background task after the greeting: the visit's open episode, then the `session_started` row, both on the
    writer's thread in that order (moved from `concierge/session.py` by V2-06)."""
    await begin_visit(writer, visit, started_at)
    await journal_row(writer.store, writer.thread_id, writer.session_id, "session_started", payload, writer)


async def end_visit(writer: MemoryWriter, visit: int, ended_at: int, summary: str | None) -> None:
    """Close the visit's episode with what `write_summary` returned (None: failed or skipped, D17 (c))."""
    try:
        await writer.call(writer.store.end_visit, writer.thread_id, visit, ended_at, summary)
    except ThreadMissing:
        logger.info("not ending the visit: the visitor's memory was erased")
    except _STORE_ERRORS as exc:
        logger.warning("could not end the visit (%s)", type(exc).__name__)

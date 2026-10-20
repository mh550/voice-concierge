"""Retention (B6): a thread idle for its TTL (30 days) is purged at worker start and daily, with the daily counts
older than 2 days. Runs in the worker's main process, started on `AgentServer`'s `worker_started` event; the store
work is off the event loop."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

from concierge.store import Store, StoreError

logger = logging.getLogger("concierge.retention")

PURGE_EVERY_S = 24 * 3600.0


def purge_once(path: Path, now: int) -> int:
    """Open the store, run both purges at `now` (ms), close it. Returns the number of threads purged."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with Store(path) as store:
        purged = store.purge_idle(now)
        store.purge_daily_counts(now)
    return purged


async def run_daily_purge(path: Path, *, every_s: float = PURGE_EVERY_S) -> None:
    """Purge now, then every `every_s` until cancelled. A failed purge is logged by type only (a message can quote
    the path) and tried again at the next interval."""
    while True:
        try:
            purged = await asyncio.to_thread(purge_once, path, time.time_ns() // 1_000_000)
            logger.info("retention purge: %d idle thread(s) removed", purged)
        except (StoreError, sqlite3.Error, OSError) as exc:
            logger.warning("retention purge failed (%s); next try in %.0f s", type(exc).__name__, every_s)
        await asyncio.sleep(every_s)

"""Erasure, the TTL purge and the daily session count (spec §4.2, B6, B7, B9; plan C2 "Erasure", "TTL purge").

Both delete every visitor-linked row of a thread (facts, state, journal, messages_for_michael, visit_summaries, then
the thread) in one `BEGIN IMMEDIATE`, then VACUUM and checkpoint the WAL so the values leave the disk too. The anonymous
tables (`anonymous_turn_metrics`, `daily_session_counts`) are never touched by an erasure. Nothing but
`get_or_create_thread` inserts a thread, so once the row is gone every later write raises `ThreadMissing`: erasure
wins.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta

from concierge.store_base import StoreBase, _immediate

log = logging.getLogger(__name__)

DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
DAILY_COUNT_KEEP_DAYS = 2  # B7: today's row is the cap; older rows go after 2 days

# Children first; the ON DELETE CASCADE foreign keys are a second net.
_CHILD_TABLES = ("facts", "state", "journal", "messages_for_michael", "visit_summaries")


def _erase_thread(conn: sqlite3.Connection, thread_id: str) -> None:
    for table in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))


def check_ms(now: int) -> None:
    if now < 10**12:  # 2001-09-09 in ms; anything smaller is seconds
        raise ValueError(f"now must be ms since the epoch, not {now}")


class ErasureStore(StoreBase):
    def _compact(self, conn: sqlite3.Connection, what: str) -> None:
        """VACUUM (rewrites the file without the freed pages), then checkpoint it out of the WAL. Best effort: the
        rows are already gone, so a failure is logged (never with a visitor id or a value) and an unfinished
        checkpoint is owed to the next write (`_settle`)."""
        try:
            conn.execute("VACUUM")
        except sqlite3.Error as exc:
            log.warning("VACUUM after %s failed: %s", what, exc)
        self._settle(conn)

    def forget_me(self, visitor_id: str) -> bool:
        """Erase the visitor's thread and every row linked to it, then VACUUM and checkpoint. False when the
        visitor has no thread. Raises only if the delete itself fails (then nothing was erased). Holds the store's
        lock for the whole sequence. Doesn't journal: the journal is what's being erased."""
        with self._locked() as conn:
            with _immediate(conn):
                row = conn.execute("SELECT id FROM threads WHERE visitor_id = ?", (visitor_id,)).fetchone()
                if row is not None:
                    _erase_thread(conn, row[0])
            if row is None:
                return False
            self._compact(conn, f"forget_me of thread {row[0][:8]}")
        return True

    def purge_idle(self, now: int) -> int:
        """Erase every thread idle longer than its TTL (`last_active_at + idle_ttl_s` < `now`, in ms), all in one
        transaction, then VACUUM and checkpoint once if any went. Returns the number of threads purged. Runs
        daily (B6), so it also checkpoints when nothing went, finishing any checkpoint an erasure owes."""
        check_ms(now)
        with self._locked() as conn:
            with _immediate(conn):
                ids = [
                    tid
                    for (tid,) in conn.execute(
                        "SELECT id FROM threads WHERE last_active_at + idle_ttl_s * 1000 < ?", (now,)
                    ).fetchall()
                ]
                for tid in ids:
                    _erase_thread(conn, tid)
            if ids:
                self._compact(conn, f"purge of {len(ids)} idle threads")
            else:
                self._settle(conn)
        return len(ids)

    # The daily session count (B7): no thread, no visitor id; survives an erasure

    def count_session(self, visitor_id: str, day: str) -> int:
        """Count a session against the daily cap (B7) and return the day's count. The key is
        sha256(visitor_id + day), so the table holds no visitor id; it survives "Forget me" so the cap can't be
        reset by erasing. `day` is the UTC date, YYYY-MM-DD."""
        if not DAY_RE.fullmatch(day):
            raise ValueError("day must be YYYY-MM-DD")
        date.fromisoformat(day)  # a real date, too
        key = hashlib.sha256((visitor_id + day).encode()).hexdigest()
        with self._transaction() as conn:
            return conn.execute(
                "INSERT INTO daily_session_counts (key, day, count) VALUES (?, ?, 1) "
                "ON CONFLICT(key) DO UPDATE SET count = count + 1 RETURNING count",
                (key, day),
            ).fetchall()[0][0]

    def purge_daily_counts(self, now: int) -> int:
        """Drop the daily counts older than 2 days before the UTC date of `now` (ms); returns the rows removed."""
        check_ms(now)
        today = datetime.fromtimestamp(now // 1000, UTC).date()
        cutoff = (today - timedelta(days=DAILY_COUNT_KEEP_DAYS)).isoformat()
        with self._transaction() as conn:
            return conn.execute("DELETE FROM daily_session_counts WHERE day < ?", (cutoff,)).rowcount

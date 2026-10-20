"""The store's plumbing (plan C2 "Connection and time"): the errors, the one connection, its lock and transactions,
and the anonymous tables, which are not thread rows. `concierge/store.py` builds the thread API on top.

One connection per store, guarded by a lock; methods are synchronous, so async callers use `asyncio.to_thread` and
never call them on the turn path (§4.4).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from concierge.models import TurnMetrics
from concierge.schema import PRAGMAS, SCHEMA, SCHEMA_VERSION

log = logging.getLogger(__name__)

BUSY_TIMEOUT_S = 5.0
SESSION_ID_RE = re.compile(r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class StoreError(Exception):
    """Base of the store's errors."""


class ThreadMissing(StoreError):
    """The thread doesn't exist (never created, or erased). Writes never re-create it."""


class FactMissing(StoreError):
    """The fact isn't a fact of the thread (never was, deleted, or already invalid for an invalidation)."""


class VersionConflict(StoreError):
    """Another writer bumped the thread's version since the caller loaded it."""

    def __init__(self, current: int) -> None:
        super().__init__(f"thread is at version {current}")
        self.current = current


class StoreBase:
    def __init__(self, path: str | Path, clock: Callable[[], int] = now_ms) -> None:
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
        self._owner: int | None = None  # the thread holding _lock (see _locked)
        # isolation_level=None: no implicit BEGIN, the store issues BEGIN IMMEDIATE itself. timeout is SQLite's
        # busy timeout, how long a writer waits for another process's write lock.
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, timeout=BUSY_TIMEOUT_S, check_same_thread=False
        )
        try:
            for pragma in PRAGMAS:
                self._pragma_with_retry(pragma)
            if self.pragma("journal_mode") != "wal":
                raise StoreError(f"journal_mode is {self.pragma('journal_mode')!r}, not 'wal'")
            self._create_schema()
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            self._conn.close()
            raise

    def _pragma_with_retry(self, pragma: str) -> None:
        # Switching a new file to WAL needs an exclusive lock and SQLite doesn't run the busy handler for it, so
        # processes opening a fresh file together get "database is locked" at once. Retry up to the busy timeout.
        deadline = time.monotonic() + BUSY_TIMEOUT_S
        while True:
            try:
                self._conn.execute(pragma).fetchall()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    def _create_schema(self) -> None:
        # One script (the DDL's comments hold semicolons, so it can't be split on them). executescript would COMMIT
        # an open transaction first, so the BEGIN is part of the script and the transaction stays open after it.
        self._conn.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}")
        found = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if found > SCHEMA_VERSION:
            raise StoreError(f"the file has schema version {found}; this code knows {SCHEMA_VERSION}")
        if found < SCHEMA_VERSION:
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._locked() as conn:
            conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    @contextmanager
    def _locked(self) -> Iterator[sqlite3.Connection]:
        """The connection, under the lock. The lock isn't reentrant: a Store method called from a `write` fn (or an
        `apply_fact_ops` callable) on the same thread raises here rather than deadlocking."""
        if self._owner == threading.get_ident():
            raise StoreError("a Store method was called from inside write(); fn may use only its conn")
        with self._lock:
            self._owner = threading.get_ident()
            try:
                yield self._conn
            finally:
                self._owner = None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE (the write lock now, not at the first write) ... COMMIT, or ROLLBACK on any error."""
        with self._locked() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:  # SQLite may have rolled back on its own already
                    conn.execute("ROLLBACK")
                raise

    def _checkpoint(self) -> None:
        """Best effort: copy the WAL into the file and empty it, so deleted values (whose old pages sit in the
        `-wal` until a checkpoint, even with secure_delete) leave the disk now. Busy (another process is reading)
        is logged; the next checkpoint finishes the job (plan C2 "Erasure")."""
        try:
            with self._locked() as conn:
                busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        except sqlite3.OperationalError as exc:
            log.warning("wal checkpoint failed: %s", exc)
            return
        if busy:
            log.warning("wal checkpoint was busy; the next one finishes it")

    def _read(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._locked() as conn:
            return conn.execute(sql, params).fetchall()

    def pragma(self, name: str) -> Any:  # noqa: ANN401 (a pragma's value is whatever SQLite returns)
        return self._read(f"PRAGMA {name}")[0][0]

    # Anonymous metrics (B9): no thread, no visitor id, no text

    def add_turn_metrics(self, session_id: str, metrics: TurnMetrics) -> None:
        # The one free-form key in the table: a random uuid4 hex per session, so no visitor or room id fits.
        if not SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("session_id must be a uuid4 hex (uuid.uuid4().hex)")
        # Durations are kept to whole milliseconds, so they are harder to line up exactly with other telemetry.
        values = {
            k: (float(round(v)) if isinstance(v, float) else v) for k, v in metrics.model_dump().items()
        }
        values["compacted"] = int(metrics.compacted)
        columns = ", ".join(["session_id", *values])
        marks = ", ".join("?" * (len(values) + 1))
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO anonymous_turn_metrics ({columns}) VALUES ({marks})", (session_id, *values.values())
            )

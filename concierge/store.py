"""The SQLite thread store (spec §4.2; plan `docs/plans/2026-10-20-C2-store.md`).

One connection per `Store`, guarded by a lock; methods are synchronous, so async callers use `asyncio.to_thread`
and never call them on the turn path (§4.4). Every write to a thread's rows is one `BEGIN IMMEDIATE` transaction
that bumps `threads.version` once (`write`, the fence). Only `get_or_create_thread` ever inserts a thread, so a
write to an erased thread raises `ThreadMissing` instead of re-creating it.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar

from pydantic import TypeAdapter

from concierge.models import JournalRow, JournalType, Thread, TurnMetrics, VisitorState
from concierge.schema import PRAGMAS, SCHEMA, SCHEMA_VERSION

T = TypeVar("T")

BUSY_TIMEOUT_S = 5.0
SESSION_ID_RE = re.compile(r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}")

_JOURNAL_TYPE: TypeAdapter[JournalType] = TypeAdapter(JournalType)
_THREAD_COLUMNS = "id, visitor_id, created_at, last_active_at, idle_ttl_s, attributes, version"
_EMPTY_STATE = VisitorState().model_dump_json()


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class StoreError(Exception):
    """Base of the store's errors."""


class ThreadMissing(StoreError):
    """The thread doesn't exist (never created, or erased). Writes never re-create it."""


class VersionConflict(StoreError):
    """Another writer bumped the thread's version since the caller loaded it."""

    def __init__(self, current: int) -> None:
        super().__init__(f"thread is at version {current}")
        self.current = current


def _thread(row: tuple[Any, ...]) -> Thread:
    tid, visitor_id, created_at, last_active_at, idle_ttl_s, attributes, version = row
    return Thread(
        id=tid, visitor_id=visitor_id, created_at=created_at, last_active_at=last_active_at,
        idle_ttl_s=idle_ttl_s, visits=json.loads(attributes)["visits"], version=version,
    )


class Store:
    def __init__(self, path: str | Path, clock: Callable[[], int] = now_ms) -> None:
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
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
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE (the write lock now, not at the first write) ... COMMIT, or ROLLBACK on any error."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:  # SQLite may have rolled back on its own already
                    self._conn.execute("ROLLBACK")
                raise

    def _read(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def pragma(self, name: str) -> Any:  # noqa: ANN401 (a pragma's value is whatever SQLite returns)
        return self._read(f"PRAGMA {name}")[0][0]

    # Threads

    def get_or_create_thread(self, visitor_id: str) -> Thread:
        """The only call that creates a thread (§4.2). A revisit counts the visit, touches last_active_at and
        bumps the version, all in one transaction."""
        with self._transaction() as conn:
            now = self._clock()  # read under the lock, so a writer that waited never commits an older time
            row = conn.execute(
                "INSERT INTO threads (id, visitor_id, created_at, last_active_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(visitor_id) DO UPDATE SET last_active_at = max(last_active_at, excluded.last_active_at), "
                "attributes = json_set(attributes, '$.visits', coalesce(json_extract(attributes, '$.visits'), 0) + 1), "
                f"version = version + 1 RETURNING {_THREAD_COLUMNS}",
                (uuid.uuid4().hex, visitor_id, now, now),
            ).fetchall()[0]
            conn.execute(
                "INSERT OR IGNORE INTO state (thread_id, state, updated_at) VALUES (?, ?, ?)",
                (row[0], _EMPTY_STATE, now),
            )
        return _thread(row)

    def thread_for(self, visitor_id: str) -> Thread | None:
        rows = self._read(f"SELECT {_THREAD_COLUMNS} FROM threads WHERE visitor_id = ?", (visitor_id,))
        return _thread(rows[0]) if rows else None

    def version(self, thread_id: str) -> int:
        rows = self._read("SELECT version FROM threads WHERE id = ?", (thread_id,))
        if not rows:
            raise ThreadMissing(thread_id)
        return rows[0][0]

    def state(self, thread_id: str) -> VisitorState:
        rows = self._read("SELECT state FROM state WHERE thread_id = ?", (thread_id,))
        if not rows:
            raise ThreadMissing(thread_id)
        return VisitorState.model_validate_json(rows[0][0])

    # The fence

    def write(self, thread_id: str, expected_version: int | None, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run fn(conn) inside BEGIN IMMEDIATE and bump the thread's version once.

        `expected_version=None` means "the version read inside the transaction": for appends that don't depend on
        what the caller loaded, so they never conflict but still fail once the thread is gone. `fn` must use only
        `conn`: the store's lock is held, so calling another Store method from it would deadlock.
        """
        with self._transaction() as conn:
            row = conn.execute("SELECT version FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if row is None:
                raise ThreadMissing(thread_id)
            current = row[0]
            if expected_version is not None and current != expected_version:
                raise VersionConflict(current)
            result = fn(conn)
            bumped = conn.execute(
                "UPDATE threads SET version = version + 1 WHERE id = ? AND version = ?", (thread_id, current)
            ).rowcount
            if bumped != 1:  # can't happen under BEGIN IMMEDIATE; kept as the fence
                raise VersionConflict(current)
            return result

    # Journal (append-only)

    def journal(self, thread_id: str, session_id: str, type: JournalType, payload: dict[str, Any]) -> int:
        kind = _JOURNAL_TYPE.validate_python(type)
        if not isinstance(payload, dict):  # journal_rows reads every payload back as a JSON object
            raise TypeError(f"journal payload must be a dict, not {payload.__class__.__name__}")
        # Both fail here, before the transaction: unserializable values, and lone surrogates UTF-8 can't hold.
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        body.encode()

        def append(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO journal (thread_id, session_id, ts_ms, type, payload) VALUES (?, ?, ?, ?, ?)",
                (thread_id, session_id, self._clock(), kind, body),
            )
            return int(cursor.lastrowid or 0)

        return self.write(thread_id, None, append)

    def journal_rows(self, thread_id: str) -> list[JournalRow]:
        rows = self._read(
            "SELECT id, thread_id, session_id, ts_ms, type, payload FROM journal WHERE thread_id = ? ORDER BY id",
            (thread_id,),
        )
        return [
            JournalRow(id=i, thread_id=t, session_id=s, ts_ms=ts, type=k, payload=json.loads(p))
            for i, t, s, ts, k, p in rows
        ]

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

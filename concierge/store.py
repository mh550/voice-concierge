"""The SQLite thread store (spec §4.2; plan `docs/plans/2026-10-20-C2-store.md`).

Every write to a thread's rows is one `BEGIN IMMEDIATE` transaction that bumps `threads.version` once (`write`, the
fence); fact ops go through `apply_fact_ops`, which reloads and reapplies on a conflict. Only
`get_or_create_thread` ever inserts a thread, so a write to an erased thread raises `ThreadMissing` instead of
re-creating it. The connection, its lock and the anonymous tables are in `concierge/store_base.py`; `forget_me` and
the TTL purge in `concierge/store_erasure.py`.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
import uuid
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

from pydantic import TypeAdapter

from concierge import fact_ops
from concierge.fact_ops import Ops
from concierge.models import (
    AddFact,
    ApplyResult,
    DeleteFact,
    Fact,
    InvalidateFact,
    JournalRow,
    JournalType,
    Thread,
    VisitorState,
)
from concierge.store_base import (  # noqa: F401 (the errors and now_ms are re-exported)
    FactMissing,
    StoreBase,
    StoreError,
    ThreadMissing,
    VersionConflict,
    now_ms,
)
from concierge.store_erasure import ErasureStore

T = TypeVar("T")

MAX_ATTEMPTS = 5

_JOURNAL_TYPE: TypeAdapter[JournalType] = TypeAdapter(JournalType)
_THREAD_COLUMNS = "id, visitor_id, created_at, last_active_at, idle_ttl_s, attributes, version"
_EMPTY_STATE = VisitorState().model_dump_json()


def _thread(row: tuple[Any, ...]) -> Thread:
    tid, visitor_id, created_at, last_active_at, idle_ttl_s, attributes, version = row
    return Thread(
        id=tid, visitor_id=visitor_id, created_at=created_at, last_active_at=last_active_at,
        idle_ttl_s=idle_ttl_s, visits=json.loads(attributes)["visits"], version=version,
    )


class Store(ErasureStore):
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
        `conn`: the store's lock is held, so calling another Store method from it raises StoreError.
        """
        with self._transaction() as conn:
            row = conn.execute("SELECT version FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if row is None:
                raise ThreadMissing(thread_id)
            current = row[0]
            if expected_version is not None and current != expected_version:
                raise VersionConflict(current)
            result = fn(conn)
            fence = current if expected_version is None else expected_version
            bumped = conn.execute(
                "UPDATE threads SET version = version + 1 WHERE id = ? AND version = ?", (thread_id, fence)
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

    # Facts (the ops themselves run in concierge/fact_ops.py, inside the fence)

    def apply_fact_ops(
        self, thread_id: str, ops: Ops, *, based_on: int | None = None, session_id: str = ""
    ) -> ApplyResult:
        """Apply a batch of fact ops in one fenced write: one transaction, one version bump.

        `based_on` is the version the caller decided the ops at (C4's extractor, before its LLM call); by default
        the current one. On a conflict: back off, reload the version and reapply, at most MAX_ATTEMPTS times, then
        let the `VersionConflict` propagate. A callable `ops` is re-resolved against the facts each time.
        """
        expected = based_on if based_on is not None else self.version(thread_id)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self.write(thread_id, expected, partial(self._apply, thread_id, ops, session_id, expected))
            except VersionConflict as exc:
                if exc.current < expected:
                    raise StoreError(f"based_on {expected} is ahead of the thread's version {exc.current}") from exc
                if attempt == MAX_ATTEMPTS:
                    raise
                time.sleep(random.uniform(0.01, 0.03) * attempt)  # jittered: let the other writer finish
                expected = self.version(thread_id)  # reloaded after the sleep
        raise AssertionError("unreachable")

    def _apply(self, thread_id: str, ops: Ops, session_id: str, version: int, conn: sqlite3.Connection) -> ApplyResult:
        added, skipped = fact_ops.apply(conn, thread_id, ops, self._clock(), session_id)
        return ApplyResult(version=version + 1, added=added, skipped=skipped)

    def add_fact(self, thread_id: str, op: AddFact, *, session_id: str = "") -> Fact:
        """Insert one fact (created_at = valid_from = now), journal it and recompute the state. A `supersedes`
        id that isn't a valid fact of the thread is skipped silently; use apply_fact_ops to see the skips."""
        (fact_id,) = self.apply_fact_ops(thread_id, [op], session_id=session_id).added
        with self._locked() as conn:
            fact = fact_ops.fact(conn, fact_id)
        if fact is None:  # deleted by another writer in between
            raise FactMissing(fact_id)
        return fact

    def invalidate_fact(
        self, fact_id: int, superseded_by: int | None = None, *, thread_id: str | None = None, session_id: str = ""
    ) -> None:
        """Set valid_to = now (and superseded_by, a fact of the same thread); the row stays. `thread_id` scopes
        the call (a tool passes its visitor's). FactMissing if there is no such valid fact."""
        op = InvalidateFact(fact_id=fact_id, superseded_by=superseded_by)
        tid = self._thread_of(fact_id) if thread_id is None else thread_id
        if fact_id in self.apply_fact_ops(tid, [op], session_id=session_id).skipped:
            raise FactMissing(fact_id)

    def delete_fact(self, fact_id: int, *, thread_id: str | None = None, session_id: str = "") -> None:
        """Really delete the row (the `forget` tool, B5), recompute the state and checkpoint the WAL, so the value
        leaves the disk too. FactMissing if there is none. Tools pass `thread_id`, so a model-supplied id can't
        reach another visitor's fact."""
        tid = self._thread_of(fact_id) if thread_id is None else thread_id
        if fact_id in self.apply_fact_ops(tid, [DeleteFact(fact_id=fact_id)], session_id=session_id).skipped:
            raise FactMissing(fact_id)
        self._checkpoint()  # the value's old pages are still in the -wal until then

    def _thread_of(self, fact_id: int) -> str:
        rows = self._read("SELECT thread_id FROM facts WHERE id = ?", (fact_id,))
        if not rows:
            raise FactMissing(fact_id)
        return rows[0][0]

    def valid_facts(self, thread_id: str) -> list[Fact]:
        """valid_to IS NULL, ordered by valid_from, id."""
        with self._locked() as conn:
            return fact_ops.valid_facts(conn, thread_id)

    def fact_history(self, thread_id: str) -> list[Fact]:
        """Every remaining row, valid or not, in the same order."""
        with self._locked() as conn:
            return fact_ops.fact_history(conn, thread_id)

    def recompute_state(self, thread_id: str) -> VisitorState:
        """Rebuild VisitorState from the valid facts and store it, in one fenced write."""
        return self.write(thread_id, None, lambda conn: fact_ops.store_state(conn, thread_id, self._clock()))

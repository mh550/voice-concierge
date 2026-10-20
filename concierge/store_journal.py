"""The fence and the journal (spec §4.2; plan C2 "The fence", moved out of `concierge/store.py` by C5-02 so the store
stays small). `Store` subclasses `JournalStore`; import both from `concierge.store`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import TypeAdapter

from concierge.models import JournalRow, JournalType
from concierge.store_base import ThreadMissing, VersionConflict
from concierge.store_erasure import ErasureStore

T = TypeVar("T")

_JOURNAL_TYPE: TypeAdapter[JournalType] = TypeAdapter(JournalType)


class JournalStore(ErasureStore):
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

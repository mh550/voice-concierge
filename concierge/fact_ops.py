"""Fact ops inside the fence (plan C2 "Reload and reapply"). Every function takes the connection `Store.write`
holds inside its BEGIN IMMEDIATE, so a batch's facts, its journal rows and the new state commit together or not at
all. Ops apply literally (plan: "Where the catalogue's ADD rules run"): slot rules are C4's merge, and only the
derived state enforces the slot shapes.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, TypeAdapter

from concierge.models import SLOTS, AddFact, DeleteFact, Fact, FactOp, InvalidateFact, JournalType, VisitorState

_FIELDS = (
    "id", "thread_id", "slot", "value", "confidence", "source", "channel", "turn_id", "created_at", "valid_from",
    "valid_to", "superseded_by",
)
_COLUMNS = ", ".join(_FIELDS)
_OPS: TypeAdapter[list[FactOp]] = TypeAdapter(list[FactOp])

OpList = Sequence[FactOp | dict[str, Any]]
# A list of ops, or a callable that decides them against the valid facts read inside the transaction.
Ops = OpList | Callable[[list[Fact]], OpList]


def _facts(conn: sqlite3.Connection, where: str, params: tuple[Any, ...]) -> list[Fact]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM facts WHERE {where} ORDER BY valid_from, id", params)
    return [Fact(**dict(zip(_FIELDS, row, strict=True))) for row in rows]


def valid_facts(conn: sqlite3.Connection, thread_id: str) -> list[Fact]:
    return _facts(conn, "thread_id = ? AND valid_to IS NULL", (thread_id,))


def fact_history(conn: sqlite3.Connection, thread_id: str) -> list[Fact]:
    return _facts(conn, "thread_id = ?", (thread_id,))


def fact(conn: sqlite3.Connection, fact_id: int) -> Fact | None:
    found = _facts(conn, "id = ?", (fact_id,))
    return found[0] if found else None


def _key(value: str) -> str:
    return " ".join(value.casefold().split())


def derive_state(valid: list[Fact], previous: VisitorState) -> VisitorState:
    """Single slots take the newest valid fact; sets hold each value once (equal after casefold and whitespace
    collapse; the newest spelling, at its newest position) and keep the newest `max_items`, oldest first. The
    last-visit summary isn't a fact and carries over. Built with model_validate, so the caps and 8 KB are checked.

    "Newest" is the highest id: AUTOINCREMENT follows commit order, and valid_from follows a clock that can step back.
    """
    ordered = sorted(valid, key=lambda f: f.id)
    fields: dict[str, Any] = {"last_visit_summary": previous.last_visit_summary}
    for slot, spec in SLOTS.items():
        values = [f.value for f in ordered if f.slot == slot]
        if spec.kind == "single":
            fields[slot] = values[-1] if values else None
        else:
            newest: dict[str, str] = {}
            for v in values:  # a later equal value replaces the earlier one, at the later position
                newest.pop(_key(v), None)
                newest[_key(v)] = v
            fields[slot] = list(newest.values())[-spec.max_items :]
    return VisitorState.model_validate(fields)


def store_state(conn: sqlite3.Connection, thread_id: str, now: int) -> VisitorState:
    row = conn.execute("SELECT state FROM state WHERE thread_id = ?", (thread_id,)).fetchone()
    previous = VisitorState.model_validate_json(row[0]) if row else VisitorState()
    state = derive_state(valid_facts(conn, thread_id), previous)
    conn.execute(
        "INSERT INTO state (thread_id, state, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(thread_id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
        (thread_id, state.model_dump_json(), now),
    )
    return state


def _journal(
    conn: sqlite3.Connection, thread_id: str, session_id: str, now: int, kind: JournalType, payload: dict[str, Any]
) -> None:
    # Ids, slot and provenance only, never the value: a delete (the `forget` tool) leaves the value nowhere.
    conn.execute(
        "INSERT INTO journal (thread_id, session_id, ts_ms, type, payload) VALUES (?, ?, ?, ?, ?)",
        (thread_id, session_id, now, kind, json.dumps(payload, separators=(",", ":"))),
    )


def _invalidate(
    conn: sqlite3.Connection, thread_id: str, fact_id: int, superseded_by: int | None, now: int
) -> str | None:
    """Set valid_to on a valid fact of this thread; its slot, or None when there is no such fact (a skip)."""
    if superseded_by is not None and (
        superseded_by == fact_id
        or conn.execute("SELECT 1 FROM facts WHERE id = ? AND thread_id = ?", (superseded_by, thread_id)).fetchone()
        is None
    ):
        return None
    row = conn.execute(
        "UPDATE facts SET valid_to = ?, superseded_by = ? WHERE id = ? AND thread_id = ? AND valid_to IS NULL "
        "RETURNING slot",
        (now, superseded_by, fact_id, thread_id),
    ).fetchone()
    return row[0] if row else None


def apply(
    conn: sqlite3.Connection, thread_id: str, ops: Ops, now: int, session_id: str
) -> tuple[list[int], list[int], list[int]]:
    """Reload the valid facts, resolve and re-validate the ops, apply them in order, journal each, store the state.

    Returns (added fact ids, skipped target ids, deleted fact ids). A target that isn't a fact of this thread is skipped, as is an
    invalidation of an already-invalid fact (its first valid_to stands).
    """
    resolved = ops(valid_facts(conn, thread_id)) if callable(ops) else ops
    # From plain data, so an op mutated after it was built (pydantic models aren't frozen) is checked again.
    checked = _OPS.validate_python([op.model_dump() if isinstance(op, BaseModel) else op for op in resolved])
    added: list[int] = []
    skipped: list[int] = []
    deleted: list[int] = []

    def invalidate(fact_id: int, superseded_by: int | None) -> None:
        slot = _invalidate(conn, thread_id, fact_id, superseded_by, now)
        if slot is None:
            skipped.append(fact_id)
        else:
            payload = {"fact_id": fact_id, "slot": slot, "superseded_by": superseded_by}
            _journal(conn, thread_id, session_id, now, "fact_invalidated", payload)

    for op in checked:
        match op:
            case AddFact():
                (new_id,) = conn.execute(
                    "INSERT INTO facts (thread_id, slot, value, confidence, source, channel, turn_id, created_at, "
                    "valid_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (thread_id, op.slot, op.value, op.confidence, op.source, op.channel, op.turn_id, now, now),
                ).fetchone()
                added.append(new_id)
                payload = op.model_dump(include={"slot", "source", "channel", "turn_id", "supersedes"})
                _journal(conn, thread_id, session_id, now, "fact_added", {"fact_id": new_id, **payload})
                for old in op.supersedes:
                    invalidate(old, new_id)
            case InvalidateFact():
                invalidate(op.fact_id, op.superseded_by)
            case DeleteFact():
                row = conn.execute(
                    "DELETE FROM facts WHERE id = ? AND thread_id = ? RETURNING slot", (op.fact_id, thread_id)
                ).fetchone()
                if row is None:
                    skipped.append(op.fact_id)
                else:
                    deleted.append(op.fact_id)
                    _journal(conn, thread_id, session_id, now, "fact_deleted", {"fact_id": op.fact_id, "slot": row[0]})
    store_state(conn, thread_id, now)
    return added, skipped, deleted

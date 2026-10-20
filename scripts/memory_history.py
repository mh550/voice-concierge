"""Print one visitor's fact timeline (plan C2 "scripts/memory_history.py").

    python scripts/memory_history.py <db> <visitor_id>

One tab-separated line per fact, ordered by valid_from then id: slot, value, valid_from, valid_to or `current`,
superseded_by or `-` (times in ISO 8601 UTC). Deleted facts don't appear: a `forget` really deletes (B5). The db is
opened read-only, so this never creates or changes a database (SQLite may add the `-wal`/`-shm` side files a reader
needs). Exit 1: no thread for that visitor; exit 2: usage, no such file, or not a memory store. It prints visitor
data: run it on the box that holds the db, to a terminal only.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from concierge.store import Store, StoreError


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: memory_history.py <db> <visitor_id>", file=sys.stderr)
        return 2
    db, visitor_id = Path(argv[0]), argv[1]
    if not db.is_file():
        print(f"no database at {db}", file=sys.stderr)
        return 2
    try:
        store = Store.open_readonly(db)
    except (StoreError, sqlite3.DatabaseError) as exc:
        print(f"not a memory store: {db} ({exc})", file=sys.stderr)
        return 2
    with store:
        try:
            thread = store.thread_for(visitor_id)
            history = [] if thread is None else store.fact_history(thread.id)
        except (sqlite3.DatabaseError, ValidationError) as exc:  # the type only: its text can quote a value
            print(f"not a memory store: {db} ({type(exc).__name__})", file=sys.stderr)
            return 2
        if thread is None:
            print("no thread for this visitor", file=sys.stderr)
            return 1
        for fact in history:
            valid_to = "current" if fact.valid_to is None else iso(fact.valid_to)
            superseded_by = "-" if fact.superseded_by is None else str(fact.superseded_by)
            print("\t".join((fact.slot, fact.value, iso(fact.valid_from), valid_to, superseded_by)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

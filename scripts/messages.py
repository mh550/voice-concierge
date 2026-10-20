"""List the messages visitors left for Michael (spec §4.6; plan C8 "The script").

    python scripts/messages.py <db>

One tab-separated line per message, newest first: created_at (ISO 8601 UTC), the contact or `-`, the text. The db is
opened read-only, so this never creates or changes a database. Exit 2: usage, no such file, or not a memory store.
It prints visitor data: run it on the box that holds the db, to a terminal only.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from memory_history import iso  # the same timestamp format; scripts/ is sys.path[0] when this runs
from pydantic import ValidationError

from concierge.store import Store, StoreError


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: messages.py <db>", file=sys.stderr)
        return 2
    db = Path(argv[0])
    if not db.is_file():
        print(f"no database at {db}", file=sys.stderr)
        return 2
    try:
        with Store.open_readonly(db) as store:
            messages = store.messages()
    except (StoreError, sqlite3.DatabaseError, ValidationError) as exc:  # the type only: its text can quote a value
        print(f"not a memory store: {db} ({type(exc).__name__})", file=sys.stderr)
        return 2
    for message in messages:
        print("\t".join((iso(message.created_at), message.contact or "-", message.text)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

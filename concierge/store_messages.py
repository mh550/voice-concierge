"""The messages for Michael (spec §4.6, C8), moved out of `concierge/store.py` by V2-03 so the store stays small.
`Store` subclasses `MessageStore`; import it from `concierge.store`.
"""

from __future__ import annotations

import sqlite3

from concierge.models import Message
from concierge.store_journal import JournalStore


class MessageStore(JournalStore):
    def add_message(self, thread_id: str, text: str, contact: str | None) -> int:
        """Insert one `messages_for_michael` row in one fenced write; ThreadMissing (nothing written, no thread
        re-created) once the visitor is erased. The caller caps and gates the values (`concierge/message_tool.py`)."""

        def insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO messages_for_michael (thread_id, text, contact, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, text, contact, self._clock()),
            )
            return int(cursor.lastrowid or 0)

        return self.write(thread_id, None, insert)

    def messages(self) -> list[Message]:
        """Every visitor's messages, newest first."""
        rows = self._read(
            "SELECT id, thread_id, text, contact, created_at FROM messages_for_michael "
            "ORDER BY created_at DESC, id DESC"
        )
        return [Message(id=i, thread_id=t, text=x, contact=c, created_at=ts) for i, t, x, c, ts in rows]

"""The write behind the agent's `leave_message_for_michael` tool (spec §4.6; plan C8 "The tool").

The visitor asked, so the turn waits for it, like `remember`: one local SQLite write on the writer's store thread,
under the thread's fence (`Store.add_message`). The contact is the write gate's one exception (§4.4): its email and
phone rules are lifted, every other rule holds. The text runs the full gate, so contact details go in `contact`.
Over a cap nothing is written (never truncated). Replies never echo the text or the contact.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Literal

from concierge.gate import check_text
from concierge.memory_tools import CANT_SAVE, STORE_FAILED
from concierge.memory_writer import MemoryWriter
from concierge.store import StoreError, ThreadMissing

logger = logging.getLogger("concierge.message_tool")

TEXT_MAX_CHARS = 500
CONTACT_MAX_CHARS = 120

MESSAGE_LEFT = "Done, Michael will get your message."
TOO_LONG = (
    f"That's too long to pass on: keep the message to {TEXT_MAX_CHARS} characters and the contact to "
    f"{CONTACT_MAX_CHARS}."
)
CANT_TAKE = "I can't pass that on. Put only the message in text, and an email or phone number only in contact."
_FAILURES = (StoreError, sqlite3.Error, ValueError)  # as in memory_tools


def _rejection(text: str, contact: str | None) -> tuple[Literal["text", "contact"], str] | None:
    """The first field the gate rejects, with its reason; None when both pass."""
    result = check_text(text)
    if not result.ok:
        return "text", str(result.reason)
    if contact is not None:
        result = check_text(contact, purpose="contact")
        if not result.ok:
            return "contact", str(result.reason)
    return None


def _leave(writer: MemoryWriter, text: str, contact: str | None) -> bool:
    """On the store thread: the row, or the gate_rejected journal row (field and reason, never the value)."""
    rejection = _rejection(text, contact)
    if rejection is None:
        writer.store.add_message(writer.thread_id, text, contact)
        return True
    field, reason = rejection
    writer.store.journal(writer.thread_id, writer.session_id, "gate_rejected", {"field": field, "reason": reason})
    return False


async def do_leave_message(writer: MemoryWriter | None, text: str, contact: str | None) -> str:
    if writer is None or writer.erased:
        return CANT_SAVE
    text = text.strip()
    contact = (contact or "").strip() or None
    if len(text) > TEXT_MAX_CHARS or (contact is not None and len(contact) > CONTACT_MAX_CHARS):
        return TOO_LONG
    try:
        left = await writer.call(_leave, writer, text, contact)
    except ThreadMissing:
        writer.erased = True
        return CANT_SAVE
    except _FAILURES as exc:
        logger.warning("leave_message failed (%s)", type(exc).__name__)
        return STORE_FAILED
    return MESSAGE_LEFT if left else CANT_TAKE

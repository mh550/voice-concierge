"""The hot-path memory writes behind the agent's `remember` and `forget` tools (spec §4.4, B4, B5; plan C4
"Hot-path tools").

The visitor asked explicitly, so these are the only memory writes a turn waits for: one local SQLite write on the
writer's store thread, in order with the background runs. `remember` goes through the merge (gate, grounding, the
B12 name rule, the slot rules) with the visitor's latest turn as its source. `forget` really deletes the matching
facts and the history they superseded, and keeps the window from adding them back. Replies never echo a value.
"""

from __future__ import annotations

import logging
import sqlite3

from concierge.fact_ops import _key
from concierge.forget_match import select
from concierge.grounding import shares_a_word
from concierge.memory_writer import MemoryWriter
from concierge.merge import merge
from concierge.models import DeleteFact, Fact, SlotName
from concierge.ops import AddOp
from concierge.store import StoreError, ThreadMissing
from concierge.turns import Turn, visible_text

logger = logging.getLogger("concierge.memory_tools")

CANT_SAVE = "I can't save anything this visit."
CANT_REMEMBER = "I can't remember that."
REMEMBERED = "Got it, I'll remember that."
ALREADY_KNOWN = "I already have that."
FORGOTTEN = "Forgotten."
NOTHING_TO_FORGET = "I didn't have anything about that."
STORE_FAILED = "Sorry, I couldn't do that just now."
_FAILURES = (StoreError, sqlite3.Error, ValueError)  # ValueError: a pydantic ValidationError

_PREFIXES: dict[str, SlotName] = {
    "name": "name",
    "role": "role",
    "company": "company",
    "interest": "interests",
    "interests": "interests",
    "follow-up": "follow_up_wanted",
    "follow_up": "follow_up_wanted",
    "follow up": "follow_up_wanted",
    "follow_up_wanted": "follow_up_wanted",
}
def parse_fact(fact: str) -> tuple[SlotName, str]:
    """`"<slot>: <value>"` → (slot, value); no or an unknown prefix → ("interests", the whole text)."""
    prefix, sep, rest = fact.partition(":")
    slot = _PREFIXES.get(" ".join(prefix.casefold().split()))
    if sep and slot is not None:
        return slot, rest.strip()
    return "interests", fact.strip()


def source_turn(writer: MemoryWriter, slot: SlotName, value: str) -> Turn | None:
    """The visitor turn the value comes from: for "I work at Acme." … "Can you remember that?", the first one. The
    newest user turn that shares a word with the value, else the latest (where the merge rejects an ungrounded value
    or an agent's guess). A name always cites the latest: it must be the yes to "Did I get that right" (B12)."""
    latest = writer.last_user_turn
    if slot == "name" or latest is None:
        return latest
    users = [t for t in reversed(writer.history) if t.role == "user"]
    return next((t for t in users if shares_a_word(value, visible_text(t))), latest)


async def do_remember(writer: MemoryWriter | None, fact: str) -> str:
    if writer is None or writer.erased:
        return CANT_SAVE
    slot, value = parse_fact(fact)
    turn = source_turn(writer, slot, value)
    if turn is None or not value:
        return CANT_REMEMBER
    op = AddOp(op="ADD", slot=slot, value=value, turn_id=turn.turn_id)
    try:
        result = await writer.call(
            merge, writer.store, writer.thread_id, [op], {turn.turn_id}, writer.session_id,
            turns=list(writer.history), source="user_asked_to_remember",
        )
    except ThreadMissing:
        writer.erased = True
        return CANT_SAVE
    except _FAILURES as exc:
        logger.warning("remember failed (%s)", type(exc).__name__)
        return STORE_FAILED
    if result.rejected:
        return CANT_REMEMBER
    return ALREADY_KNOWN if result.skipped else REMEMBERED


def _forget(writer: MemoryWriter, about: str) -> list[Fact]:
    """On the store thread: the matching facts (valid or not) and every row they superseded, deleted in one batch."""
    history = writer.store.fact_history(writer.thread_id)
    doomed = select(history, about)
    grew = True
    while grew:  # back through superseded_by: the rows a matched fact replaced
        older = {f.id for f in history if f.superseded_by in doomed} - doomed
        doomed |= older
        grew = bool(older)
    if not doomed:
        return []
    deletes = [DeleteFact(fact_id=i) for i in sorted(doomed)]
    deleted = set(writer.store.apply_fact_ops(writer.thread_id, deletes, session_id=writer.session_id).deleted)
    gone = [f for f in history if f.id in deleted]
    writer.forgotten.update((f.slot, _key(f.value)) for f in gone)  # here, before any later merge on this thread
    return gone


async def do_forget(writer: MemoryWriter | None, about: str) -> str:
    if writer is None or writer.erased:
        return CANT_SAVE
    writer.note_forget(about)  # first: a run that filters its ops after this sees it, even with nothing stored yet
    try:
        gone = await writer.call(_forget, writer, about)
    except ThreadMissing:
        writer.erased = True
        return CANT_SAVE
    except _FAILURES as exc:
        logger.warning("forget failed (%s)", type(exc).__name__)
        return STORE_FAILED
    return FORGOTTEN if gone else NOTHING_TO_FORGET

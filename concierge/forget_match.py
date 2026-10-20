"""What a `forget(about)` request names (plan C4 "Hot-path tools"): values by whole words first, a slot only when
`about` names nothing else.

"forget Acme" and "forget my interest in Rust" name values; "forget my name" and "forget what I said about my
company" name a slot. "forget my company's name" names two slots and no value, so it names nothing: the agent can
ask again. Shared by the forget tool (what to delete) and the writer (what the window may not add back).
"""

from __future__ import annotations

from collections.abc import Iterable

from concierge.fact_ops import _key
from concierge.grounding import words
from concierge.models import Fact, SlotName
from concierge.ops import AddOp, Op, UpdateOp

_SLOT_WORDS: dict[SlotName, frozenset[str]] = {
    "name": frozenset({"name"}),
    "role": frozenset({"job", "role", "title"}),
    "company": frozenset({"company", "employer", "work"}),
    "interests": frozenset({"interest"}),
    "follow_up_wanted": frozenset({"follow", "up"}),
}
# Words that say nothing about what to forget ("what I said about ...", "everything I told you about ...").
_FILLER = frozenset("said told forget everything thing all stuff mentioned mention info information where".split())


def value_matches(value: str, about: str) -> bool:
    """Every word of one is a word of the other; a value with no word tokens ("C++") must equal `about`."""
    have, asked = words(value), words(about)
    if not have:
        return _key(value) == _key(about)
    return bool(asked) and (have <= asked or asked <= have)


def named_slot(about: str) -> SlotName | None:
    """The one slot `about` names, when its words (fillers aside) are all that slot's words."""
    asked = words(about) - _FILLER
    if not asked:
        return None
    found = [slot for slot, slot_words in _SLOT_WORDS.items() if asked <= slot_words]
    return found[0] if len(found) == 1 else None


def select(facts: Iterable[Fact], about: str) -> set[int]:
    """The facts `about` names: the value matches, or (when none) every fact of the slot it names."""
    facts = list(facts)
    by_value = {f.id for f in facts if value_matches(f.value, about)}
    if by_value:
        return by_value
    slot = named_slot(about)
    return {f.id for f in facts if f.slot == slot} if slot is not None else set()


def blocks(slot: str | None, value: str, about: str) -> bool:
    """Whether a forget request for `about` covers an extracted (slot, value)."""
    return value_matches(value, about) or (slot is not None and slot == named_slot(about))


def was_forgotten(
    op: Op, positions: dict[str, int], forgotten: list[tuple[SlotName, str, int]], requests: list[tuple[str, int]]
) -> bool:
    """An extracted ADD or UPDATE, from a turn before a forget request this session, that the request covers or
    whose value the tool deleted for it (`positions`: turn id → its index in the session's history). A later turn
    that says it again is kept, whether or not the value had been stored when the visitor asked."""
    position = positions.get(op.turn_id)
    if not isinstance(op, AddOp | UpdateOp) or position is None:
        return False
    key = _key(op.value)
    deleted = any(
        position < asked_at and k == key and (op.slot is None or op.slot == slot) for slot, k, asked_at in forgotten
    )
    return deleted or any(position < asked_at and blocks(op.slot, op.value, about) for about, asked_at in requests)

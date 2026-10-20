"""The deterministic merge (spec §4.4 "Merge", §4.0 "Delta edits, not rewrites", "Temporal validity"; plan C4
"The merge").

The extractor proposes ops; this code decides them. Each op is checked (turn, target, gate, grounding, name
confirmation, confidence) and applied by the slot rules, in order, each seeing the ones before it. The decision runs
inside `Store.apply_fact_ops`' transaction against the facts read there, so a retry after a version conflict decides
again against the newer facts. The extractor never really deletes: a DELETE invalidates, and only `forget` deletes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from concierge.fact_ops import value_key
from concierge.gate import check_value
from concierge.grounding import is_confirmed_name, shares_a_word
from concierge.models import SLOTS, AddFact, Fact, FactOp, InvalidateFact, Note, SlotName, Source, VisitorState
from concierge.ops import AddOp, DeleteOp, Op, OpKind, UpdateOp
from concierge.store import Store
from concierge.turns import Turn, visible_text

MIN_CONFIDENCE = 0.5
# follow_up_wanted's value is the extractor's phrase for a request; asked_about is naturally a paraphrase (D10).
_GROUNDING_EXEMPT: frozenset[str] = frozenset({"follow_up_wanted", "asked_about"})


class Rejection(BaseModel):
    """A rejected op, as journaled in gate_rejected: ids, slot and reason, never the value (D8)."""

    index: int
    op: OpKind
    reason: str
    slot: SlotName | None  # None for a slot that isn't one: the name is the model's text
    turn_id: str | None  # None unless it's a turn the merge was given
    fact_id: int | None


class Skip(BaseModel):
    index: int
    reason: Literal["duplicate", "replaced_in_batch"]


class MergeResult(BaseModel):
    version: int
    added: list[int]
    invalidated: list[int]
    rejected: list[Rejection]
    skipped: list[Skip]
    state: VisitorState


@dataclass
class _Live:
    """A valid fact as the batch sees it: a stored one (fact_id) or one this batch adds (pending)."""

    slot: str
    value: str
    fact_id: int | None = None
    pending: AddFact | None = None
    index: int = -1  # the op that added it


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


@dataclass
class _Decision:
    """One attempt's decision against the valid facts it was given."""

    turns: dict[str, Turn]
    order: list[Turn]
    known: set[str]
    live: list[_Live]
    source: Source | None = None  # every fact's source, when the caller fixes it (the remember tool)
    out: list[FactOp] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)

    def run(self, ops: Sequence[Op]) -> None:
        for index, op in enumerate(ops):
            try:
                self._one(index, op)
            except _Rejected as exc:
                self.rejected.append(self._rejection(index, op, exc.reason))

    def _rejection(self, index: int, op: Op, reason: str) -> Rejection:
        slot = op.slot if not isinstance(op, DeleteOp) and op.slot in SLOTS else None
        turn_id = op.turn_id if op.turn_id in self.turns or op.turn_id in self.known else None
        fact_id = None if isinstance(op, AddOp) else op.fact_id
        return Rejection(index=index, op=op.op, reason=reason, slot=slot, turn_id=turn_id, fact_id=fact_id)

    def _target(self, fact_id: int) -> _Live:
        for entry in self.live:
            if entry.fact_id == fact_id:
                return entry
        raise _Rejected("stale_fact")  # invalidated or forgotten since the extractor read it, or never ours

    def _one(self, index: int, op: Op) -> None:
        turn = self.turns.get(op.turn_id) if op.turn_id is not None else None
        if turn is not None and turn.role == "agent":
            raise _Rejected("agent_attributed")
        if isinstance(op, DeleteOp):  # needs no turn (spec §4.4), but never the agent's
            self.live.remove(self._target(op.fact_id))
            self.out.append(InvalidateFact(fact_id=op.fact_id, reason=op.reason or "unspecified"))
            return
        if turn is None or op.turn_id not in self.known:
            raise _Rejected("unknown_turn")
        target = self._target(op.fact_id) if isinstance(op, UpdateOp) else None
        slot = target.slot if target is not None else op.slot
        if target is not None and op.slot is not None and op.slot != slot:
            raise _Rejected("slot_mismatch")
        if slot not in SLOTS:
            raise _Rejected("unknown_slot")
        source: Source = self.source or ("user_said" if slot == "name" or turn.channel == "voice" else "user_typed")
        self._check(slot, op, turn, source)
        stt = 1.0 if turn.confidence is None else turn.confidence
        confidence = min(1.0 if op.confidence is None else op.confidence, stt)
        new = AddFact(
            slot=slot, value=op.value, confidence=confidence, source=source, channel=turn.channel, turn_id=turn.turn_id
        )
        if target is None:
            self._add(index, new)
        else:
            self._update(index, target, new)

    def _check(self, slot: SlotName, op: AddOp | UpdateOp, turn: Turn, source: Source) -> None:
        gate = check_value(slot, op.value, source)
        if not gate.ok:
            raise _Rejected(gate.reason or "gate")
        if slot == "name":
            if not is_confirmed_name(op.value, turn, self.order):
                raise _Rejected("name_unconfirmed")
        elif slot not in _GROUNDING_EXEMPT and not shares_a_word(op.value, visible_text(turn)):
            agents = (visible_text(t) for t in self.order if t.role == "agent")
            raise _Rejected("agent_attributed" if any(shares_a_word(op.value, a) for a in agents) else "ungrounded")
        if op.confidence is not None and op.confidence < MIN_CONFIDENCE:
            raise _Rejected("low_confidence")

    def _add(self, index: int, new: AddFact) -> None:
        same = [e for e in self.live if e.slot == new.slot]
        if any(value_key(e.value) == value_key(new.value) for e in same):
            self.skipped.append(Skip(index=index, reason="duplicate"))
            return
        spec = SLOTS[new.slot]
        if spec.kind == "single":
            for entry in same:
                self._supersede(entry, new)
        else:  # an item is its spellings, at its newest one (as derive_state shows it); the oldest items go
            items: dict[str, None] = {}
            for entry in same:  # stored facts by id, then this batch's
                items.pop(value_key(entry.value), None)
                items[value_key(entry.value)] = None
            gone = set(list(items)[: max(0, len(items) - spec.max_items + 1)])
            for entry in same:
                if value_key(entry.value) in gone:
                    self._supersede(entry, new)
        self._emit(index, new)

    def _update(self, index: int, target: _Live, new: AddFact) -> None:
        if value_key(target.value) == value_key(new.value):
            self.skipped.append(Skip(index=index, reason="duplicate"))
            return
        others = [e for e in self.live if e.slot == new.slot and e is not target]
        if SLOTS[new.slot].kind == "set" and any(value_key(e.value) == value_key(new.value) for e in others):
            assert target.fact_id is not None  # _target only finds stored facts
            self.live.remove(target)  # corrected to an item the set already holds
            self.out.append(InvalidateFact(fact_id=target.fact_id, reason="corrected"))
            return
        self._supersede(target, new)
        if SLOTS[new.slot].kind == "single":
            for entry in others:
                self._supersede(entry, new)
        self._emit(index, new)

    def _supersede(self, entry: _Live, new: AddFact) -> None:
        self.live.remove(entry)
        if entry.fact_id is not None:
            new.supersedes.append(entry.fact_id)
            return
        # An earlier op of this batch: it's never written, and the new fact takes over what it superseded.
        assert entry.pending is not None
        self.out = [op for op in self.out if op is not entry.pending]
        new.supersedes.extend(entry.pending.supersedes)
        self.skipped.append(Skip(index=entry.index, reason="replaced_in_batch"))

    def _emit(self, index: int, new: AddFact) -> None:
        self.out.append(new)
        self.live.append(_Live(slot=new.slot, value=new.value, pending=new, index=index))


def merge(
    store: Store,
    thread_id: str,
    ops: Sequence[Op],
    turn_ids_known: set[str],
    session_id: str,
    *,
    turns: Sequence[Turn] = (),
    extraction: dict[str, Any] | None = None,
    source: Source | None = None,
) -> MergeResult:
    """Decide and apply the extractor's ops in one fenced write. Blocking: call it off the event loop.

    `turn_ids_known` are the user turns the extractor was shown (the ones an op may cite); `turns` is the window in
    order, agent turns included, which the grounding, attribution and name rules read. `extraction`, when given,
    becomes the batch's `extraction_ran` row (with the op counts), committed with the facts. `source` fixes the
    facts' source (B12's rule otherwise)."""
    by_id = {t.turn_id: t for t in turns}
    decisions: list[_Decision] = []

    def decide(valid: list[Fact]) -> list[FactOp]:
        live = [_Live(slot=f.slot, value=f.value, fact_id=f.id) for f in sorted(valid, key=lambda f: f.id)]
        decision = _Decision(turns=by_id, order=list(turns), known=turn_ids_known, live=live, source=source)
        decision.run(ops)
        decisions.append(decision)
        notes: list[FactOp] = [
            Note(type="gate_rejected", payload=r.model_dump(include={"reason", "op", "slot", "turn_id", "fact_id"}))
            for r in decision.rejected
        ]
        if extraction is not None:
            counts = {"ops": len(ops), "rejected": len(decision.rejected), "skipped": len(decision.skipped)}
            counts["applied"] = counts["ops"] - counts["rejected"] - counts["skipped"]
            notes.append(Note(type="extraction_ran", payload={**extraction, **counts}))
        return [*decision.out, *notes]

    if not ops and extraction is None:
        empty: dict[str, list[Any]] = {"added": [], "invalidated": [], "rejected": [], "skipped": []}
        return MergeResult(version=store.version(thread_id), state=store.state(thread_id), **empty)
    applied = store.apply_fact_ops(thread_id, decide, session_id=session_id)
    final = decisions[-1]
    targets: list[int] = []
    for op in final.out:
        if isinstance(op, AddFact):
            targets.extend(op.supersedes)
        elif isinstance(op, InvalidateFact):
            targets.append(op.fact_id)
    return MergeResult(
        version=applied.version,
        added=applied.added,
        invalidated=[i for i in targets if i not in applied.skipped],
        rejected=final.rejected,
        skipped=sorted(final.skipped, key=lambda s: s.index),
        state=store.state(thread_id),
    )

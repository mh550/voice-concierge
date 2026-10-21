"""The merge's result models (plan C4 "The merge"), kept out of `merge.py` for its size; `merge` re-exports them."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from concierge.models import SlotName, VisitorState
from concierge.ops import OpKind


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


class FactChange(BaseModel):
    """A fact this merge added or invalidated, with its value, for this session's event ring (V2-04). In memory only:
    the journal still never holds a value (D8)."""

    kind: Literal["added", "invalidated"]
    slot: SlotName
    value: str


class MergeResult(BaseModel):
    version: int
    added: list[int]
    invalidated: list[int]
    rejected: list[Rejection]
    skipped: list[Skip]
    state: VisitorState
    extraction_ms: float | None = None  # the batch's extraction_ran `ms` (None: no extraction); C6's metrics
    changes: list[FactChange] = []  # the invalidated facts, then the added ones, in op order

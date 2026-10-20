"""The extractor's ops (spec §4.4; plan C4 "The ops").

`OpArg` is the `emit_ops` tool's wire item: flat, every field but `op` nullable, which the strict tool schema handles
best. Internally the ops are discriminated on `op`, each with the fields it needs. Slot names and caps aren't checked
here: an unknown slot or an over-long value reaches the merge, which journals it as `gate_rejected`.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter, ValidationError

from concierge.models import SlotName

OpKind = Literal["ADD", "UPDATE", "DELETE"]
# An enum, never free text, so fact_invalidated never holds the model's words about the visitor (D8).
DeleteReason = Literal["no_longer_true", "asked_to_forget", "corrected"]

_Value = Annotated[str, StringConstraints(strip_whitespace=True)]
_Confidence = Annotated[float, Field(ge=0, le=1)]


class OpArg(BaseModel):
    # One item of emit_ops(ops=[...]) on the wire. The docstring is sent to the model as the item's description.
    """One change to the visitor's memory. Fields the op doesn't use are null."""

    op: OpKind
    slot: SlotName | None = None
    value: str | None = None
    fact_id: int | None = None
    confidence: float | None = None
    turn_id: str | None = None
    reason: DeleteReason | None = None


class AddOp(BaseModel):
    op: Literal["ADD"]
    slot: str
    value: _Value
    turn_id: str
    confidence: _Confidence | None = None
    reason: DeleteReason | None = None


class UpdateOp(BaseModel):
    op: Literal["UPDATE"]
    fact_id: int
    value: _Value
    turn_id: str
    slot: str | None = None  # must equal the target's slot when given
    confidence: _Confidence | None = None
    reason: DeleteReason | None = None


class DeleteOp(BaseModel):
    op: Literal["DELETE"]
    fact_id: int
    reason: DeleteReason | None = None
    turn_id: str | None = None


Op = Annotated[AddOp | UpdateOp | DeleteOp, Field(discriminator="op")]
_OP: TypeAdapter[Op] = TypeAdapter(Op)


class Dropped(BaseModel):
    """A malformed op: its index in `ops` (-1: no ops list at all) and pydantic's error type, never the input."""

    index: int
    error_type: str


class ParsedOps(BaseModel):
    ops: list[Op]
    dropped: list[Dropped]


def parse_ops(json_args: str | dict[str, Any]) -> ParsedOps:
    """Read emit_ops' arguments (the tool call's JSON string, or a dict): each op validated on its own, so one
    malformed op never loses the others. Nulls are dropped first: the strict schema sends every field."""
    try:
        args = json.loads(json_args) if isinstance(json_args, str) else json_args
    except json.JSONDecodeError:
        return ParsedOps(ops=[], dropped=[Dropped(index=-1, error_type="json_invalid")])
    items = args.get("ops") if isinstance(args, dict) else None
    if not isinstance(items, list):
        return ParsedOps(ops=[], dropped=[Dropped(index=-1, error_type="ops_missing")])
    ops: list[Op] = []
    dropped: list[Dropped] = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            item = {k: v for k, v in item.items() if v is not None}
        try:
            ops.append(_OP.validate_python(item))
        except ValidationError as exc:
            dropped.append(Dropped(index=index, error_type=exc.errors()[0]["type"]))
    return ParsedOps(ops=ops, dropped=dropped)

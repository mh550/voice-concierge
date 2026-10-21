"""The memory's data shapes (spec §4.0 "Profile, not collection", §4.2, §6 metrics; plan C2 "Models").

Times are integers of milliseconds since the Unix epoch (UTC). Caps count characters; the 8 KB state cap counts
the bytes of the JSON dump, which is what the `state` table stores.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

SlotName = Literal["name", "role", "company", "follow_up_wanted", "interests", "asked_about"]
Source = Literal["user_said", "user_typed", "user_asked_to_remember"]
Channel = Literal["voice", "text"]
# The §4.2 list, then C5's additions (plan C5). journal.type has no SQL CHECK, so adding a type needs no table rebuild.
JournalType = Literal[
    "session_started", "session_ended", "user_turn", "agent_turn", "memory_preloaded", "extraction_ran",
    "fact_added", "fact_invalidated", "fact_deleted", "turn_metrics", "gate_rejected", "error",
    "summary_written", "compacted", "visitor_left",
]

SINGLE_CAP = 120
SET_ITEM_CAP = 60
SET_MAX_ITEMS = 8
SUMMARY_CAP = 500
STATE_MAX_BYTES = 8192


class SlotSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["single", "set"]
    cap: int
    max_items: int = 1


_SINGLE = SlotSpec(kind="single", cap=SINGLE_CAP)
_SET = SlotSpec(kind="set", cap=SET_ITEM_CAP, max_items=SET_MAX_ITEMS)
SLOTS: dict[SlotName, SlotSpec] = {
    "name": _SINGLE,
    "role": _SINGLE,
    "company": _SINGLE,
    "follow_up_wanted": _SINGLE,
    "interests": _SET,
    "asked_about": _SET,
}


# Control, format (bidi overrides, zero-width), surrogate, private-use, unassigned, line and paragraph separators:
# a memory value is rendered into the prompt as one line of data, and a lone surrogate can't be stored as UTF-8.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def check_value(slot: SlotName, value: str) -> str:
    """A fact value: stripped, non-empty, no unsafe characters, within the slot's cap."""
    value = value.strip()
    if not value:
        raise ValueError("value is empty")
    if any(unicodedata.category(ch) in _UNSAFE_CATEGORIES for ch in value):
        raise ValueError("value contains control, format or line-separator characters")
    if len(value) > SLOTS[slot].cap:
        raise ValueError(f"value is over the {slot} cap of {SLOTS[slot].cap} characters")
    return value


class _SlotValue(BaseModel):
    slot: SlotName
    value: str

    @model_validator(mode="after")
    def _value_fits_slot(self) -> _SlotValue:
        self.value = check_value(self.slot, self.value)
        return self


class Fact(_SlotValue):
    id: int
    thread_id: str
    confidence: float = Field(ge=0, le=1)
    source: Source
    channel: Channel
    turn_id: str
    created_at: int
    valid_from: int
    valid_to: int | None = None
    superseded_by: int | None = None


_Single = Annotated[str, StringConstraints(max_length=SINGLE_CAP)]
_SetItem = Annotated[str, StringConstraints(max_length=SET_ITEM_CAP)]


class VisitorState(BaseModel):
    """The `state` row: derived from valid facts (C2-03), plus C5's last-visit summary."""

    name: _Single | None = None
    role: _Single | None = None
    company: _Single | None = None
    follow_up_wanted: _Single | None = None
    interests: list[_SetItem] = Field(default_factory=list, max_length=SET_MAX_ITEMS)
    asked_about: list[_SetItem] = Field(default_factory=list, max_length=SET_MAX_ITEMS)
    last_visit_summary: Annotated[str, StringConstraints(max_length=SUMMARY_CAP)] | None = None

    @model_validator(mode="after")
    def _under_8_kib(self) -> VisitorState:
        # Caps count characters, JSON counts bytes: escaped control characters can still overflow.
        size = len(self.model_dump_json().encode())
        if size >= STATE_MAX_BYTES:
            raise ValueError(f"state JSON is {size} bytes; it must be under {STATE_MAX_BYTES}")
        return self


class AddFact(_SlotValue):
    op: Literal["add"] = "add"
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: Source
    channel: Channel
    turn_id: str
    supersedes: list[int] = Field(default_factory=list)

    @field_validator("supersedes")
    @classmethod
    def _once_each(cls, ids: list[int]) -> list[int]:
        return list(dict.fromkeys(ids))  # a repeat would invalidate once, then report itself skipped


InvalidateReason = Literal["no_longer_true", "asked_to_forget", "corrected", "unspecified"]


class InvalidateFact(BaseModel):
    op: Literal["invalidate"] = "invalidate"
    fact_id: int
    superseded_by: int | None = None
    reason: InvalidateReason | None = None  # journaled in fact_invalidated: an enum, never free text (D8)


class DeleteFact(BaseModel):
    op: Literal["delete"] = "delete"
    fact_id: int


class Note(BaseModel):
    """A journal row that commits with the batch (C4: gate_rejected, extraction_ran). Ids and reasons only."""

    op: Literal["note"] = "note"
    type: JournalType
    payload: dict[str, Any]


FactOp = Annotated[AddFact | InvalidateFact | DeleteFact | Note, Field(discriminator="op")]


class ApplyResult(BaseModel):
    version: int
    added: list[int]
    skipped: list[int]
    deleted: list[int]  # really deleted rows: their values leave the disk at the WAL checkpoint after the commit


class Thread(BaseModel):
    id: str
    visitor_id: str
    created_at: int
    last_active_at: int
    idle_ttl_s: int
    visits: int
    version: int


class ThreadSnapshot(BaseModel):
    """What the preload reads in one transaction (`Store.load`): the version, the state row and the valid facts."""

    version: int
    state: VisitorState
    facts: list[Fact]


class VisitEpisode(BaseModel):
    """A `visit_summaries` row (V2-03): one visit, open until its session's summary step ends it."""

    visit: int
    started_at: int
    ended_at: int | None
    summary: str | None


class JournalRow(BaseModel):
    id: int
    thread_id: str
    session_id: str
    ts_ms: int
    type: JournalType
    payload: dict[str, Any]


class TurnMetrics(BaseModel):
    """The §6 `concierge.metrics` fields exactly; `extra="forbid"` keeps text and ids out of the anonymous table."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    turn: int = Field(ge=1)
    eou_ms: float | None = Field(default=None, ge=0)
    stt_ms: float | None = Field(default=None, ge=0)
    llm_ttft_ms: float | None = Field(default=None, ge=0)
    tts_ttfb_ms: float | None = Field(default=None, ge=0)
    total_ms: float | None = Field(default=None, ge=0)
    memory_on_turn_path_ms: float | None = Field(default=None, ge=0)
    preload_ms: float | None = Field(default=None, ge=0)
    extraction_ms: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    compacted: bool = False


class Message(BaseModel):
    """A `messages_for_michael` row (spec §4.6, C8): what `scripts/messages.py` lists."""

    id: int
    thread_id: str
    text: str
    contact: str | None
    created_at: int

"""The eval script format (spec §4.9; plan C4 "The YAML schema"): one evals/memory/*.yaml file is one visitor's visits,
the facts that must and must never be stored, and the emit_ops arguments the offline twin replays.

The live eval (C7) reads the same files and ignores `recorded_ops`. Turn ids are the runner's, `v<visit>-t<index>`
(both 1-based), so recorded ops can cite them; fact ids are the temp store's (AUTOINCREMENT from 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from concierge.models import Channel, SlotName


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScriptTurn(_Strict):
    role: Literal["user", "agent"]
    text: str = Field(min_length=1)
    channel: Channel = "voice"  # user turns: the door; agent turns are always voice
    interrupted_heard: str | None = None  # agent turns: cut off after this much was heard ("" = nothing heard)
    confidence: float | None = Field(default=None, ge=0, le=1)  # user turns: the STT's transcript confidence

    @model_validator(mode="after")
    def _role_fields(self) -> ScriptTurn:
        if self.role == "agent" and (self.channel != "voice" or self.confidence is not None):
            raise ValueError("an agent turn is voice and has no transcript confidence")
        if self.role == "user" and self.interrupted_heard is not None:
            raise ValueError("only an agent turn can be interrupted")
        return self


class ExpectedFact(_Strict):
    slot: SlotName
    value: str = Field(min_length=1)
    also: list[str] = []  # other spellings that count (a live extractor's wording: "product manager" for "PM")


class GoneFact(_Strict):
    slot: SlotName
    value: str = Field(min_length=1)


class ForbiddenFact(_Strict):
    slot: SlotName | None = None  # None: any slot
    value_contains: str = Field(min_length=1)


class RecordedReply(_Strict):
    """What the fake extractor LLM replies for one visit: an emit_ops call with these ops, or text (zero ops)."""

    ops: list[dict[str, Any]] | None = None
    text: str | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> RecordedReply:
        if (self.ops is None) == (self.text is None):
            raise ValueError("a recorded reply has exactly one of ops or text")
        return self


class MemoryScript(_Strict):
    name: str
    about: str | None = None  # one line, for the report
    visits: list[list[ScriptTurn]] = Field(min_length=1)
    expected: list[ExpectedFact]  # valid at the end
    forbidden: list[ForbiddenFact]  # never stored, valid or not
    gone: list[GoneFact] = []  # stored, then removed: in the history, not valid at the end
    nothing_stored: bool = False  # no valid fact at the end
    recorded_ops: list[RecordedReply]  # one per visit

    @model_validator(mode="after")
    def _one_reply_per_visit(self) -> MemoryScript:
        if any(not visit for visit in self.visits):
            raise ValueError("a visit has at least one turn")
        if len(self.recorded_ops) != len(self.visits):
            raise ValueError(f"{len(self.visits)} visits need {len(self.visits)} recorded_ops entries")
        return self


def load_script(path: Path) -> MemoryScript:
    """Read and validate one script; its name must be the file's stem."""
    script = MemoryScript.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if script.name != path.stem:
        raise ValueError(f"script name {script.name!r} is not the file's stem {path.stem!r}")
    return script

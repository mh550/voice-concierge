"""This session's memory events (spec 2026-10-21 §2 `about_visitor.events`; plan V2 "Events (V2-04)", D17 (a)).

A ring of at most 12 plain lines, newest first, fed off the turn path: the session's `on_merged` (the writer's
background run) and the `remember` / `forget` tools. A line may show a visitor's value ("Remembered your role:
engineer") but never instruction-like or URL text: every detail must pass `check_text` and fit in 120 characters, else
the type's value-free form is used. A gate rejection never carries the value. A line keeps the value it shows, and
every body checks it against the store on the writer's thread (`shown`): a forgotten value goes out in no body, even one
whose lines were read before the forget ran. In memory only; `clear` on "Forget me".
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from concierge.contract import MAX_EVENTS, EventType, MemoryEvent, iso_utc
from concierge.fact_ops import value_key
from concierge.gate import check_text
from concierge.merge_result import MergeResult
from concierge.models import SlotName
from concierge.store import now_ms

MAX_DETAIL = 120  # MemoryEvent.detail's max_length

# The value-free form of each type: the fallback when a line would carry text the page mustn't show.
PLAIN: dict[EventType, str] = {
    "fact_added": "Remembered something about you",
    "fact_invalidated": "Updated something about you",
    "fact_deleted": "Forgot something about you",
    "gate_rejected": "Didn't store something",
    "extraction_ran": "Took notes in the background",
    "remember": "Remembered something at your request",
    "forget": "Forgot something at your request",
}
# "your <slot>", except asked_about, which reads "what you asked about".
_YOUR: dict[SlotName, str] = {
    "name": "your name",
    "role": "your role",
    "company": "your company",
    "interests": "your interest",
    "asked_about": "what you asked about",
    "follow_up_wanted": "your follow-up",
}
_WORD: dict[SlotName, str] = {s: w.removeprefix("your ") for s, w in _YOUR.items()}
# The gate reasons a visitor can act on (D17 (a)); the model's own mistakes get no line.
_LOOKED_LIKE: dict[str, str] = {
    "instruction": "an instruction",
    "url": "a link",
    "email": "contact details",
    "phone": "contact details",
    "secret": "a secret",
    "code": "code",
}


def _safe(line: str, plain: str) -> str:
    return line if len(line) <= MAX_DETAIL and check_text(line).ok else plain


def fact_added(slot: SlotName, value: str) -> str:
    return _safe(f"Remembered {_YOUR[slot]}: {' '.join(value.split())}", f"Remembered {_YOUR[slot]}")


def fact_invalidated(slot: SlotName) -> str:
    return f"Updated {_YOUR[slot]}"


def fact_deleted(slot: SlotName) -> str:
    return f"Forgot {_YOUR[slot]}"


def gate_rejected(reason: str) -> str | None:
    """Never the value: only what it looked like. None for a reason that gets no line."""
    looked = _LOOKED_LIKE.get(reason)
    return None if looked is None else f"Didn't store something that looked like {looked}"


def extraction_ran(changes: int) -> str:
    return f"Took notes in the background ({changes} change{'' if changes == 1 else 's'})"


def remember(slot: SlotName) -> str:
    return f"Remembered at your request: {_WORD[slot]}"


def forget(about: str) -> str:
    return _safe(f"Forgot at your request: {' '.join(about.split())}", PLAIN["forget"])


def forgot_slot(slot: SlotName) -> str:
    """The `forget` tool's line: the slot's word, never the visitor's own words, which can hold a value (D17 (l))."""
    return forget(_WORD[slot])


@dataclass(frozen=True)
class Line:
    """One noted event and, for a line that shows a visitor's value, that value and the line without it."""

    event: MemoryEvent
    value: str | None = None
    plain: str | None = None


def shown(lines: Iterable[Line], stored: set[str]) -> list[MemoryEvent]:
    """The events as the page may see them: a line whose value is no longer in `stored` (the `value_key`s of the
    thread's fact history; forgotten here or in another session, D17 (l)) shows its value-free form."""
    return [line.event if line.value is None or value_key(line.value) in stored
            else line.event.model_copy(update={"detail": line.plain}) for line in lines]


class EventRing:
    """The newest `max_items` events of one session. Sync and in memory: call it on the event loop only."""

    def __init__(self, max_items: int = MAX_EVENTS, clock: Callable[[], int] = now_ms) -> None:
        self._lines: deque[Line] = deque(maxlen=max_items)
        self._clock = clock

    def note(self, type: EventType, detail: str) -> None:  # noqa: A002 (§2's name)
        """One line, which falls back to the type's value-free form if it fails `check_text` or the cap."""
        self._append(type, detail, None, PLAIN[type])

    def note_merge(self, result: MergeResult) -> None:
        """A background run's merge, oldest first so the list reads newest first: `extraction_ran` (only when the
        run changed something or a rejection gets a line, D17 (d)), the gate rejections, the invalidated facts, then
        the added ones (each keeps its value, for `shown`)."""
        rejected = [line for r in result.rejected if (line := gate_rejected(r.reason)) is not None]
        if not result.changes and not rejected:
            return
        self.note("extraction_ran", extraction_ran(len(result.changes)))
        for line in rejected:
            self.note("gate_rejected", line)
        for change in result.changes:
            if change.kind == "invalidated":
                self.note("fact_invalidated", fact_invalidated(change.slot))
        for change in result.changes:
            if change.kind == "added":
                plain = f"Remembered {_YOUR[change.slot]}"
                self._append("fact_added", fact_added(change.slot, change.value), change.value, plain)

    def _append(self, type: EventType, detail: str, value: str | None, plain: str) -> None:  # noqa: A002
        line = _safe(" ".join(detail.split()), plain)
        event = MemoryEvent(ts=iso_utc(self._clock()), type=type, detail=line)
        self._lines.append(Line(event, value if line != plain else None, plain))

    def lines(self) -> list[Line]:
        """Newest first: a snapshot to take on the event loop and hand to `shown` on the writer's thread."""
        return list(reversed(self._lines))

    def items(self) -> list[MemoryEvent]:
        return [line.event for line in self.lines()]

    def clear(self) -> None:
        self._lines.clear()

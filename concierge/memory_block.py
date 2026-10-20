"""The memory block: what a returning visitor told us, rendered as quoted data under MEMORY_HEADER (spec §4.0
"Context is a budget", "Memory as an attack surface"; plan C3 "The memory block").

Lines come from the derived `VisitorState` (the store applies ops literally, so a slot can hold several valid facts),
and each takes its channel and day from the newest valid fact behind it. Every value is a JSON string, so it can't
close its own quotes, and `check_value` already keeps line breaks out of fact values.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

from concierge.fact_ops import value_key
from concierge.models import _UNSAFE_CATEGORIES, SLOTS, Fact, VisitorState
from concierge.prompt import MEMORY_BLOCK_MAX_CHARS, MEMORY_HEADER

_ELLIPSIS = "…"


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _line(f: Fact) -> str:
    day = datetime.fromtimestamp(f.valid_from / 1000, tz=UTC).strftime("%Y-%m-%d")
    return f"- {f.slot}: {_quoted(f.value)} ({f.channel}, {day})"


def _newest(facts: list[Fact], slot: str, value: str) -> Fact | None:
    """The newest valid fact (highest id) of `slot` whose value is `value`, compared the way derive_state keys it."""
    matches = [f for f in facts if f.slot == slot and value_key(f.value) == value_key(value)]
    return matches[-1] if matches else None


def _clean(summary: str | None) -> str | None:
    """The LLM-written summary with unsafe characters (line separators, bidi overrides) turned into spaces."""
    if summary is None:
        return None
    text = "".join(" " if unicodedata.category(ch) in _UNSAFE_CATEGORIES else ch for ch in summary).strip()
    return text or None


def _render(singles: list[Fact], set_items: list[Fact], summary: str | None) -> str:
    order = list(SLOTS)
    ordered = sorted(set_items, key=lambda f: (order.index(f.slot), f.id))
    lines = [MEMORY_HEADER, *map(_line, singles), *map(_line, ordered)]
    if summary is not None:
        lines.append(f"Last visit: {_quoted(summary)}")
    return "\n".join(lines)


def _shortened(summary: str, fits: Callable[[str], bool]) -> str | None:
    """The longest prefix of the summary, cut back to a space, that fits with an ellipsis; None if no word fits."""
    for cut in sorted((i for i, ch in enumerate(summary) if ch == " "), reverse=True):
        candidate = summary[:cut].rstrip() + _ELLIPSIS
        if candidate != _ELLIPSIS and fits(candidate):
            return candidate
    return None


def render_memory_block(state: VisitorState, facts: list[Fact]) -> str | None:
    """The block for a returning visitor, or None when there is nothing to recall. Always at most
    MEMORY_BLOCK_MAX_CHARS: set items go first (oldest first), then the summary is shortened, then dropped."""
    valid = sorted((f for f in facts if f.valid_to is None), key=lambda f: f.id)
    singles: list[Fact] = []
    set_items: list[Fact] = []
    for slot, spec in SLOTS.items():
        value = getattr(state, slot)
        values = ([value] if value is not None else []) if spec.kind == "single" else value
        for v in values:
            found = _newest(valid, slot, v)
            if found is not None:  # a state value with no valid fact behind it is never rendered
                (singles if spec.kind == "single" else set_items).append(found)
    summary = _clean(state.last_visit_summary)
    if not singles and not set_items and summary is None:
        return None

    def fits(s: str | None) -> bool:
        return len(_render(singles, set_items, s)) <= MEMORY_BLOCK_MAX_CHARS

    set_items.sort(key=lambda f: f.id)
    while set_items and not fits(summary):
        set_items.pop(0)  # the oldest set item, across both sets
    if summary is not None and not fits(summary):
        summary = _shortened(summary, fits)
    block = _render(singles, set_items, summary)
    # Single lines are validated fact values (at most 4 x 120 characters), so this holds; kept as the guarantee.
    return block if len(block) <= MEMORY_BLOCK_MAX_CHARS else None

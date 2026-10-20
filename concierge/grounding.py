"""Whose words a value is (D10 *default*, B12; plan C4 "The merge", steps 4 and 5).

A turn id is only a pointer the model chooses. These checks read the cited turn's visible text: a value must share
a word with it, and a name counts only when the visitor said yes to the agent's "did I get that right" with it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from concierge.turns import Turn, visible_text

_STOP = frozenset(
    "the and or but of to in on at for with from by about as is are was were be been am me my you your he his she "
    "her it its we our they them this that what who how do does did have has had not so just can will would "
    "an us no up if oh ok hi".split()
)
_YES = re.compile(r"^\W*(yes|yeah|yep|yup|correct|right|that's right|exactly|uh-huh)\b")
_TAKEN_BACK = re.compile(r"\b(no|not|nope|actually|but|wait)\b")
CONFIRM_QUESTION = "did i get that right"
# The prompt's exact form (STATIC_INSTRUCTIONS): "Did I get that right, <name>?". The name is what follows the comma.
_ASKED_NAME = re.compile(r"\bdid i get that right,\s*([^?.!,]+)")


def words(text: str) -> set[str]:
    """Casefolded tokens without punctuation, a trailing "s" dropped, stop words and single letters left out. A
    two-letter token ("PM", "AI") still counts, but only as a whole token."""
    out: set[str] = set()
    for token in re.findall(r"[^\W_]+", text.casefold()):
        if token in _STOP:
            continue
        if len(token) >= 3 and token.endswith("s"):
            token = token[:-1]
        if len(token) >= 2 and token not in _STOP:
            out.add(token)
    return out


def shares_a_word(value: str, text: str) -> bool:
    return bool(words(value) & words(text))


def _plain(text: str) -> str:
    return " ".join(text.casefold().replace("’", "'").split())


def is_confirmed_name(value: str, turn: Turn, order: Sequence[Turn]) -> bool:
    """`turn` is a user turn saying yes (and not taking it back), directly after an agent turn whose heard text
    asked "did I get that right, <value>?" in the prompt's form, with exactly this value."""
    position = next((i for i, t in enumerate(order) if t.turn_id == turn.turn_id), 0)
    if position == 0 or turn.role != "user":
        return False
    asked = order[position - 1]
    if asked.role != "agent":
        return False
    names = [m.group(1).strip() for m in _ASKED_NAME.finditer(_plain(visible_text(asked)))]
    reply = _plain(visible_text(turn))
    return _plain(value) in names and _YES.match(reply) is not None and _TAKEN_BACK.search(reply) is None

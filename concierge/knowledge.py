"""The knowledge pack (spec §4.1): the only source of facts about Michael, static so it sits in the cached prefix."""

from functools import cache
from pathlib import Path

# Resolved from this file, not the cwd, so the worker finds the pack wherever it is started.
PACK_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "michael.md"


@cache
def load_pack() -> str:
    """The pack's text, read once per process (it never changes during a session)."""
    return PACK_PATH.read_text(encoding="utf-8")


def pack_word_count() -> int:
    """Words as `wc -w` counts them: runs of non-whitespace."""
    return len(load_pack().split())

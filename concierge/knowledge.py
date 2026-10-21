"""The knowledge pack (spec §4.1): the only source of facts about Michael, static so it sits in the cached prefix.

`pack_stats` is what `concierge.memory`'s `about_agent.knowledge` reports about it (spec 2026-10-21 §2).
"""

import re
from functools import cache
from pathlib import Path

from concierge.contract import Knowledge
from concierge.prompt import estimate_tokens

# Resolved from this file, not the cwd, so the worker finds the pack wherever it is started.
PACK_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "michael.md"
SOURCE_MD_PATH = PACK_PATH.parent / "sources" / "SOURCE.md"  # names the portfolio commit the sources were copied at

_COMMIT = re.compile(r"commit `([0-9a-f]{7,40})`")  # as SOURCE.md records it: at commit `81bb0fc`


@cache
def load_pack() -> str:
    """The pack's text, read once per process (it never changes during a session)."""
    return PACK_PATH.read_text(encoding="utf-8")


def pack_word_count() -> int:
    """Words as `wc -w` counts them: runs of non-whitespace."""
    return len(load_pack().split())


def sources_commit(source_md: str) -> str:
    """The first 7+ hex commit `SOURCE.md` names, or "unknown" (the page shows it; a missing one never costs a send)."""
    found = _COMMIT.search(source_md)
    return found.group(1) if found else "unknown"


def _source_md() -> str:
    try:
        return SOURCE_MD_PATH.read_text(encoding="utf-8")
    except OSError:  # a deployed tree without it still reports the pack (D18 (b))
        return ""


@cache
def pack_stats() -> Knowledge:
    """The pack's size, its sources' commit and its `## ` section titles in order; read once per process."""
    pack = load_pack()
    return Knowledge(
        words=pack_word_count(),
        est_tokens=estimate_tokens(pack),
        sources_commit=sources_commit(_source_md()),
        sections=[line[3:].strip() for line in pack.splitlines() if line.startswith("## ")],
    )

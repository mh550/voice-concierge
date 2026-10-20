"""Print p50/p95 per latency field and the cached-token share (spec §4.7; plan C7 "scripts/latency_report.py").

    python scripts/latency_report.py <db>

A markdown table, `| field | n | p50 | p95 |`, in the shape of the README's Results section: one row per field of
`anonymous_turn_metrics` (each over its non-null values only: text turns have no eou/stt, preload_ms is set on a
session's first turn, extraction_ms after a merge), then the cached-token share, sum(cached_tokens) /
sum(prompt_tokens) over the rows that have both. Percentiles interpolate linearly between closest ranks (numpy's
default). The rows are numbers only (B9), so the output holds no visitor data. The db is opened read-only. Exit 2:
usage, no such file, or not a memory store; otherwise 0, even with no rows (every cell `n/a`).
"""

from __future__ import annotations

import math
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from concierge.models import TurnMetrics
from concierge.store import Store, StoreError

FIELDS = ("eou_ms", "stt_ms", "llm_ttft_ms", "tts_ttfb_ms", "total_ms", "memory_on_turn_path_ms", "preload_ms",
          "extraction_ms")


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th percentile (0-100) of non-empty `values`, linear between closest ranks."""
    ordered = sorted(values)
    k = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def report(rows: Sequence[TurnMetrics]) -> list[str]:
    lines = ["| field | n | p50 | p95 |", "|---|---|---|---|"]
    for field in FIELDS:
        values = [v for r in rows if (v := getattr(r, field)) is not None]
        if values:
            lines.append(f"| {field} | n={len(values)} | {percentile(values, 50):.1f} | {percentile(values, 95):.1f} |")
        else:
            lines.append(f"| {field} | n=0 | n/a | n/a |")
    both = [r for r in rows if r.prompt_tokens is not None and r.cached_tokens is not None]
    prompt = sum(r.prompt_tokens or 0 for r in both)
    share = f"{100 * sum(r.cached_tokens or 0 for r in both) / prompt:.1f} %" if prompt else "n/a"
    lines.append(f"| cached-token share | n={len(both)} | {share} | |")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: latency_report.py <db>", file=sys.stderr)
        return 2
    db = Path(argv[0])
    if not db.is_file():
        print(f"no database at {db}", file=sys.stderr)
        return 2
    try:
        with Store.open_readonly(db) as store:
            rows = store.turn_metrics()
    except (StoreError, sqlite3.DatabaseError, ValidationError) as exc:
        print(f"not a memory store: {db} ({type(exc).__name__})", file=sys.stderr)
        return 2
    print("\n".join(report(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

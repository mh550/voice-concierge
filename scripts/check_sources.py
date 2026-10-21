"""Report which vendored source files drifted from the portfolio repo's main (plan V3 "The drift check", D22).

    python scripts/check_sources.py [--fetched DIR] [--sources DIR]

`--sources`: the vendored files, default `knowledge/sources` in this repo. `--fetched`: a flat directory holding the
five upstream files by base name, without header lines; without it the five are downloaded from `RAW` (the network is
used only then, all of it in `fetch`). Prints `sources commit: <hex>` (from SOURCE.md), then `drifted: <name>` per
drifted file or `clean: 5 files match main`. Exit 0 clean, 1 drift, 2 a fetch failed or a file is missing (the reason
on stderr). It never writes into the sources: re-vendoring stays the manual procedure in the V3 plan.
"""

from __future__ import annotations

import argparse
import http.client
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

from concierge.knowledge import sources_commit

ROOT = Path(__file__).resolve().parent.parent
RAW = "https://raw.githubusercontent.com/mh550/portfolio_site/main/"
REMOTE_PATHS = {
    "Bio.md": "Bio.md",
    "profile.ts": "src/lib/data/profile.ts",
    "experience.ts": "src/lib/data/experience.ts",
    "projects.ts": "src/lib/data/projects.ts",
    "skills.ts": "src/lib/data/skills.ts",
}
TIMEOUT_S = 10
# The one header line V3-02 put first in each vendored file (the same regex as tests/test_knowledge.py).
HEADER = re.compile(rb"^(?://|<!--) vendored from mh550/portfolio_site@([0-9a-f]{7,40}) (\S+)(?: -->)?$")


class FetchError(Exception):
    """One upstream file could not be downloaded."""


def _body(path: Path) -> bytes:
    """The file's bytes without its header line (LF or CRLF); a file without one is compared whole."""
    data = path.read_bytes()
    first, sep, rest = data.partition(b"\n")
    return rest if sep and HEADER.match(first.removesuffix(b"\r")) else data


def diff_sources(local: Path, fetched: Path) -> list[str]:
    """The names, in `REMOTE_PATHS` order, whose local body differs from the fetched file. A missing file raises
    `FileNotFoundError` naming it."""
    drifted = []
    for name in REMOTE_PATHS:
        for side in (local, fetched):
            if not (side / name).is_file():
                raise FileNotFoundError(name)
        if _body(local / name) != (fetched / name).read_bytes():
            drifted.append(name)
    return drifted


def fetch(dest: Path) -> None:
    """Download the five upstream files into `dest`, by base name."""
    for name, path in REMOTE_PATHS.items():
        # URLError (HTTPError too) and TimeoutError are OSErrors; IncompleteRead and the like are HTTPExceptions.
        try:
            with urllib.request.urlopen(RAW + path, timeout=TIMEOUT_S) as response:
                if response.status != 200:
                    raise FetchError(f"{name}: HTTP {response.status}")
                (dest / name).write_bytes(response.read())
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError(f"{name}: {exc}") from exc


def _report(sources: Path, fetched: Path) -> int:
    try:
        drifted = diff_sources(sources, fetched)
    except FileNotFoundError as exc:
        print(f"missing: {exc.args[0]}", file=sys.stderr)
        return 2
    for name in drifted:
        print(f"drifted: {name}")
    if not drifted:
        print(f"clean: {len(REMOTE_PATHS)} files match main")
    return 1 if drifted else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report vendored source files that drifted from the portfolio repo.")
    parser.add_argument("--fetched", type=Path, help="a directory holding the five upstream files (no download)")
    parser.add_argument("--sources", type=Path, default=ROOT / "knowledge" / "sources", help="the vendored files")
    args = parser.parse_args(argv)

    source_md = args.sources / "SOURCE.md"
    commit = sources_commit(source_md.read_text(encoding="utf-8")) if source_md.is_file() else "unknown"
    print(f"sources commit: {commit}")
    if args.fetched is not None:
        return _report(args.sources, args.fetched)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            fetch(Path(tmp))
        except FetchError as exc:
            print(f"fetch failed: {exc}", file=sys.stderr)
            return 2
        return _report(args.sources, Path(tmp))


if __name__ == "__main__":
    sys.exit(main())

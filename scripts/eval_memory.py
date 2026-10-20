"""Run the memory evals through the real extractor and merge (spec §4.9; plan C7 "scripts/eval_memory.py").

    python scripts/eval_memory.py [--offline] [--case NAME]... [--dir DIR]

Every `*.yaml` in DIR (default `evals/memory`), in name order, goes through `concierge.evals.runner.run_script`:
the real Turn building, extract() and merge() on a temp Store. Live (the default), the extractor is
`build_llm("extractor")`, the configured provider and model, and the script's recorded_ops are ignored; it needs
ANTHROPIC_API_KEY (OPENROUTER_API_KEY under CONCIERGE_LLM_PROVIDER=openrouter) in the process environment and exits 2
naming it when unset. `--offline` replays the recorded_ops instead, like tests/test_memory_evals_offline.py.

Prints a markdown table: case, recall (expected facts valid at the end; `n/a` when a case expects none) and harm hits
(forbidden, duplicate, gone-but-valid and stored-when-nothing-should-be), then a total row. Exit 0 with no harm hit,
1 with any (a recall miss is reported, not failed: the live extractor can miss things), 2 on usage or a missing key.
A provider error (a 400, a refusal, a timeout) prints `error` for that case and counts as one harm hit; the run goes
on.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml
from livekit.agents import APIError
from pydantic import ValidationError

from concierge.config import LLM_KEY, Settings, build_llm
from concierge.evals.runner import LLMFactory, ScriptResult, run_script
from concierge.evals.script import MemoryScript, load_script
from concierge.testing.replay import Replay

EVALS = Path(__file__).resolve().parent.parent / "evals" / "memory"


def recall_cell(hit: int, total: int) -> str:
    # Rounded down, so 100 % means every expected fact was there.
    return f"{hit}/{total} ({100 * hit // total} %)" if total else "n/a"


def harm_cell(hits: list[str]) -> str:
    return f"{len(hits)}: {'; '.join(hits)}".replace("|", "\\|") if hits else "0"


async def run_all(scripts: list[MemoryScript], live: Settings | None) -> int:
    print("| case | recall | harm hits |\n|---|---|---|")
    hit_total = expected_total = harm_total = 0
    extractor = build_llm("extractor", live) if live is not None else None
    try:
        for script in scripts:
            factory: LLMFactory = Replay(script) if extractor is None else (lambda n: extractor)
            expected = len(script.expected)
            expected_total += expected
            try:
                result: ScriptResult = await run_script(script, factory)
            except (APIError, TimeoutError) as exc:  # a 400, a refusal or a timeout is this case's row, counted as harm
                harm_total += 1
                print(f"| {script.name} | error | 1: {type(exc).__name__} |")
                continue
            hit = expected - len(result.missing_expected)
            hit_total += hit
            harm_total += len(result.forbidden_hits)
            print(f"| {script.name} | {recall_cell(hit, expected)} | {harm_cell(result.forbidden_hits)} |")
    finally:
        if extractor is not None:  # run_script doesn't close the factory's LLM
            await extractor.aclose()
    print(f"| total | {recall_cell(hit_total, expected_total)} | {harm_total} |")
    return 1 if harm_total else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="eval_memory.py", description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="replay the scripts' recorded_ops; no key needed")
    parser.add_argument("--case", action="append", default=[], metavar="NAME", help="run only this case (repeatable)")
    parser.add_argument("--dir", type=Path, default=EVALS, help="the eval scripts' directory")
    args = parser.parse_args(argv)  # a usage error exits 2

    paths = sorted(args.dir.glob("*.yaml"))
    unknown = sorted(set(args.case) - {p.stem for p in paths})
    if not paths or unknown:
        print(f"no such case in {args.dir}: {', '.join(unknown) or '*.yaml'}", file=sys.stderr)
        return 2
    try:
        scripts = [load_script(p) for p in paths if not args.case or p.stem in args.case]
    except (ValueError, OSError, yaml.YAMLError) as exc:  # pydantic's ValidationError is a ValueError
        print(f"bad eval script: {exc}", file=sys.stderr)
        return 2

    live: Settings | None = None
    if not args.offline:
        try:
            live = Settings()
        except ValidationError as exc:
            print(f"bad CONCIERGE_ setting: {exc.errors()[0]['loc']}", file=sys.stderr)
            return 2
        key = LLM_KEY[live.llm_provider]
        if not os.environ.get(key):
            print(f"{key} not set", file=sys.stderr)
            return 2
    return asyncio.run(run_all(scripts, live))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

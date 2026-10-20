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
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from livekit.agents import llm
from pydantic import ValidationError

from concierge.config import Settings, build_llm
from concierge.evals.runner import LLMFactory, ScriptResult, run_script
from concierge.evals.script import MemoryScript, load_script
from concierge.testing.replay import Replay

EVALS = Path(__file__).resolve().parent.parent / "evals" / "memory"
KEY_FOR_PROVIDER = {"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def recall_cell(hit: int, total: int) -> str:
    # Rounded down, so 100 % means every expected fact was there.
    return f"{hit}/{total} ({100 * hit // total} %)" if total else "n/a"


def harm_cell(hits: list[str]) -> str:
    return f"{len(hits)}: {'; '.join(hits)}".replace("|", "\\|") if hits else "0"


async def run_all(scripts: list[MemoryScript], live: Settings | None) -> int:
    print("| case | recall | harm hits |\n|---|---|---|")
    hit_total = expected_total = harm_total = 0
    for script in scripts:
        built: list[llm.LLM] = []
        factory: LLMFactory
        if live is None:
            factory = Replay(script)
        else:
            def factory(n: int, settings: Settings = live, built: list[llm.LLM] = built) -> llm.LLM:
                built.append(build_llm("extractor", settings))
                return built[-1]
        try:
            result: ScriptResult = await run_script(script, factory)
        finally:
            for made in built:  # run_script doesn't close the factory's LLMs
                await made.aclose()
        expected = len(script.expected)
        hit = expected - len(result.missing_expected)
        hit_total, expected_total = hit_total + hit, expected_total + expected
        harm_total += len(result.forbidden_hits)
        print(f"| {script.name} | {recall_cell(hit, expected)} | {harm_cell(result.forbidden_hits)} |")
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
    except (ValueError, OSError) as exc:  # pydantic's ValidationError is a ValueError
        print(f"bad eval script: {exc}", file=sys.stderr)
        return 2

    live: Settings | None = None
    if not args.offline:
        try:
            live = Settings()
        except ValidationError as exc:
            print(f"bad CONCIERGE_ setting: {exc.errors()[0]['loc']}", file=sys.stderr)
            return 2
        key = KEY_FOR_PROVIDER[live.llm_provider]
        if not os.environ.get(key):
            print(f"{key} not set", file=sys.stderr)
            return 2
    return asyncio.run(run_all(scripts, live))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

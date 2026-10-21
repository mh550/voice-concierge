"""Run the conversation evals through the production agent's text path (spec 2026-10-21 §6; plan V4).

    python scripts/eval_conversation.py [--offline] [--case NAME]... [--dir DIR]

Every `*.yaml` in DIR (default `evals/conversation`), in name order, goes through
`concierge.evals.conversation.run_conversation`: the real ConciergeAgent (its instructions, Michael's description and
its tools) on a real AgentSession, one `session.run(user_input=...)` per visitor turn, no room, STT, TTS or Store.
Live (the default, the llm tier: Michael runs it) the LLM is `build_llm("conversation")`, the configured provider and
model, shared by every script; it needs ANTHROPIC_API_KEY (OPENROUTER_API_KEY under CONCIERGE_LLM_PROVIDER=openrouter)
in the process environment and exits 2 naming it when unset. `--offline` replays each turn's fake_reply or
fake_tool_call through FakeLLM instead, like tests/test_conversation_evals_offline.py.

Prints a markdown table, one row per turn: script, turn, pass or fail, the failing assertions and the reply; then a
total row. Exit 0 when every script passes, 1 when any fails, 2 on usage, a bad script or a missing key. A timeout or
provider error fails that turn and ends its script (the runner's `error:` failure); the other scripts still run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml
from livekit.agents import llm
from pydantic import ValidationError

from concierge.config import LLM_KEY, Settings, build_llm
from concierge.evals.conversation import (
    ConversationResult,
    ConversationScript,
    load_conversation,
    offline_llm,
    run_conversation,
)

EVALS = Path(__file__).resolve().parent.parent / "evals" / "conversation"
HEADER = "| script | turn | result | failing assertion | reply |\n|---|---|---|---|---|"


def cell(text: str) -> str:
    """One table cell: whitespace (newlines too) collapsed, "|" escaped."""
    return " ".join(text.split()).replace("|", "\\|")


def rows(result: ConversationResult) -> list[str]:
    return [f"| {result.name} | {t.turn} | {'fail' if t.failures else 'pass'} | {cell('; '.join(t.failures))} "
            f"| {cell(t.reply)} |" for t in result.turns]


async def run_one(script: ConversationScript, shared: llm.LLM | None) -> ConversationResult:
    if shared is not None:
        return await run_conversation(script, lambda: shared)
    fake = offline_llm(script)
    try:
        return await run_conversation(script, lambda: fake)
    finally:
        await fake.aclose()


async def run_all(scripts: list[ConversationScript], live: Settings | None) -> int:
    print(HEADER)
    failed: list[str] = []
    turns = 0
    shared = build_llm("conversation", live) if live is not None else None
    try:
        for script in scripts:
            try:
                result = await run_one(script, shared)
            except Exception as exc:  # a session that won't start: this script's row, and the others still run
                failed.append(script.name)
                print(f"| {script.name} | - | fail | {cell(f'error: {type(exc).__name__}: {exc}')} | |")
                continue
            turns += len(result.turns)
            if not result.passed:
                failed.append(script.name)
            print("\n".join(rows(result)))
    finally:
        if shared is not None:  # run_conversation doesn't close the factory's LLM
            await shared.aclose()
    passed = len(scripts) - len(failed)
    note = f"failed: {', '.join(failed)}" if failed else ""
    print(f"| total | {turns} turns | {passed}/{len(scripts)} scripts passed | {cell(note)} | |")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="eval_conversation.py", description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="replay the scripts' fake replies; no key needed")
    parser.add_argument("--case", action="append", default=[], metavar="NAME", help="run only this script (repeatable)")
    parser.add_argument("--dir", type=Path, default=EVALS, help="the conversation scripts' directory")
    args = parser.parse_args(argv)  # a usage error exits 2

    paths = sorted(args.dir.glob("*.yaml"))
    unknown = sorted(set(args.case) - {p.stem for p in paths})
    if not paths or unknown:
        print(f"no such case in {args.dir}: {', '.join(unknown) or '*.yaml'}", file=sys.stderr)
        return 2
    try:
        scripts = [load_conversation(p) for p in paths if not args.case or p.stem in args.case]
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

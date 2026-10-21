"""The llm tier (V4-02; spec 2026-10-21 §6): the conversation evals with the configured conversation LLM, through
scripts/eval_conversation.py's run_all, the real instructions, Michael's description and tools on the text path; no
room, STT, TTS or Store. It calls a paid provider, so only Michael runs it:

    ( set -a; . ~/.config/voice-concierge/env; set +a; .venv/bin/pytest -m llm -s tests/llm )

The offline suite (`-m "not live and not llm"`) deselects it, and without ANTHROPIC_API_KEY it skips.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from concierge.config import LLM_KEY, Settings
from concierge.evals.conversation import load_conversation

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"),
                       reason="llm: ANTHROPIC_API_KEY not set (Michael runs these)"),
]

ROOT = Path(__file__).resolve().parents[2]
EVAL_CONVERSATION = ROOT / "scripts" / "eval_conversation.py"


async def test_conversation_evals_pass_live() -> None:
    settings = Settings()
    key = LLM_KEY[settings.llm_provider]  # under CONCIERGE_LLM_PROVIDER=openrouter, the OpenRouter key
    if not os.environ.get(key):
        pytest.skip(f"llm: {key} not set (Michael runs these)")
    spec = importlib.util.spec_from_file_location("eval_conversation_live", EVAL_CONVERSATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scripts = [load_conversation(p) for p in sorted(module.EVALS.glob("*.yaml"))]
    assert len(scripts) >= 11
    assert await module.run_all(scripts, settings) == 0  # -s shows the table: each failing row and its reply

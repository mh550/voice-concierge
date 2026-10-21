"""MORNING.md and .env.example (plan C7 Part 5): step order, exact commands, the six env names."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MORNING = (ROOT / "MORNING.md").read_text()

COMMANDS = [
    "test -s ~/.config/voice-concierge/env && grep -c '=' ~/.config/voice-concierge/env",
    ".harness/check.sh",
    "scripts/run-worker.sh start",
    "cp deploy/voice-concierge.service ~/.config/systemd/user/ && systemctl --user daemon-reload"
    " && systemctl --user enable --now voice-concierge",
    ".venv/bin/pytest -m live -q",
    ".venv/bin/python scripts/eval_memory.py",
    ".venv/bin/python scripts/eval_conversation.py",
    ".venv/bin/python scripts/latency_report.py",
    ".venv/bin/python scripts/memory_history.py",
    ".venv/bin/python scripts/check_sources.py",
    "systemctl --user stop voice-concierge",
    "touch ~/.voice-concierge-off",
]


def test_fourteen_numbered_steps_in_order() -> None:
    numbers = [int(n) for n in re.findall(r"^## (\d+)\. ", MORNING, re.M)]
    assert numbers == list(range(1, 15))


def test_exact_commands_appear_in_order() -> None:
    at = -1
    for cmd in COMMANDS:
        i = MORNING.find(cmd, at + 1)
        assert i > at, cmd
        at = i


def test_each_live_step_has_check_and_undo() -> None:
    for body in re.split(r"^## ", MORNING, flags=re.M):
        m = re.match(r"(\d+)\. ", body)
        if m and int(m.group(1)) >= 3:
            assert "Check" in body and "Undo" in body, m.group(0)


def test_states_keys_and_time_up_front() -> None:
    head = MORNING[: MORNING.index("## 1.")]
    assert "20 minutes" in head and "keys only you have" in head


def test_questions_cover_every_default() -> None:
    tail = MORNING[MORNING.index("## Questions for you") :]
    decisions = (ROOT / "docs" / "decisions.md").read_text()
    for n in re.findall(r"^## D(\d+) \*default\*", decisions, re.M):
        assert f"D{n}" in tail, n


def test_env_example_names() -> None:
    lines = (ROOT / ".env.example").read_text().splitlines()
    names = [ln.split("=")[0] for ln in lines if re.match(r"^[A-Z_]+=", ln)]
    assert names == [
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "DEEPGRAM_API_KEY",
    ]  # fmt: skip
    for switch in ("CONCIERGE_LLM_PROVIDER", "CONCIERGE_SPEECH", "CONCIERGE_RECORD_AUDIO", "CONCIERGE_ENABLED"):
        assert any(ln.startswith(f"# {switch}=") for ln in lines), switch
    assert all(ln.split("=", 1)[1] == "" for ln in lines if re.match(r"^[A-Z_]+=", ln))

"""The operator scripts, run as subprocesses: scripts/memory_history.py (C2-04), C7-02's eval_memory.py,
latency_report.py, run-worker.sh and the systemd unit (plan C7 "Part 1" and "Part 3"), and C8's messages.py.
Nothing here starts a worker, calls a provider or runs systemctl: every run-worker.sh test leaves a required name
unset, and those that set any LiveKit name run a copy that execs a stub python."""

import configparser
import hashlib
import importlib.util
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from concierge.models import AddFact, TurnMetrics
from concierge.store import Store

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "memory_history.py"
EVAL_MEMORY = ROOT / "scripts" / "eval_memory.py"
LATENCY_REPORT = ROOT / "scripts" / "latency_report.py"
RUN_WORKER = ROOT / "scripts" / "run-worker.sh"
UNIT = ROOT / "deploy" / "voice-concierge.service"
MESSAGES = ROOT / "scripts" / "messages.py"
EVALS = ROOT / "evals" / "memory"
EVAL_STEMS = sorted(p.stem for p in EVALS.glob("*.yaml"))


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, timeout=60, check=False
    )


def name(value: str, supersedes: list[int] | None = None) -> AddFact:
    return AddFact(
        slot="name", value=value, source="user_said", channel="voice", turn_id="t1", supersedes=supersedes or []
    )


def seed(db: Path, visitor_id: str) -> tuple[int, int]:
    clock = iter(range(1_760_000_000_000, 1_760_000_000_000 + 10_000_000, 60_000))
    with Store(db, clock=lambda: next(clock)) as store:
        thread = store.get_or_create_thread(visitor_id)
        ann = store.add_fact(thread.id, name("Ann"))
        anna = store.add_fact(thread.id, name("Anna", [ann.id]))
    return ann.id, anna.id


def test_memory_history_prints_one_line_per_fact(tmp_path) -> None:
    db, visitor_id = tmp_path / "memory.db", str(uuid.uuid4())
    ann, anna = seed(db, visitor_id)

    result = run(db, visitor_id)

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 2
    assert lines[0].split("\t") == ["name", "Ann", "2025-10-09T08:54:20.000Z", "2025-10-09T08:55:20.000Z", str(anna)]
    assert lines[1].split("\t") == ["name", "Anna", "2025-10-09T08:55:20.000Z", "current", "-"]
    assert "current" in result.stdout


def test_memory_history_unknown_visitor_exits_1(tmp_path) -> None:
    db = tmp_path / "memory.db"
    seed(db, str(uuid.uuid4()))

    result = run(db, str(uuid.uuid4()))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "no thread for this visitor" in result.stderr


def test_memory_history_missing_db_exits_2(tmp_path) -> None:
    db = tmp_path / "missing.db"

    result = run(db, str(uuid.uuid4()))

    assert result.returncode == 2
    assert not db.exists()


def test_memory_history_not_a_store_exits_2(tmp_path) -> None:
    empty, junk = tmp_path / "empty.db", tmp_path / "junk.db"
    empty.touch()
    junk.write_bytes(b"not a database" * 100)

    for db in (empty, junk):
        result = run(db, str(uuid.uuid4()))
        assert result.returncode == 2, db
        assert "Traceback" not in result.stderr
        assert "not a memory store" in result.stderr


def test_memory_history_never_writes_the_database(tmp_path) -> None:
    db, visitor_id = tmp_path / "memory.db", str(uuid.uuid4())
    seed(db, visitor_id)
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    assert run(db, visitor_id).returncode == 0
    assert run(db, str(uuid.uuid4())).returncode == 1

    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    with Store(db) as store:  # and the visit count wasn't touched by a get_or_create_thread
        thread = store.thread_for(visitor_id)
    assert thread is not None and thread.visits == 1


def test_memory_history_usage_exits_2(tmp_path) -> None:
    result = run(tmp_path / "memory.db")
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()


def test_memory_history_bad_fact_row_exits_2_without_a_traceback(tmp_path) -> None:
    db, visitor_id = tmp_path / "memory.db", str(uuid.uuid4())
    seed(db, visitor_id)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE facts SET slot = 'not_a_slot'")

    result = run(db, visitor_id)

    assert result.returncode == 2
    assert "not a memory store" in result.stderr
    assert "Traceback" not in result.stderr and "Ann" not in result.stderr


# --- C7-02: the scripts run with a scrubbed environment and an empty HOME ----------------------------------------


def scrubbed_env(home: Path, **extra: str) -> dict[str, str]:
    """The outer environment without LIVEKIT_*, *_API_KEY or CONCIERGE_* (so no real key can leak in), HOME a temp
    dir, plus `extra`."""
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith(("LIVEKIT_", "CONCIERGE_")) or k.endswith("_API_KEY"))}
    return {**env, "HOME": str(home), **extra}


def run_py(script: Path, *args: str | Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                          timeout=120, check=False, env=env, cwd=ROOT)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


# eval_memory.py


def test_eval_memory_without_the_key_says_not_set_and_exits_2(home) -> None:
    result = run_py(EVAL_MEMORY, env=scrubbed_env(home))
    assert result.returncode == 2
    assert "ANTHROPIC_API_KEY not set" in result.stderr
    assert result.stdout == ""


def test_eval_memory_names_the_openrouter_key_under_openrouter(home) -> None:
    result = run_py(EVAL_MEMORY, env=scrubbed_env(home, CONCIERGE_LLM_PROVIDER="openrouter", ANTHROPIC_API_KEY="x"))
    assert result.returncode == 2
    assert "OPENROUTER_API_KEY not set" in result.stderr


def table_rows(stdout: str) -> dict[str, list[str]]:
    """A markdown table's body rows by their first cell (the header and the |---| line skipped)."""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in stdout.splitlines()
            if line.startswith("|")]
    return {r[0]: r[1:] for r in rows[2:]}


@pytest.fixture(scope="module")
def offline_eval(tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess[str]:
    """One `eval_memory.py --offline` run over evals/memory, shared by the tests that read its table."""
    return run_py(EVAL_MEMORY, "--offline", env=scrubbed_env(tmp_path_factory.mktemp("home")))


def test_eval_memory_offline_has_full_recall_and_no_harm(offline_eval) -> None:
    result = offline_eval
    assert result.returncode == 0, result.stderr
    recall, harm = table_rows(result.stdout)["total"]
    assert re.fullmatch(r"\d+/\d+ \(100 %\)", recall)
    assert harm == "0"


def test_eval_memory_offline_prints_one_row_per_case(offline_eval) -> None:
    rows = table_rows(offline_eval.stdout)
    assert list(rows) == [*EVAL_STEMS, "total"]
    assert len(EVAL_STEMS) == 13
    assert rows["11-nothing-to-store"] == ["n/a", "0"]  # no expected facts: not a recall case
    assert rows["01-introduction"] == ["3/3 (100 %)", "0"]


def test_eval_memory_runs_only_the_named_cases(home) -> None:
    result = run_py(EVAL_MEMORY, "--offline", "--case", "02-correction", "--case", "01-introduction",
                    env=scrubbed_env(home))
    assert result.returncode == 0, result.stderr
    assert list(table_rows(result.stdout)) == ["01-introduction", "02-correction", "total"]


def test_eval_memory_reports_a_harm_hit_by_name_and_exits_1(home, tmp_path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    script = {
        "name": "stores-the-forbidden",
        "visits": [[{"role": "user", "text": "I work at Initech on support tooling."}]],
        "expected": [{"slot": "company", "value": "Initech"}],
        "forbidden": [{"slot": "company", "value_contains": "initech"}],
        "recorded_ops": [{"ops": [{"op": "ADD", "slot": "company", "value": "Initech", "turn_id": "v1-t1"}]}],
    }
    (cases / "stores-the-forbidden.yaml").write_text(yaml.safe_dump(script))

    result = run_py(EVAL_MEMORY, "--offline", "--dir", cases, env=scrubbed_env(home))

    assert result.returncode == 1
    rows = table_rows(result.stdout)
    assert rows["stores-the-forbidden"] == ["1/1 (100 %)", "1: forbidden company: Initech"]
    assert rows["total"] == ["1/1 (100 %)", "1"]


async def test_eval_memory_reports_a_provider_error_as_a_row_and_runs_the_other_cases(monkeypatch, capsys) -> None:
    """A 400 or a refusal from the live extractor is that case's row, not a traceback that loses the rest."""
    from livekit.agents import APIStatusError

    from concierge.evals.script import load_script

    spec = importlib.util.spec_from_file_location("eval_memory_probe", EVAL_MEMORY)
    assert spec and spec.loader
    eval_memory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eval_memory)
    real = eval_memory.run_script

    async def flaky(script, factory):
        if script.name == "01-introduction":
            raise APIStatusError("claude-sonnet-5-5 refused the request", retryable=False)
        return await real(script, factory)

    monkeypatch.setattr(eval_memory, "run_script", flaky)
    scripts = [load_script(EVALS / f"{stem}.yaml") for stem in ("01-introduction", "02-correction")]

    code = await eval_memory.run_all(scripts, None)

    rows = table_rows(capsys.readouterr().out)
    assert rows["01-introduction"] == ["error", "1: APIStatusError"]
    assert rows["02-correction"][1] == "0"
    assert rows["total"][1] == "1"
    assert code == 1


def test_eval_memory_unknown_case_exits_2(home) -> None:
    result = run_py(EVAL_MEMORY, "--offline", "--case", "99-no-such-case", env=scrubbed_env(home))
    assert result.returncode == 2
    assert "99-no-such-case" in result.stderr
    assert "Traceback" not in result.stderr


# latency_report.py

FIELDS = ["eou_ms", "stt_ms", "llm_ttft_ms", "tts_ttfb_ms", "total_ms", "memory_on_turn_path_ms", "preload_ms",
          "extraction_ms"]


def seed_metrics(db: Path, rows: list[TurnMetrics]) -> None:
    with Store(db) as store:
        for metrics in rows:
            store.add_turn_metrics(uuid.uuid4().hex, metrics)


def twenty_rows() -> list[TurnMetrics]:
    """Field k (0-based, in FIELDS order) holds (k + 1) * 10, (k + 1) * 20, ... (k + 1) * 200 over the 20 rows."""
    return [TurnMetrics(turn=i, **{f: float((k + 1) * 10 * i) for k, f in enumerate(FIELDS)},
                        prompt_tokens=1000, cached_tokens=800) for i in range(1, 21)]


def test_latency_report_prints_p50_and_p95_per_field(tmp_path, home) -> None:
    db = tmp_path / "metrics.db"
    seed_metrics(db, twenty_rows())

    result = run_py(LATENCY_REPORT, db, env=scrubbed_env(home))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:2] == ["| field | n | p50 | p95 |", "|---|---|---|---|"]
    rows = table_rows(result.stdout)
    assert list(rows) == [*FIELDS, "cached-token share"]
    # 10, 20, ... 200: p50 = 105.0 and p95 = 190.5 (linear interpolation); field k scales both by k + 1.
    for k, field in enumerate(FIELDS):
        assert rows[field] == ["n=20", f"{105.0 * (k + 1):.1f}", f"{190.5 * (k + 1):.1f}"], field
    assert rows["total_ms"] == ["n=20", "525.0", "952.5"]


def test_latency_report_counts_only_non_null_values(tmp_path, home) -> None:
    db = tmp_path / "metrics.db"
    text_turns = [TurnMetrics(turn=21 + i, llm_ttft_ms=300.0, total_ms=600.0) for i in range(5)]  # no eou/stt
    seed_metrics(db, [*twenty_rows(), *text_turns, TurnMetrics(turn=1, stt_ms=7.0)])

    rows = table_rows(run_py(LATENCY_REPORT, db, env=scrubbed_env(home)).stdout)

    assert rows["eou_ms"][0] == "n=20"
    assert rows["stt_ms"][0] == "n=21"
    assert rows["total_ms"][0] == "n=25"
    assert rows["cached-token share"][0] == "n=20"  # only the rows with both token counts


def test_latency_report_one_value_is_both_percentiles(tmp_path, home) -> None:
    db = tmp_path / "metrics.db"
    seed_metrics(db, [TurnMetrics(turn=1, preload_ms=42.0)])
    rows = table_rows(run_py(LATENCY_REPORT, db, env=scrubbed_env(home)).stdout)
    assert rows["preload_ms"] == ["n=1", "42.0", "42.0"]


def test_latency_report_prints_the_cached_token_share(tmp_path, home) -> None:
    db = tmp_path / "metrics.db"
    seed_metrics(db, [*twenty_rows(), TurnMetrics(turn=21, prompt_tokens=1000, cached_tokens=None)])
    rows = table_rows(run_py(LATENCY_REPORT, db, env=scrubbed_env(home)).stdout)
    assert rows["cached-token share"] == ["n=20", "80.0 %", ""]


def test_latency_report_on_an_empty_table_prints_n_0(tmp_path, home) -> None:
    db = tmp_path / "metrics.db"
    Store(db).close()

    result = run_py(LATENCY_REPORT, db, env=scrubbed_env(home))

    assert result.returncode == 0, result.stderr
    rows = table_rows(result.stdout)
    assert {f: rows[f] for f in FIELDS} == {f: ["n=0", "n/a", "n/a"] for f in FIELDS}
    assert rows["cached-token share"] == ["n=0", "n/a", ""]


def test_latency_report_missing_db_exits_2(tmp_path, home) -> None:
    db = tmp_path / "missing.db"
    result = run_py(LATENCY_REPORT, db, env=scrubbed_env(home))
    assert result.returncode == 2
    assert "no database" in result.stderr and "Traceback" not in result.stderr
    assert not db.exists()


def test_latency_report_not_a_store_exits_2(tmp_path, home) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database" * 100)
    result = run_py(LATENCY_REPORT, junk, env=scrubbed_env(home))
    assert result.returncode == 2
    assert "not a memory store" in result.stderr and "Traceback" not in result.stderr


def test_latency_report_usage_exits_2(home) -> None:
    result = run_py(LATENCY_REPORT, env=scrubbed_env(home))
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()


def test_latency_report_never_writes_the_database(tmp_path, home) -> None:
    db = tmp_path / "metrics.db"
    seed_metrics(db, twenty_rows())
    before = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)

    assert run_py(LATENCY_REPORT, db, env=scrubbed_env(home)).returncode == 0

    assert (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns) == before


# run-worker.sh

DUMMY = "dummy-value-7c41e9"  # never a real key; no test may see it printed
LIVEKIT = {"LIVEKIT_URL": DUMMY, "LIVEKIT_API_KEY": DUMMY, "LIVEKIT_API_SECRET": DUMMY}


def write_env_file(home: Path, values: dict[str, str]) -> None:
    env_dir = home / ".config" / "voice-concierge"
    env_dir.mkdir(parents=True)
    (env_dir / "env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def run_sh(script: Path, *args: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(script), *args], capture_output=True, text=True, timeout=30, check=False, env=env,
                          cwd=cwd)


def test_run_worker_is_executable_and_parses() -> None:
    assert os.access(RUN_WORKER, os.X_OK)
    assert subprocess.run(["bash", "-n", str(RUN_WORKER)], capture_output=True, check=False).returncode == 0


def test_run_worker_without_env_exits_1_naming_livekit_url(home, tmp_path) -> None:
    result = run_sh(RUN_WORKER, env=scrubbed_env(home), cwd=tmp_path)
    assert result.returncode == 1
    assert "LIVEKIT_URL" in result.stdout + result.stderr


def test_run_worker_reads_the_env_file_when_present(home, tmp_path, stub_checkout) -> None:
    write_env_file(home, LIVEKIT)  # the LiveKit names only: the LLM key is next
    result = run_sh(stub_checkout, env=scrubbed_env(home), cwd=tmp_path)
    assert result.returncode == 1
    assert "ANTHROPIC_API_KEY" in result.stderr and "LIVEKIT" not in result.stderr


def test_run_worker_never_prints_a_value(home, tmp_path, stub_checkout) -> None:
    write_env_file(home, LIVEKIT)
    result = run_sh(stub_checkout, env=scrubbed_env(home), cwd=tmp_path)
    assert result.returncode == 1
    assert DUMMY not in result.stdout + result.stderr


def test_run_worker_needs_the_openrouter_key_under_openrouter(home, tmp_path, stub_checkout) -> None:
    write_env_file(home, {**LIVEKIT, "ANTHROPIC_API_KEY": DUMMY, "CONCIERGE_LLM_PROVIDER": "openrouter"})
    result = run_sh(stub_checkout, env=scrubbed_env(home), cwd=tmp_path)
    assert result.returncode == 1
    assert "OPENROUTER_API_KEY" in result.stderr


def test_run_worker_needs_the_deepgram_key_under_deepgram_speech(home, tmp_path, stub_checkout) -> None:
    write_env_file(home, {**LIVEKIT, "ANTHROPIC_API_KEY": DUMMY, "CONCIERGE_SPEECH": "deepgram"})
    result = run_sh(stub_checkout, env=scrubbed_env(home), cwd=tmp_path)
    assert result.returncode == 1
    assert "DEEPGRAM_API_KEY" in result.stderr


@pytest.fixture
def stub_checkout(tmp_path: Path) -> Path:
    """A copy of run-worker.sh in a fake checkout whose .venv/bin/python only echoes its arguments, so the exec
    path is tested without starting a worker."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    shutil.copy2(RUN_WORKER, root / "scripts" / "run-worker.sh")
    python = root / ".venv" / "bin" / "python"
    python.write_text('#!/usr/bin/env bash\necho "stub python: $*"\n')
    python.chmod(0o755)
    return root / "scripts" / "run-worker.sh"


@pytest.mark.parametrize(("args", "expected"), [((), "start"), (("--help",), "--help"), (("dev",), "dev")])
def test_run_worker_execs_the_worker_with_start_by_default(home, tmp_path, stub_checkout, args, expected) -> None:
    write_env_file(home, {**LIVEKIT, "ANTHROPIC_API_KEY": DUMMY})
    result = run_sh(stub_checkout, *args, env=scrubbed_env(home), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"stub python: -m concierge.worker {expected}\n"


# deploy/voice-concierge.service (never installed or started here: build-only)


def test_systemd_unit_has_the_six_keys() -> None:
    unit = configparser.ConfigParser(interpolation=None, strict=False)  # interpolation would choke on %h
    unit.optionxform = str  # type: ignore[assignment,method-assign]  (keys are case-sensitive in systemd)
    unit.read_string(UNIT.read_text())
    assert unit["Service"]["EnvironmentFile"] == "%h/.config/voice-concierge/env"
    assert unit["Service"]["WorkingDirectory"] == "%h/projects/voice-concierge"
    assert unit["Service"]["ExecStart"] == "%h/projects/voice-concierge/scripts/run-worker.sh start"
    assert unit["Service"]["Restart"] == "on-failure"
    assert unit["Service"]["RestartSec"] == "10"
    assert unit["Install"]["WantedBy"] == "default.target"


def test_systemd_unit_waits_for_live_sessions_to_drain() -> None:
    assert "TimeoutStopSec=660" in UNIT.read_text().splitlines()


# --- C8-01: scripts/messages.py (plan C8 "The script") -------------------------------------------------------------


def seed_messages(db: Path) -> None:
    clock = iter([1_760_000_000_000, 1_760_000_000_000, 1_760_000_060_000, 1_760_000_120_000])
    with Store(db, clock=lambda: next(clock)) as store:
        thread = store.get_or_create_thread(str(uuid.uuid4()))
        store.add_message(thread.id, "Loved the RAG talk", "ann@example.com")
        store.add_message(thread.id, "Second thought: call me", None)


def test_messages_lists_newest_first(tmp_path, home) -> None:
    db = tmp_path / "memory.db"
    seed_messages(db)

    result = run_py(MESSAGES, db, env=scrubbed_env(home))

    assert result.returncode == 0, result.stderr
    assert [line.split("\t") for line in result.stdout.splitlines()] == [
        ["2025-10-09T08:54:20.000Z", "-", "Second thought: call me"],
        ["2025-10-09T08:53:20.000Z", "ann@example.com", "Loved the RAG talk"],
    ]


def test_messages_on_a_store_without_messages_prints_nothing(tmp_path, home) -> None:
    db = tmp_path / "memory.db"
    Store(db).close()
    result = run_py(MESSAGES, db, env=scrubbed_env(home))
    assert (result.returncode, result.stdout) == (0, "")


def test_messages_never_writes_the_database(tmp_path, home) -> None:
    db = tmp_path / "memory.db"
    seed_messages(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    assert run_py(MESSAGES, db, env=scrubbed_env(home)).returncode == 0
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_messages_usage_missing_db_and_not_a_store_exit_2(tmp_path, home) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database" * 100)
    usage = run_py(MESSAGES, env=scrubbed_env(home))
    assert usage.returncode == 2 and "usage" in usage.stderr.lower()
    missing = tmp_path / "missing.db"
    assert run_py(MESSAGES, missing, env=scrubbed_env(home)).returncode == 2
    assert not missing.exists()
    result = run_py(MESSAGES, junk, env=scrubbed_env(home))
    assert result.returncode == 2
    assert "not a memory store" in result.stderr and "Traceback" not in result.stderr

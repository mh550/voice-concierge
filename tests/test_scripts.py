"""C2-04: scripts/memory_history.py (plan C2 "scripts/memory_history.py")."""

import hashlib
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

from concierge.models import AddFact
from concierge.store import Store

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "memory_history.py"


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

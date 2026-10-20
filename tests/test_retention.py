"""C6-05 review (C-I1): the TTL purge runs at worker start and daily (spec B6), not only in tests."""

import asyncio
import sqlite3
from pathlib import Path

import pytest

from concierge import retention, worker
from concierge.store import Store

DAY_MS = 86_400_000


def test_purge_once_removes_an_idle_thread_and_old_daily_counts(tmp_path: Path, clock, visitor_id) -> None:
    path = tmp_path / "memory.db"
    with Store(path, clock=clock) as store:
        store.get_or_create_thread(visitor_id)
        store.count_session(visitor_id, "2025-01-01")
    assert retention.purge_once(path, clock() + 31 * DAY_MS) == 1
    with Store(path, clock=clock) as store:
        assert store.thread_for(visitor_id) is None
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM daily_session_counts").fetchone()[0] == 0


async def test_daily_purge_runs_at_once_and_again_after_each_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, int]] = []
    monkeypatch.setattr(retention, "purge_once", lambda path, now: calls.append((path, now)) or 0)
    task = asyncio.create_task(retention.run_daily_purge(tmp_path / "m.db", every_s=0.02))
    await asyncio.sleep(0.01)
    assert len(calls) == 1
    await asyncio.sleep(0.05)
    assert len(calls) >= 3
    task.cancel()
    assert calls[0][0] == tmp_path / "m.db" and calls[0][1] > 1_000_000_000_000  # ms, not seconds


async def test_a_failing_purge_is_logged_by_type_and_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[int] = []

    def purge(path: Path, now: int) -> int:
        calls.append(now)
        if len(calls) == 1:
            raise sqlite3.OperationalError(f"database is locked at {path}")
        return 0

    monkeypatch.setattr(retention, "purge_once", purge)
    task = asyncio.create_task(retention.run_daily_purge(tmp_path / "m.db", every_s=0.02))
    await asyncio.sleep(0.05)
    task.cancel()
    assert len(calls) >= 2
    assert "OperationalError" in caplog.text and str(tmp_path) not in caplog.text


async def test_the_worker_starts_the_daily_purge_when_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Path] = []

    async def fake_run(path: Path, **_: object) -> None:
        started.append(path)

    monkeypatch.setattr(retention, "run_daily_purge", fake_run)
    worker.server.emit("worker_started")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(started) == 1
    assert started[0].name == "concierge.db" and started[0].parent.name == "concierge-db"  # conftest's temp path

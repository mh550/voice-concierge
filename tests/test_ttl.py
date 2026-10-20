"""C2-04: the TTL purge (spec §4.2, B6, B7; plan C2 "TTL purge")."""

import sqlite3
import uuid

import pytest

from concierge.models import AddFact
from concierge.store import Store

DAY_MS = 86_400_000
SESSION = uuid.uuid4().hex


def seed(store: Store, visitor_id: str) -> str:
    thread = store.get_or_create_thread(visitor_id)
    store.add_fact(thread.id, AddFact(slot="name", value="Ann", source="user_said", channel="voice", turn_id="t1"))
    store.journal(thread.id, SESSION, "user_turn", {"text": "I'm Ann"})
    store.write(
        thread.id,
        None,
        lambda conn: conn.execute(
            "INSERT INTO messages_for_michael (thread_id, text, created_at) VALUES (?, 'hi', 0)", (thread.id,)
        ),
    )
    return thread.id


def rows(store: Store, table: str) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_thread_idle_31_days_is_purged(store, clock, visitor_id) -> None:
    seed(store, visitor_id)
    assert store.purge_idle(clock() + 31 * DAY_MS) == 1
    assert store.thread_for(visitor_id) is None


def test_thread_idle_29_days_stays(store, clock, visitor_id) -> None:
    seed(store, visitor_id)
    assert store.purge_idle(clock() + 29 * DAY_MS) == 0
    assert store.thread_for(visitor_id) is not None


def test_thread_idle_exactly_the_ttl_stays(store, clock, visitor_id) -> None:
    seed(store, visitor_id)
    assert store.purge_idle(clock() + 30 * DAY_MS) == 0  # last_active_at + idle_ttl_s < now, strictly
    assert store.purge_idle(clock() + 30 * DAY_MS + 1) == 1


def test_purge_idle_removes_every_row_of_a_purged_thread(store, clock, visitor_id) -> None:
    seed(store, visitor_id)
    clock.advance(20 * DAY_MS)
    kept = seed(store, str(uuid.uuid4()))  # active 20 days later

    assert store.purge_idle(clock() + 11 * DAY_MS) == 1  # the first is 31 days idle, the second 11

    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT id FROM threads").fetchall() == [(kept,)]
        for table in ("state", "facts", "journal", "messages_for_michael"):
            threads = conn.execute(f"SELECT DISTINCT thread_id FROM {table}").fetchall()
            assert threads == [(kept,)], table
    conn.close()
    assert store.thread_for(visitor_id) is None


def test_purge_idle_counts_from_the_last_visit(store, clock, visitor_id) -> None:
    seed(store, visitor_id)
    clock.advance(20 * DAY_MS)
    store.get_or_create_thread(visitor_id)  # a revisit touches last_active_at
    assert store.purge_idle(clock() + 29 * DAY_MS) == 0


def test_purge_idle_honours_a_per_thread_ttl(store, clock, visitor_id) -> None:
    thread_id = seed(store, visitor_id)
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE threads SET idle_ttl_s = 3600 WHERE id = ?", (thread_id,))
    conn.close()
    assert store.purge_idle(clock() + 3_600_001) == 1


def test_purge_idle_keeps_anonymous_tables(store, clock, visitor_id) -> None:
    seed(store, visitor_id)
    store.count_session(visitor_id, "2025-10-09")
    assert store.purge_idle(clock() + 31 * DAY_MS) == 1
    assert rows(store, "daily_session_counts") == 1


def test_purge_daily_counts_drops_rows_older_than_2_days(store, clock) -> None:
    # clock() is 2025-10-09T08:53:20Z
    for day in ("2025-10-09", "2025-10-08", "2025-10-07", "2025-10-06", "2025-09-30"):
        store.count_session("v", day)

    assert store.purge_daily_counts(clock()) == 2

    with sqlite3.connect(store.path) as conn:
        days = sorted(d for (d,) in conn.execute("SELECT day FROM daily_session_counts"))
    assert days == ["2025-10-07", "2025-10-08", "2025-10-09"]


@pytest.mark.parametrize("purge", ["purge_idle", "purge_daily_counts"])
def test_purges_reject_a_now_in_seconds(store, clock, visitor_id, purge) -> None:
    seed(store, visitor_id)
    with pytest.raises(ValueError, match="ms"):
        getattr(store, purge)(clock() // 1000 + 31 * 86_400)

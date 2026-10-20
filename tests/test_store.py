import json
import multiprocessing
import sqlite3
import uuid

import pytest
from pydantic import ValidationError

from concierge.models import TurnMetrics, VisitorState
from concierge.schema import TABLES
from concierge.store import Store, StoreError, ThreadMissing
from concierge.testing.store_writers import open_and_touch

SEVEN = {
    "threads", "state", "facts", "journal", "anonymous_turn_metrics", "daily_session_counts", "messages_for_michael",
}
SESSION = uuid.uuid4().hex


def raw(store: Store) -> sqlite3.Connection:
    """A second, independent connection to the store's file (what another process would see)."""
    return sqlite3.connect(store.path)


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    return {name for (name,) in rows}


def test_schema_creates_the_seven_tables(store) -> None:
    assert set(TABLES) == SEVEN
    with raw(store) as conn:
        assert table_names(conn) == SEVEN


def test_journal_mode_is_wal(store) -> None:
    with raw(store) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_foreign_keys_and_secure_delete_are_on(store) -> None:
    assert store.pragma("foreign_keys") == 1
    assert store.pragma("secure_delete") == 1
    assert store.pragma("user_version") == 1


def test_reopening_keeps_schema_and_rows(tmp_path, clock, visitor_id) -> None:
    first = Store(tmp_path / "memory.db", clock=clock)
    thread = first.get_or_create_thread(visitor_id)
    first.journal(thread.id, "s1", "session_started", {"n": 1})
    first.close()
    second = Store(tmp_path / "memory.db", clock=clock)
    try:
        assert second.thread_for(visitor_id).id == thread.id
        assert [r.type for r in second.journal_rows(thread.id)] == ["session_started"]
    finally:
        second.close()


def test_get_or_create_thread_returns_the_same_thread(store, visitor_id) -> None:
    first = store.get_or_create_thread(visitor_id)
    second = store.get_or_create_thread(visitor_id)
    assert second.id == first.id
    assert len(first.id) == 32 and uuid.UUID(hex=first.id).version == 4
    with raw(store) as conn:
        assert conn.execute("SELECT count(*) FROM threads").fetchone()[0] == 1


def test_new_thread_row_defaults(store, visitor_id, clock) -> None:
    thread = store.get_or_create_thread(visitor_id)
    assert (thread.version, thread.idle_ttl_s, thread.visits) == (0, 2592000, 1)
    assert thread.created_at == thread.last_active_at == clock.now
    with raw(store) as conn:
        version, ttl, attributes = conn.execute(
            "SELECT version, idle_ttl_s, attributes FROM threads WHERE id = ?", (thread.id,)
        ).fetchone()
    assert (version, ttl, json.loads(attributes)) == (0, 2592000, {"visits": 1})
    assert store.state(thread.id) == VisitorState()


def test_get_or_create_counts_visits_and_touches_last_active(store, visitor_id, clock) -> None:
    first = store.get_or_create_thread(visitor_id)
    clock.advance(60_000)
    second = store.get_or_create_thread(visitor_id)
    assert second.visits == 2
    assert second.last_active_at == first.last_active_at + 60_000
    assert second.created_at == first.created_at
    assert second.version == 1  # the revisit is a write to the thread, so it bumps the fence (plan: Store API)
    with raw(store) as conn:
        attributes, last_active = conn.execute(
            "SELECT attributes, last_active_at FROM threads WHERE id = ?", (first.id,)
        ).fetchone()
    assert json.loads(attributes) == {"visits": 2}
    assert last_active == clock.now


def test_threads_visitor_id_is_unique(store, visitor_id) -> None:
    store.get_or_create_thread(visitor_id)
    with raw(store) as conn, pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            "INSERT INTO threads (id, visitor_id, created_at, last_active_at) VALUES (?, ?, 0, 0)",
            (uuid.uuid4().hex, visitor_id),
        )


def test_two_visitors_get_two_threads(store) -> None:
    a = store.get_or_create_thread(str(uuid.uuid4()))
    b = store.get_or_create_thread(str(uuid.uuid4()))
    assert a.id != b.id


def test_journal_rows_come_back_in_insertion_order(store, visitor_id, clock) -> None:
    thread = store.get_or_create_thread(visitor_id)
    types = ["session_started", "user_turn", "agent_turn", "user_turn", "session_ended"]
    ids = []
    for i, kind in enumerate(types):
        ids.append(store.journal(thread.id, "sess-1", kind, {"i": i}))
        clock.advance(-10)  # a clock going backwards: only insertion order (id) can give the expected list
    rows = store.journal_rows(thread.id)
    assert [r.id for r in rows] == ids
    assert [r.type for r in rows] == types
    assert [r.payload for r in rows] == [{"i": i} for i in range(5)]
    assert all(r.thread_id == thread.id and r.session_id == "sess-1" for r in rows)


def test_journal_rows_are_scoped_to_their_thread(store) -> None:
    a = store.get_or_create_thread(str(uuid.uuid4()))
    b = store.get_or_create_thread(str(uuid.uuid4()))
    store.journal(a.id, "s", "user_turn", {"who": "a"})
    store.journal(b.id, "s", "user_turn", {"who": "b"})
    assert [r.payload for r in store.journal_rows(a.id)] == [{"who": "a"}]


def test_journal_bumps_the_version(store, visitor_id) -> None:
    thread = store.get_or_create_thread(visitor_id)
    store.journal(thread.id, "s", "session_started", {})
    store.journal(thread.id, "s", "user_turn", {})
    assert store.version(thread.id) == 2


def test_journal_rejects_an_unknown_type(store, visitor_id) -> None:
    thread = store.get_or_create_thread(visitor_id)
    with pytest.raises(ValidationError):
        store.journal(thread.id, "s", "made_up", {})
    assert store.journal_rows(thread.id) == []
    assert store.version(thread.id) == 0


def test_journal_on_a_missing_thread_raises_thread_missing(store) -> None:
    with pytest.raises(ThreadMissing):
        store.journal(uuid.uuid4().hex, "s", "user_turn", {})
    with raw(store) as conn:
        assert conn.execute("SELECT count(*) FROM threads").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM journal").fetchone()[0] == 0


def test_version_of_a_missing_thread_raises_thread_missing(store) -> None:
    with pytest.raises(ThreadMissing):
        store.version(uuid.uuid4().hex)
    assert store.thread_for(str(uuid.uuid4())) is None


def test_anonymous_turn_metrics_columns(store) -> None:
    with raw(store) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(anonymous_turn_metrics)")]
    assert columns == [
        "id", "session_id", "turn", "eou_ms", "stt_ms", "llm_ttft_ms", "tts_ttfb_ms", "total_ms",
        "memory_on_turn_path_ms", "preload_ms", "extraction_ms", "prompt_tokens", "cached_tokens", "compacted",
    ]
    assert "visitor_id" not in columns and "thread_id" not in columns and "text" not in columns


def test_add_turn_metrics_writes_one_row_of_numbers(store) -> None:
    metrics = TurnMetrics(turn=3, eou_ms=212.6, stt_ms=80.2, llm_ttft_ms=410.0, total_ms=901.49,
                          prompt_tokens=1200, cached_tokens=1024, compacted=True)
    store.add_turn_metrics(SESSION, metrics)
    with raw(store) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM anonymous_turn_metrics").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row.pop("id") == 1
    assert row == {
        "session_id": SESSION, "turn": 3, "eou_ms": 213.0, "stt_ms": 80.0, "llm_ttft_ms": 410.0,
        "tts_ttfb_ms": None, "total_ms": 901.0, "memory_on_turn_path_ms": None, "preload_ms": None,
        "extraction_ms": None, "prompt_tokens": 1200, "cached_tokens": 1024, "compacted": 1,
    }


def test_add_turn_metrics_needs_no_thread(store) -> None:
    store.add_turn_metrics(SESSION, TurnMetrics(turn=1))
    with raw(store) as conn:
        assert conn.execute("SELECT count(*) FROM threads").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM anonymous_turn_metrics").fetchone()[0] == 1


def test_two_stores_on_one_file_share_the_schema(tmp_path, clock, visitor_id) -> None:
    a = Store(tmp_path / "memory.db", clock=clock)
    b = Store(tmp_path / "memory.db", clock=clock)
    try:
        assert a.get_or_create_thread(visitor_id).id == b.get_or_create_thread(visitor_id).id
        assert b.thread_for(visitor_id).visits == 2
    finally:
        a.close()
        b.close()


def test_processes_opening_a_fresh_file_together_all_succeed(tmp_path, visitor_id) -> None:
    # The switch to WAL on a new file doesn't wait on SQLite's busy timeout; the store must retry it itself.
    ctx = multiprocessing.get_context("spawn")
    for run in range(3):
        db = str(tmp_path / f"fresh-{run}.db")
        barrier = ctx.Barrier(4)
        procs = [ctx.Process(target=open_and_touch, args=(db, visitor_id, barrier)) for _ in range(4)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        assert [p.exitcode for p in procs] == [0, 0, 0, 0], f"run {run}"
        with sqlite3.connect(db) as conn:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert json.loads(conn.execute("SELECT attributes FROM threads").fetchone()[0]) == {"visits": 4}
            assert conn.execute("SELECT count(*) FROM journal").fetchone()[0] == 4


@pytest.mark.parametrize("payload", [["a"], "text", None, 3])
def test_journal_rejects_a_non_object_payload(store, visitor_id, payload) -> None:
    thread = store.get_or_create_thread(visitor_id)
    with pytest.raises(TypeError):
        store.journal(thread.id, "s", "user_turn", payload)
    assert store.journal_rows(thread.id) == []


def test_journal_rejects_text_that_cannot_be_stored(store, visitor_id) -> None:
    thread = store.get_or_create_thread(visitor_id)
    with pytest.raises(ValueError):
        store.journal(thread.id, "s", "user_turn", {"text": "A\ud800"})  # a lone surrogate, from json.loads
    assert store.version(thread.id) == 0


@pytest.mark.parametrize(
    "session_id", ["3f2b8c1e-9a4d-4c7b-8e21-5d6f7a8b9c0d", "visitor-3f2b8c1e", "concierge-room", "A" * 32, ""]
)
def test_add_turn_metrics_session_id_must_be_uuid4_hex(store, session_id) -> None:
    # B9: the session id is the only free-form key in the anonymous table, so a visitor id can't be passed in.
    with pytest.raises(ValueError):
        store.add_turn_metrics(session_id, TurnMetrics(turn=1))


def test_reopening_a_newer_schema_raises(tmp_path, clock) -> None:
    Store(tmp_path / "memory.db", clock=clock).close()
    with sqlite3.connect(tmp_path / "memory.db") as conn:
        conn.execute("PRAGMA user_version = 2")
    with pytest.raises(StoreError, match="schema version 2"):
        Store(tmp_path / "memory.db", clock=clock)
    with sqlite3.connect(tmp_path / "memory.db") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_last_active_at_never_moves_backwards(store, visitor_id, clock) -> None:
    first = store.get_or_create_thread(visitor_id)
    clock.advance(-5_000)  # a writer that read the clock before waiting for the lock
    assert store.get_or_create_thread(visitor_id).last_active_at == first.last_active_at

"""C2-04: "Forget me" (spec §4.2, B7, B9; plan C2 "Erasure")."""

import sqlite3
import uuid
from pathlib import Path

import pytest

from concierge.models import AddFact, TurnMetrics
from concierge.store import Store, ThreadMissing

VISITOR_TABLES = ("threads", "state", "facts", "journal", "messages_for_michael")
SESSION = uuid.uuid4().hex


def add(slot: str = "interests", value: str = "RAG") -> AddFact:
    return AddFact(slot=slot, value=value, source="user_said", channel="voice", turn_id="turn-1")


def count(store: Store, table: str) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def leave_message(store: Store, thread_id: str, text: str) -> None:
    store.add_message(thread_id, text, "ann@example.com")  # C8's write, as the leave_message_for_michael tool does


def seed_visitor(store: Store, visitor_id: str, marker: str = "Ann") -> str:
    thread = store.get_or_create_thread(visitor_id)
    store.add_fact(thread.id, add("name", marker))
    store.add_fact(thread.id, add("interests", f"{marker} RAG"))
    store.journal(thread.id, SESSION, "user_turn", {"text": f"I'm {marker}"})
    leave_message(store, thread.id, f"{marker} says hello")
    return thread.id


def seed_anonymous(store: Store, visitor_id: str) -> None:
    for turn in range(1, 4):
        store.add_turn_metrics(uuid.uuid4().hex, TurnMetrics(turn=turn, total_ms=900.0))
    store.count_session(visitor_id, "2025-10-09")


def test_forget_me_erases_visitor_tables_and_keeps_anonymous_ones(store, visitor_id) -> None:
    seed_visitor(store, visitor_id)
    seed_anonymous(store, visitor_id)
    assert all(count(store, table) > 0 for table in VISITOR_TABLES)

    assert store.forget_me(visitor_id) is True

    assert {table: count(store, table) for table in VISITOR_TABLES} == dict.fromkeys(VISITOR_TABLES, 0)
    assert count(store, "anonymous_turn_metrics") == 3
    assert count(store, "daily_session_counts") == 1


def disk_bytes(path: Path) -> bytes:
    return b"".join(p.read_bytes() for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")) if p.exists())


@pytest.mark.parametrize("checkpointed", [False, True], ids=["in_wal", "in_main_file"])
def test_forget_me_leaves_no_bytes_on_disk(store, visitor_id, checkpointed) -> None:
    marker = "Zyxwvutsrq" + uuid.uuid4().hex[:8]
    seed_visitor(store, visitor_id, marker)
    if checkpointed:
        store._checkpoint()
    assert marker.encode() in disk_bytes(store.path)  # the test can see it before

    store.forget_me(visitor_id)

    assert marker.encode() not in disk_bytes(store.path)
    assert visitor_id.encode() not in disk_bytes(store.path)


def test_forget_me_vacuums(store, visitor_id) -> None:
    thread_id = seed_visitor(store, visitor_id)
    for i in range(40):  # enough journal pages that deleting them leaves free pages only a VACUUM gives back
        store.journal(thread_id, SESSION, "user_turn", {"text": f"{i} " + "x" * 1000})
    seed_visitor(store, str(uuid.uuid4()), "Bob")
    pages_before = store.pragma("page_count")

    store.forget_me(visitor_id)

    assert store.pragma("freelist_count") == 0
    assert store.pragma("page_count") <= pages_before - 10  # ~40 KB of journal gone from the file
    assert store.path.stat().st_size == store.pragma("page_count") * store.pragma("page_size")


def _add_fact(store: Store, thread_id: str) -> None:
    store.add_fact(thread_id, add())


def _journal(store: Store, thread_id: str) -> None:
    store.journal(thread_id, SESSION, "user_turn", {"text": "hello"})


def _apply_fact_ops(store: Store, thread_id: str) -> None:
    store.apply_fact_ops(thread_id, [add()])


def _apply_fact_ops_based_on(store: Store, thread_id: str) -> None:
    store.apply_fact_ops(thread_id, [add()], based_on=3)  # an extraction that loaded the thread before the erasure


@pytest.mark.parametrize(
    "write",
    [_add_fact, _journal, _apply_fact_ops, _apply_fact_ops_based_on],
    ids=["add_fact", "journal", "apply_fact_ops", "apply_fact_ops_based_on"],
)
def test_writes_after_forget_me_raise_thread_missing(store, visitor_id, write) -> None:
    thread_id = seed_visitor(store, visitor_id)
    store.forget_me(visitor_id)

    with pytest.raises(ThreadMissing):
        write(store, thread_id)

    assert count(store, "threads") == 0
    assert count(store, "facts") == 0
    assert count(store, "journal") == 0
    assert store.thread_for(visitor_id) is None


def test_forget_me_only_touches_that_visitor(store, visitor_id) -> None:
    seed_visitor(store, visitor_id, "Ann")
    other = str(uuid.uuid4())
    other_thread = seed_visitor(store, other, "Bob")
    before = store.fact_history(other_thread), store.journal_rows(other_thread), store.state(other_thread)

    store.forget_me(visitor_id)

    assert (store.fact_history(other_thread), store.journal_rows(other_thread), store.state(other_thread)) == before
    assert store.thread_for(other) is not None
    for table in VISITOR_TABLES:
        assert count(store, table) > 0


def test_forget_me_deletes_the_visitors_messages(store, visitor_id) -> None:
    mine = store.get_or_create_thread(visitor_id).id
    theirs = store.get_or_create_thread(str(uuid.uuid4())).id
    leave_message(store, mine, "Ann says hello")
    leave_message(store, mine, "Ann again")
    leave_message(store, theirs, "Bob says hello")

    assert store.forget_me(visitor_id) is True

    assert [(m.thread_id, m.text) for m in store.messages()] == [(theirs, "Bob says hello")]
    with pytest.raises(ThreadMissing):  # and no message can be left on the erased thread
        leave_message(store, mine, "too late")
    assert count(store, "messages_for_michael") == 1


def test_forget_me_unknown_visitor_returns_false(store, visitor_id) -> None:
    seed_visitor(store, visitor_id)
    assert store.forget_me(str(uuid.uuid4())) is False
    assert store.thread_for(visitor_id) is not None


def test_forget_me_twice_returns_false_the_second_time(store, visitor_id) -> None:
    seed_visitor(store, visitor_id)
    assert store.forget_me(visitor_id) is True
    assert store.forget_me(visitor_id) is False


def test_a_returning_visitor_after_forget_me_gets_a_fresh_thread(store, visitor_id) -> None:
    old = seed_visitor(store, visitor_id)
    store.forget_me(visitor_id)

    fresh = store.get_or_create_thread(visitor_id)

    assert fresh.id != old
    assert (fresh.visits, fresh.version) == (1, 0)
    assert store.valid_facts(fresh.id) == []


def test_count_session_survives_forget_me(store, visitor_id) -> None:
    store.get_or_create_thread(visitor_id)
    day = "2025-10-09"
    store.count_session(visitor_id, day)
    store.count_session(visitor_id, day)

    assert store.forget_me(visitor_id) is True

    assert store.count_session(visitor_id, day) == 3


def test_forget_me_raises_and_erases_nothing_when_it_cannot_take_the_write_lock(store, visitor_id) -> None:
    seed_visitor(store, visitor_id)
    blocker = sqlite3.connect(store.path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")  # another process is writing
    store._conn.execute("PRAGMA busy_timeout = 50")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            store.forget_me(visitor_id)
    finally:
        blocker.close()
    assert store.thread_for(visitor_id) is not None  # so the page's RPC must not answer ok


def test_forget_me_returns_true_when_a_reader_blocks_the_checkpoint(store, visitor_id, caplog) -> None:
    seed_visitor(store, visitor_id)
    reader = sqlite3.connect(store.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM threads").fetchall()  # an open read transaction in another process
    store._conn.execute("PRAGMA busy_timeout = 100")  # the checkpoint waits out the busy timeout (5 s) for it
    try:
        assert store.forget_me(visitor_id) is True
    finally:
        reader.close()
    assert store.thread_for(visitor_id) is None
    assert "checkpoint was busy" in caplog.text
    assert visitor_id not in caplog.text


class FailingVacuum:
    """The store's connection, except that VACUUM fails (as on a full disk, or a corrupt page)."""

    def __init__(self, conn: sqlite3.Connection, error: sqlite3.Error) -> None:
        self._conn = conn
        self._error = error

    def execute(self, sql: str, *args):
        if sql.strip().upper() == "VACUUM":
            raise self._error
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


@pytest.mark.parametrize(
    "error",
    [sqlite3.OperationalError("database or disk is full"), sqlite3.DatabaseError("database disk image is malformed")],
    ids=["full", "corrupt"],
)
def test_forget_me_returns_true_when_vacuum_fails(store, visitor_id, caplog, error) -> None:
    thread_id = seed_visitor(store, visitor_id)
    store._conn = FailingVacuum(store._conn, error)

    assert store.forget_me(visitor_id) is True

    assert store.thread_for(visitor_id) is None
    assert "VACUUM after forget_me of thread " + thread_id[:8] in caplog.text
    assert visitor_id not in caplog.text and thread_id not in caplog.text


def test_forget_me_deletes_every_child_row_without_the_cascades(store, visitor_id) -> None:
    # The ON DELETE CASCADE keys are a second net; the explicit deletes must do the job on their own.
    seed_visitor(store, visitor_id)
    store._conn.execute("PRAGMA foreign_keys = OFF")

    assert store.forget_me(visitor_id) is True

    assert {table: count(store, table) for table in VISITOR_TABLES} == dict.fromkeys(VISITOR_TABLES, 0)


def test_a_checkpoint_blocked_by_a_reader_is_finished_by_the_next_write(store, visitor_id) -> None:
    marker = "Qwertzuiop" + uuid.uuid4().hex[:8]
    seed_visitor(store, visitor_id, marker)
    store._checkpoint()  # the marker now sits in the main file too
    other = store.get_or_create_thread(str(uuid.uuid4()))
    reader = sqlite3.connect(store.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM threads").fetchall()
    store._conn.execute("PRAGMA busy_timeout = 100")
    assert store.forget_me(visitor_id) is True
    assert marker.encode() in disk_bytes(store.path)  # the reader kept the checkpoint from finishing
    reader.close()

    store.journal(other.id, SESSION, "user_turn", {"text": "hello"})  # any later write settles it

    assert marker.encode() not in disk_bytes(store.path)


def test_purge_idle_finishes_an_owed_checkpoint_even_when_nothing_is_idle(store, clock, visitor_id) -> None:
    marker = "Asdfghjkl" + uuid.uuid4().hex[:8]
    seed_visitor(store, visitor_id, marker)
    store._checkpoint()
    reader = sqlite3.connect(store.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM threads").fetchall()
    store._conn.execute("PRAGMA busy_timeout = 100")
    store.forget_me(visitor_id)
    reader.close()

    assert store.purge_idle(clock()) == 0

    assert marker.encode() not in disk_bytes(store.path)


@pytest.mark.parametrize("checkpointed", [False, True], ids=["in_wal", "in_main_file"])
def test_purge_idle_leaves_no_bytes_on_disk(store, clock, visitor_id, checkpointed) -> None:
    marker = "Mnbvcxzlk" + uuid.uuid4().hex[:8]
    seed_visitor(store, visitor_id, marker)
    if checkpointed:
        store._checkpoint()
    assert marker.encode() in disk_bytes(store.path)

    assert store.purge_idle(clock() + 31 * 86_400_000) == 1

    assert marker.encode() not in disk_bytes(store.path)
    assert visitor_id.encode() not in disk_bytes(store.path)
    assert store.pragma("freelist_count") == 0

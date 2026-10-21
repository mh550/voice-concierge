"""The page's two RPC methods (spec §6; plan C6 Part 4): `concierge.forget_me` and `concierge.get_memory`."""

import asyncio
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.testing import fake_job_context

from concierge import session as concierge_session
from concierge.config import Settings
from concierge.contract import FORGET_ME_METHOD, GET_MEMORY_METHOD, MEMORY_TOPIC, build_memory_payload
from concierge.limits import GOODBYE_LINE
from concierge.memory_view import current_memory
from concierge.memory_writer import MemoryWriter
from concierge.models import AddFact
from concierge.publish import MemoryPublisher
from concierge.rpc import build_handlers, register_rpcs
from concierge.session import start_session
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM
from concierge.testing.fake_room import FakeRoom
from concierge.testing.sessions import METADATA, VISITOR, shutdown, start
from concierge.testing.speaking_session import FakeSpeakingSession

CONTRACT = Path(__file__).parent / "contract"
VISITOR_TABLES = ("threads", "state", "facts", "journal", "messages_for_michael")


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((CONTRACT / name).read_text()))


def invocation(method: str, caller: str = f"visitor-{VISITOR}", payload: str = "") -> rtc.RpcInvocationData:
    return rtc.RpcInvocationData(
        request_id="req-1", caller_identity=caller, payload=payload, response_timeout=10.0, method=method
    )


def count(store: Store, table: str) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def visitor_rows(store: Store) -> int:
    return sum(count(store, table) for table in VISITOR_TABLES)


async def until(cond: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


def seed(store: Store) -> str:
    tid = store.get_or_create_thread(VISITOR).id
    for n, (slot, value) in enumerate([("name", "Ada"), ("company", "Acme")], 1):
        store.add_fact(tid, AddFact(slot=slot, value=value, source="user_said", channel="voice", turn_id=f"t{n}"))
    store.journal(tid, "s", "user_turn", {"text": "I'm Ada from Acme"})
    return tid


class Rig:
    """register_rpcs over a real store, MemoryWriter and MemoryPublisher, a FakeRoom and a speaking session."""

    def __init__(self, store: Store, *, with_writer: bool = True) -> None:
        self.store = store
        self.room = FakeRoom()
        self.session = FakeSpeakingSession()
        self.ended: list[str] = []
        self.tasks: set[asyncio.Task[Any]] = set()
        tid = seed(store)
        self.writer = MemoryWriter(store, tid, "s", lambda: FakeLLM([]), 60.0) if with_writer else None
        self.publisher = MemoryPublisher(self.room, lambda: current_memory(store, self.writer, VISITOR))
        handlers = build_handlers(
            visitor_id=VISITOR, store=store, writer=self.writer, publisher=self.publisher, session=self.session,
            end=self.ended.append, tasks=self.tasks,
        )
        register_rpcs(self.room, handlers)

    @property
    def rpc(self) -> dict[str, Callable[..., Any]]:
        return self.room.local_participant.rpc_handlers

    def memory_sends(self) -> list[dict[str, Any]]:
        return [json.loads(text) for text in self.room.local_participant.sent_on(MEMORY_TOPIC)]

    async def aclose(self) -> None:
        if self.writer is not None:
            await self.writer.aclose()


@pytest.fixture
async def rig(store: Store) -> AsyncIterator[Rig]:  # async: FakeRoom (an rtc.Room) wants a running loop
    yield Rig(store)


async def test_register_rpcs_registers_both_methods(rig: Rig) -> None:
    assert set(rig.rpc) == {"concierge.forget_me", "concierge.get_memory"} == {FORGET_ME_METHOD, GET_MEMORY_METHOD}
    await rig.aclose()


async def test_forget_me_returns_ok_within_50_ms_while_the_erase_sleeps(
    rig: Rig, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_forget = store.forget_me

    def slow_forget(visitor_id: str) -> bool:
        time.sleep(1.0)
        return real_forget(visitor_id)

    monkeypatch.setattr(store, "forget_me", slow_forget)
    assert visitor_rows(store) > 0

    began = time.monotonic()
    answer = await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    assert time.monotonic() - began < 0.05
    assert json.loads(answer) == {"ok": True} and answer == '{"ok": true}'
    validator("forget_me.schema.json").validate(json.loads(answer))

    await asyncio.sleep(1.5)
    assert visitor_rows(store) == 0
    (sent,) = rig.memory_sends()
    assert sent["facts"] == [] and sent["visitor"] == {"name": None, "visits": 0}
    validator("memory.schema.json").validate(sent)
    assert [text for text, _ in rig.session.said] == [GOODBYE_LINE]
    assert rig.session.interrupts == [True]  # review A-I1: the goodbye cuts the reply that is playing
    assert rig.ended == ["forget_me"]  # the close stub (ctx.shutdown in a session)
    assert rig.writer is not None and rig.writer.erased
    await rig.aclose()


async def test_get_memory_returns_the_topic_json(rig: Rig, store: Store) -> None:
    answer = await rig.rpc[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD))
    body = json.loads(answer)
    validator("memory.schema.json").validate(body)
    expected = json.loads(build_memory_payload(store, rig.writer.thread_id).model_dump_json())  # type: ignore[union-attr]
    assert {k: v for k, v in body.items() if k != "updated_at"} == {
        k: v for k, v in expected.items() if k != "updated_at"
    }
    assert [f["value"] for f in body["facts"]] == ["Ada", "Acme"]
    await rig.aclose()


async def test_get_memory_returns_a_v2_body(rig: Rig) -> None:
    body = json.loads(await rig.rpc[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD)))
    validator("memory.schema.json").validate(body)
    assert body["v"] == 2 and body["retention_days"] == 30
    assert [f["value"] for f in body["about_visitor"]["profile"]] == ["Ada", "Acme"]
    await rig.aclose()


async def test_get_memory_without_a_writer_reads_the_store(store: Store) -> None:
    rig = Rig(store, with_writer=False)  # the preload missed its deadline, or the daily cap
    body = json.loads(await rig.rpc[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD)))
    assert [f["value"] for f in body["facts"]] == ["Ada", "Acme"]
    assert store.thread_for("someone-else") is None  # read-only: no thread was created


async def test_get_memory_of_nobody_is_empty(tmp_path: Path) -> None:
    body = json.loads((await current_memory(None, None, VISITOR)).model_dump_json())
    assert body["facts"] == [] and body["visitor"] == {"name": None, "visits": 0}
    with Store(tmp_path / "empty.db") as empty:
        assert (await current_memory(empty, None, VISITOR)).facts == []
        assert empty.thread_for(VISITOR) is None


async def test_rpcs_refuse_another_caller(rig: Rig, store: Store) -> None:
    for method in (FORGET_ME_METHOD, GET_MEMORY_METHOD):
        with pytest.raises(rtc.RpcError) as refused:
            await rig.rpc[method](invocation(method, caller="agent-other"))
        assert refused.value.code == 4403
    await asyncio.sleep(0.1)
    assert visitor_rows(store) > 0 and rig.memory_sends() == [] and rig.ended == []
    await rig.aclose()


async def test_a_second_forget_me_starts_nothing(rig: Rig) -> None:
    first = await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    second = await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    assert first == second == '{"ok": true}'
    await until(lambda: rig.ended != [], 2)
    await asyncio.sleep(0.1)
    assert len(rig.memory_sends()) == 1 and rig.ended == ["forget_me"] and len(rig.session.said) == 1
    await rig.aclose()


async def test_forget_me_without_memory_erases_through_the_store(store: Store) -> None:
    rig = Rig(store, with_writer=False)
    await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    await until(lambda: rig.ended != [], 2)
    assert visitor_rows(store) == 0
    assert [s["facts"] for s in rig.memory_sends()] == [[]]


async def test_forget_me_with_a_closed_writer_still_erases(rig: Rig, store: Store) -> None:
    await rig.aclose()  # writer.call raises StoreError now (C4 review B-M4)
    await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    await until(lambda: rig.ended != [], 2)
    assert visitor_rows(store) == 0


async def test_a_failed_erase_still_sends_the_empty_memory_and_ends(
    rig: Rig, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(visitor_id: str) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "forget_me", broken)
    await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    await until(lambda: rig.ended != [], 2)
    assert [s["facts"] for s in rig.memory_sends()] == [[]] and rig.ended == ["forget_me"]
    await rig.aclose()


async def test_no_merge_publish_after_the_forget_publish(rig: Rig) -> None:
    await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    await until(lambda: rig.ended != [], 2)
    rig.publisher.schedule()  # a merge's on_merged landing late
    await rig.publisher.idle()
    assert [s["facts"] for s in rig.memory_sends()] == [[]]
    await rig.aclose()


# --- through start_session (a real AgentSession over FakeLLMs, a FakeRoom as ctx.room) ---------------------------


async def test_get_memory_equals_the_last_published_body(fakes: list[FakeLLM], db: Store) -> None:
    """V2-05: one build path, so the RPC answers with what the topic last carried, about_agent and events included."""
    tid = db.get_or_create_thread(VISITOR).id
    db.add_fact(tid, AddFact(slot="company", value="Acme", source="user_said", channel="voice", turn_id="t1"))
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        assert started.events is not None and started.publisher is not None
        started.events.note("remember", "Remembered at your request: company")
        started.publisher.schedule()  # a send after the greeting landed: nothing changes between it and the call
        await started.publisher.idle()
        last = json.loads(room.local_participant.sent_on(MEMORY_TOPIC)[-1])
        body = json.loads(await room.local_participant.rpc_handlers[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD)))
        await shutdown(ctx, started)
    validator("memory.schema.json").validate(body)
    assert body["about_agent"] is not None and body["about_visitor"]["events"] != []
    assert {**body, "updated_at": None} == {**last, "updated_at": None}


async def test_get_memory_after_forget_me_without_memory_equals_the_last_send(fakes: list[FakeLLM]) -> None:
    """Review M2: no writer (here no store): the last send is the empty body, and get_memory answers the same."""
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, None)
        before = json.loads(await room.local_participant.rpc_handlers[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD)))
        assert before["about_agent"] is not None  # the agent exists, so it reports itself (D18 (d))
        assert json.loads(await room.local_participant.rpc_handlers[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD)))
        await until(lambda: started.publisher is not None and started.publisher.closed, 3)
        await until(lambda: len(room.local_participant.sent_on(MEMORY_TOPIC)) == 2, 3)
        last = json.loads(room.local_participant.sent_on(MEMORY_TOPIC)[-1])
        body = json.loads(await room.local_participant.rpc_handlers[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD)))
        await shutdown(ctx, started)
    assert last["about_agent"] is None and {**body, "updated_at": None} == {**last, "updated_at": None}


async def test_start_session_registers_both_rpcs(fakes: list[FakeLLM], db: Store) -> None:
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        assert set(room.local_participant.rpc_handlers) == {FORGET_ME_METHOD, GET_MEMORY_METHOD}
        body = json.loads(await room.local_participant.rpc_handlers[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD)))
        validator("memory.schema.json").validate(body)
        await shutdown(ctx, started)


async def test_forget_me_cancels_the_writer_and_skips_the_summary(
    fakes: list[FakeLLM], db: Store, summarizer: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        ended: list[str] = []
        monkeypatch.setattr(ctx, "shutdown", lambda reason="": ended.append(reason))
        started = await start(ctx, db)
        await started.session.run(user_input="I'm Ada from Acme.")
        answer = await room.local_participant.rpc_handlers[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
        assert answer == '{"ok": true}'
        await until(lambda: ended != [], 10)
        assert ended == ["forget_me"]
        assert started.writer is not None and started.writer.erased
        await shutdown(ctx, started, "forget_me")
    assert summarizer.calls == []  # erased: no visit summary (spec §4.2)
    with Store(db.path) as reopened:  # the shutdown closed `db`
        assert reopened.thread_for(VISITOR) is None
    sends = [json.loads(t) for t in room.local_participant.sent_on(MEMORY_TOPIC)]
    assert sends[-1]["facts"] == [] and sends[-1]["visitor"] == {"name": None, "visits": 0}


async def test_forget_me_waits_for_a_preload_that_missed_its_deadline(
    fakes: list[FakeLLM], db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review I2: the session runs without memory (no writer) while the late preload goes on; an erase that didn't
    wait for it would be followed by the preload re-creating the visitor's thread."""
    seed(db)  # a returning visitor
    real_thread = db.get_or_create_thread

    def slow_thread(visitor_id: str) -> Any:
        time.sleep(0.6)
        return real_thread(visitor_id)

    monkeypatch.setattr(db, "get_or_create_thread", slow_thread)
    monkeypatch.setattr(concierge_session, "PRELOAD_TIMEOUT_S", 0.1)
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        ended: list[str] = []
        monkeypatch.setattr(ctx, "shutdown", lambda reason="": ended.append(reason))
        started = await start_session(ctx, db, Settings())  # not `start`: it waits for the late preload
        assert started.writer is None  # the preload missed its deadline
        await room.local_participant.rpc_handlers[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
        await until(lambda: ended != [], 10)
        await shutdown(ctx, started, "forget_me")
    with Store(db.path) as reopened:
        assert reopened.thread_for(VISITOR) is None
        assert visitor_rows(reopened) == 0


async def test_get_memory_failure_is_an_rpc_error_without_the_message(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Review M5: rtc logs a handler's exception with its message (participant.py:629-634); ours carries the type."""

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Zephyrine")

    assert rig.writer is not None
    monkeypatch.setattr(rig.writer, "call", broken)
    with pytest.raises(rtc.RpcError) as failed:
        await rig.rpc[GET_MEMORY_METHOD](invocation(GET_MEMORY_METHOD))
    assert "Zephyrine" not in failed.value.message and "Zephyrine" not in caplog.text
    assert "ValueError" in caplog.text
    await rig.aclose()


async def test_a_locked_store_through_the_writer_is_retried_directly(
    rig: Rig, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M4: any failure through the writer (sqlite3.OperationalError after the busy timeout, not only
    StoreError) is retried once straight through the store."""
    real_forget = store.forget_me
    calls: list[int] = []

    def locked_once(visitor_id: str) -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_forget(visitor_id)

    monkeypatch.setattr(store, "forget_me", locked_once)
    await rig.rpc[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
    await until(lambda: rig.ended != [], 2)
    assert len(calls) == 2 and visitor_rows(store) == 0
    await rig.aclose()


async def test_forget_me_stops_the_session_timer(
    fakes: list[FakeLLM], db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M7: the 10-minute line can't follow the goodbye."""
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        monkeypatch.setattr(ctx, "shutdown", lambda reason="": None)
        started = await start(ctx, db)
        assert started.timer is not None
        await room.local_participant.rpc_handlers[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
        await asyncio.sleep(0.05)
        assert started.timer.cancelled()
        await shutdown(ctx, started, "forget_me")


async def test_a_forget_me_during_session_start_gets_no_greeting_and_no_timer(
    fakes: list[FakeLLM], db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review A-M1: the RPCs answer before session.start returns; a forget then must not be followed by a greeting
    built from the erased memory, nor by the 10-minute timer."""
    room = FakeRoom()
    real_start = AgentSession.start

    async def start_after_a_forget(self: AgentSession, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        await room.local_participant.rpc_handlers[FORGET_ME_METHOD](invocation(FORGET_ME_METHOD))
        await asyncio.sleep(0.05)  # the erase task runs
        return await real_start(self, *args, **kwargs)

    monkeypatch.setattr(AgentSession, "start", start_after_a_forget)
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        monkeypatch.setattr(ctx, "shutdown", lambda reason="": None)
        started = await start(ctx, db)
        assert started.writer is not None and started.writer.erased
        assert started.greeting is None and started.timer is None
        await shutdown(ctx, started, "forget_me")

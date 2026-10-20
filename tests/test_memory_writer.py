"""The background memory writer (spec §4.4; plan C4 "The scheduler"): debounced, one run in flight per thread, the
new turns journaled, then extract → merge → extraction_ran → on_merged."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import llm
from livekit.agents.testing import fake_job_context

from concierge import session as concierge_session
from concierge.memory_writer import MemoryWriter
from concierge.merge import MergeResult
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.sessions import METADATA, shutdown, start
from concierge.text_input import ChannelTags


def user(text: str, msg_id: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="user", content=[text], id=msg_id)


def agent(text: str, msg_id: str, *, interrupted: bool = False) -> llm.ChatMessage:
    return llm.ChatMessage(role="assistant", content=[text], id=msg_id, interrupted=interrupted)


def add(slot: str, value: str, turn_id: str) -> dict[str, Any]:
    return {"op": "ADD", "slot": slot, "value": value, "fact_id": None, "confidence": None, "turn_id": turn_id,
            "reason": None}


def emit(*ops: dict[str, Any], delay_s: float = 0.0) -> FakeResponse:
    return FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": list(ops)}), delay_s=delay_s)


async def until(cond: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def types(store: Store, thread_id: str) -> list[str]:
    return [r.type for r in store.journal_rows(thread_id)]


@pytest.fixture
def thread_id(store: Store, visitor_id: str) -> str:
    return store.get_or_create_thread(visitor_id).id


@pytest.fixture
async def make(store: Store, thread_id: str) -> AsyncIterator[Callable[..., MemoryWriter]]:
    made: list[MemoryWriter] = []

    def build(fake: FakeLLM, **kwargs: Any) -> MemoryWriter:
        made.append(MemoryWriter(store, thread_id, "s1", lambda: fake, **kwargs))
        return made[-1]

    yield build
    for writer in made:
        await writer.aclose()


async def test_two_schedules_100ms_apart_start_one_extraction(make: Callable[..., MemoryWriter]) -> None:
    fake = FakeLLM([emit(delay_s=0.5), emit()])  # slow, so a second timer would overlap the first run
    writer = make(fake)  # the default 2 s debounce
    writer.note_item(user("I work at Acme.", "u1"))  # schedules
    await asyncio.sleep(0.1)
    writer.schedule()
    await asyncio.sleep(3)
    assert len(fake.calls) == 1
    assert "Acme" in (fake.calls[0].chat_ctx.items[-1].text_content or "")


async def test_a_turn_during_a_run_queues_exactly_one_follow_up(
    make: Callable[..., MemoryWriter], store: Store, thread_id: str
) -> None:
    fake = FakeLLM([emit(delay_s=0.5), emit(), emit()])
    writer = make(fake, debounce_s=0.05)
    writer.note_item(user("I work at Acme.", "u1"))
    await until(lambda: len(fake.calls) == 1, 2)
    writer.note_item(user("I'm a PM.", "u2"))
    writer.note_item(user("I like Rust.", "u3"))
    writer.schedule()
    await until(lambda: types(store, thread_id).count("extraction_ran") == 2, 3)
    await asyncio.sleep(0.3)
    assert len(fake.calls) == 2
    second = fake.calls[1].chat_ctx.items[-1].text_content or ""
    assert "PM" in second and "Rust" in second and "Acme" not in second


async def test_run_journals_extraction_ran_with_ms_and_ops(
    make: Callable[..., MemoryWriter], store: Store, thread_id: str
) -> None:
    writer = make(FakeLLM([emit(add("company", "Acme", "u1"))]), debounce_s=0.01)
    writer.note_item(user("I work at Acme.", "u1"))
    await until(lambda: "extraction_ran" in types(store, thread_id), 2)
    (ran,) = [r for r in store.journal_rows(thread_id) if r.type == "extraction_ran"]
    assert isinstance(ran.payload["ms"], int) and ran.payload["ops"] == 1 and ran.payload["applied"] == 1
    assert ran.payload["tool_called"] is True
    assert [(f.slot, f.value, f.turn_id) for f in store.valid_facts(thread_id)] == [("company", "Acme", "u1")]


async def test_run_journals_the_new_turns_in_order(
    make: Callable[..., MemoryWriter], store: Store, thread_id: str
) -> None:
    writer = make(FakeLLM([emit()]), debounce_s=60)
    writer.note_item(agent("Hi, I'm the concierge.", "a0"))
    writer.note_item(user("Tell me about Michael.", "u1"))
    writer.note_item(agent("Michael worked at Acme", "a1", interrupted=True))
    await writer.flush()
    rows = [r for r in store.journal_rows(thread_id) if r.type in ("user_turn", "agent_turn")]
    assert [(r.type, r.payload["turn_id"]) for r in rows] == [("agent_turn", "a0"), ("user_turn", "u1"),
                                                              ("agent_turn", "a1")]
    assert rows[1].payload == {"turn_id": "u1", "channel": "voice", "text": "Tell me about Michael.",
                               "confidence": None}
    assert rows[2].payload == {"turn_id": "a1", "interrupted": True, "text": "Michael worked at Acme"}


async def test_on_merged_is_called_after_each_run(make: Callable[..., MemoryWriter]) -> None:
    results: list[MergeResult] = []
    fake = FakeLLM([emit(add("company", "Acme", "u1")), emit()])
    writer = make(fake, debounce_s=0.01, on_merged=results.append)
    writer.note_item(user("I work at Acme.", "u1"))
    await until(lambda: len(results) == 1, 2)
    assert results[0].state.company == "Acme"
    writer.note_item(user("What's new?", "u2"))
    await until(lambda: len(results) == 2, 2)


async def test_a_failing_on_merged_callback_never_stops_the_writer(make: Callable[..., MemoryWriter]) -> None:
    def boom(result: MergeResult) -> None:
        raise RuntimeError("publish failed")

    fake = FakeLLM([emit(), emit()])
    writer = make(fake, debounce_s=0.01, on_merged=boom)
    writer.note_item(user("Hello.", "u1"))
    await until(lambda: len(fake.calls) == 1, 2)
    writer.note_item(user("Again.", "u2"))
    await until(lambda: len(fake.calls) == 2, 2)


async def test_a_failed_run_keeps_its_turns_for_the_next(
    make: Callable[..., MemoryWriter], store: Store, thread_id: str
) -> None:
    fake = FakeLLM([FakeResponse(error="overloaded"), emit(add("company", "Acme", "u1"))])
    writer = make(fake, debounce_s=0.01)
    writer.note_item(user("I work at Acme.", "u1"))
    await until(lambda: "error" in types(store, thread_id), 2)
    (error,) = [r for r in store.journal_rows(thread_id) if r.type == "error"]
    assert error.payload == {"stage": "extraction", "type": "APIStatusError"}
    writer.note_item(user("And I like Rust.", "u2"))
    await until(lambda: "extraction_ran" in types(store, thread_id), 2)
    retried = fake.calls[1].chat_ctx.items[-1].text_content or ""
    assert "Acme" in retried and "Rust" in retried
    assert [r.payload["turn_id"] for r in store.journal_rows(thread_id) if r.type == "user_turn"] == ["u1", "u2"]
    assert [f.value for f in store.valid_facts(thread_id)] == ["Acme"]


async def test_window_drops_are_journaled(make: Callable[..., MemoryWriter], store: Store, thread_id: str) -> None:
    writer = make(FakeLLM([emit()]), debounce_s=60)
    for i in range(30):
        writer.note_item(user(f"Turn number {i}.", f"u{i}"))
    await writer.flush()
    (ran,) = [r for r in store.journal_rows(thread_id) if r.type == "extraction_ran"]
    assert ran.payload["window_dropped"] == 6
    assert types(store, thread_id).count("user_turn") == 30


async def test_flush_runs_the_remaining_turns(make: Callable[..., MemoryWriter], store: Store, thread_id: str) -> None:
    fake = FakeLLM([emit(add("company", "Acme", "u1"))])
    writer = make(fake, debounce_s=60)
    writer.note_item(user("I work at Acme.", "u1"))
    await writer.flush()
    assert len(fake.calls) == 1
    assert "extraction_ran" in types(store, thread_id)
    assert store.state(thread_id).company == "Acme"


async def test_flush_with_only_agent_turns_journals_them_and_calls_no_llm(
    make: Callable[..., MemoryWriter], store: Store, thread_id: str
) -> None:
    fake = FakeLLM([])
    writer = make(fake, debounce_s=60)
    writer.note_item(agent("Hello there.", "a0"))
    await writer.flush()
    assert fake.calls == []
    assert types(store, thread_id) == ["agent_turn"]


async def test_flush_is_bounded_by_its_timeout(make: Callable[..., MemoryWriter]) -> None:
    writer = make(FakeLLM([emit(delay_s=5)]), debounce_s=0)
    writer.note_item(user("I work at Acme.", "u1"))
    began = time.perf_counter()
    await writer.flush(timeout_s=0.3)
    assert time.perf_counter() - began < 1.0


async def test_typed_turn_is_tagged_text(make: Callable[..., MemoryWriter], store: Store, thread_id: str) -> None:
    channels = ChannelTags()
    channels.on_text(SimpleNamespace(text="I work at Acme."))  # type: ignore[arg-type]
    writer = make(FakeLLM([emit(add("company", "Acme", "u1"))]), debounce_s=60, channels=channels)
    writer.note_item(user("I work at Acme.", "u1"))
    writer.note_item(user("I like Rust.", "u2"))
    assert writer.last_user_turn is not None and writer.last_user_turn.channel == "voice"
    await writer.flush()
    turns = [r.payload for r in store.journal_rows(thread_id) if r.type == "user_turn"]
    assert [t["channel"] for t in turns] == ["text", "voice"]
    (fact,) = store.valid_facts(thread_id)
    assert (fact.channel, fact.source) == ("text", "user_typed")


async def test_no_writer_without_preload(db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(*args: Any) -> None:
        raise RuntimeError("disk")

    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, None)
        assert started.writer is None
        await shutdown(ctx, started)
    monkeypatch.setattr(concierge_session, "preload", failing)
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is None and started.writer is None
        await started.session.run(user_input="I work at Acme.")
        await shutdown(ctx, started)


async def test_aclose_leaves_no_task_behind(make: Callable[..., MemoryWriter]) -> None:  # review M5
    fake = FakeLLM([emit(delay_s=5), emit()])
    writer = make(fake, debounce_s=0.01)
    writer.note_item(user("I work at Acme.", "u1"))
    await until(lambda: len(fake.calls) == 1, 2)
    writer.note_item(user("I like Rust.", "u2"))  # queues a follow-up behind the slow run
    await writer.aclose()
    assert writer._tasks == set() and writer._timer is None
    writer.note_item(user("Still here?", "u3"))
    assert writer._tasks == set()


async def test_a_turn_during_the_final_flush_is_journaled(
    make: Callable[..., MemoryWriter], store: Store, thread_id: str
) -> None:  # review M6
    fake = FakeLLM([emit(delay_s=0.3), emit()])
    writer = make(fake, debounce_s=60)
    writer.note_item(user("I work at Acme.", "u1"))
    flushing = asyncio.create_task(writer.flush())
    await until(lambda: len(fake.calls) == 1, 2)
    writer.note_item(user("And I like Rust.", "u2"))
    await flushing
    assert [r.payload["turn_id"] for r in store.journal_rows(thread_id) if r.type == "user_turn"] == ["u1", "u2"]
    assert len(fake.calls) == 2


async def test_cancel_all_reaches_the_final_flush_run(make: Callable[..., MemoryWriter]) -> None:  # review M7
    fake = FakeLLM([emit(delay_s=5)])
    writer = make(fake, debounce_s=60)
    writer.note_item(user("I work at Acme.", "u1"))
    flushing = asyncio.create_task(writer.flush())
    await until(lambda: len(fake.calls) == 1, 2)
    writer.cancel_all()
    await asyncio.wait_for(flushing, 0.5)


async def test_the_handler_stays_fast_during_an_inflight_run(make: Callable[..., MemoryWriter]) -> None:  # M12
    fake = FakeLLM([emit(delay_s=5), emit()])
    writer = make(fake, debounce_s=0.01)
    writer.note_item(user("I work at Acme.", "u1"))
    await until(lambda: len(fake.calls) == 1, 2)
    began = time.perf_counter()
    writer.note_item(user("I like Rust.", "u2"))
    assert time.perf_counter() - began < 0.05

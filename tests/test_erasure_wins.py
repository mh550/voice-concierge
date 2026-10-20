"""Erasure wins over pending work (spec §4.2; plan C4 "Erasure wins"): forget_me plus cancel_all during an
extraction leaves zero visitor rows, and the shutdown callback then does nothing for that visitor."""

import asyncio
import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any

import pytest
from livekit.agents import llm
from livekit.agents.testing import fake_job_context

from concierge import session as concierge_session
from concierge.memory_writer import MemoryWriter, forget_visitor
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.sessions import METADATA, VISITOR, shutdown, start

VISITOR_TABLES = ("threads", "facts", "state", "journal", "messages_for_michael")


class CitingLLM(FakeLLM):
    """A slow extractor whose emit_ops ADD cites the newest visitor turn it was shown (its id is the session's)."""

    def __init__(self, delay_s: float) -> None:
        super().__init__([])
        self.delay_s = delay_s
        self.cancelled = False

    def chat(self, **kwargs: Any) -> Any:  # noqa: ANN401
        turns = json.loads(kwargs["chat_ctx"].items[-1].text_content.rsplit("\n", 1)[-1])
        turn_id = [t["turn_id"] for t in turns if t["speaker"] == "visitor"][-1]
        op = {"op": "ADD", "slot": "company", "value": "Acme", "fact_id": None, "confidence": None,
              "turn_id": turn_id, "reason": None}
        self._script.append(FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": [op]}),
                                         delay_s=self.delay_s))
        stream = super().chat(**kwargs)
        real_run = stream._run

        async def run() -> None:
            try:
                await real_run()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        stream._run = run  # type: ignore[method-assign]
        return stream


def slow_extractor(delay_s: float) -> CitingLLM:
    return CitingLLM(delay_s)


async def until(cond: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


def counts(path: Any) -> dict[str, int]:  # noqa: ANN401
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in VISITOR_TABLES}
    finally:
        conn.close()


async def _erase_during_extraction(
    db: Store, monkeypatch: pytest.MonkeyPatch, *, cancel: bool
) -> tuple[CitingLLM, MemoryWriter, list[dict[str, Any]]]:
    extractor = slow_extractor(1.0)
    monkeypatch.setattr(concierge_session, "build_llm", lambda stage, settings=None: extractor)
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 0.05)
    errors: list[dict[str, Any]] = []
    asyncio.get_running_loop().set_exception_handler(lambda loop, context: errors.append(context))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        writer = started.writer
        assert writer is not None
        await started.session.run(user_input="I work at Acme.")
        await until(lambda: len(extractor.calls) == 1, 3)  # the extraction is in its 1 s LLM call
        if cancel:  # the real "Forget me" path: cancel first, then erase on the writer's store thread
            assert await forget_visitor(writer, VISITOR)
            await until(lambda: writer._run is None, 0.2)  # cancelled now, not after the 1 s call
            assert extractor.cancelled
        else:
            assert await asyncio.to_thread(db.forget_me, VISITOR)
            await until(lambda: writer.erased, 2)  # nothing cancelled: the run's merge hits the fence (ThreadMissing)
        await shutdown(ctx, started)
        await asyncio.sleep(1.2)  # past the point the extraction would have finished
    return extractor, writer, errors


async def test_erasure_wins_over_an_inflight_extraction(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, writer, errors = await _erase_during_extraction(db, monkeypatch, cancel=True)
    assert counts(db.path) == dict.fromkeys(VISITOR_TABLES, 0)
    assert writer.erased
    assert errors == []


async def test_the_fence_alone_keeps_an_erased_thread_empty(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run is not cancelled: its ADD (citing the real turn) reaches the merge after forget_me and fails."""
    extractor, _, errors = await _erase_during_extraction(db, monkeypatch, cancel=False)
    assert not extractor.cancelled
    assert counts(db.path) == dict.fromkeys(VISITOR_TABLES, 0)
    assert errors == []


async def test_cancel_all_sets_erased_and_ignores_later_turns(store: Store, visitor_id: str) -> None:
    thread_id = store.get_or_create_thread(visitor_id).id
    fake = FakeLLM([])
    writer = MemoryWriter(store, thread_id, "s1", lambda: fake, debounce_s=0.01)
    try:
        writer.note_item(llm.ChatMessage(role="user", content=["I work at Acme."], id="u1"))
        writer.cancel_all()
        assert writer.erased
        writer.note_item(llm.ChatMessage(role="user", content=["And I like Rust."], id="u2"))
        writer.schedule()
        await asyncio.sleep(0.2)
        await writer.flush()
        assert fake.calls == []
        assert store.journal_rows(thread_id) == []
    finally:
        await writer.aclose()


async def test_shutdown_skips_flush_when_erased(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 60)
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.writer is not None and started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        started.writer.cancel_all()
        await shutdown(ctx, started)
    assert extractor.calls == []
    with Store(db.path) as s:
        kinds = [r.type for r in s.journal_rows(started.preloaded.thread_id)]
    assert "session_ended" not in kinds and "user_turn" not in kinds and "extraction_ran" not in kinds


async def test_forget_visitor_cancels_then_erases(store: Store, visitor_id: str) -> None:
    thread_id = store.get_or_create_thread(visitor_id).id
    fake = slow_extractor(1.0)
    writer = MemoryWriter(store, thread_id, "s1", lambda: fake, debounce_s=0.01)
    try:
        writer.note_item(llm.ChatMessage(role="user", content=["I work at Acme."], id="u1"))
        await until(lambda: len(fake.calls) == 1, 2)
        assert await forget_visitor(writer, visitor_id)
        assert writer.erased
        await asyncio.sleep(1.2)
        assert store.thread_for(visitor_id) is None
        assert counts(store.path) == dict.fromkeys(VISITOR_TABLES, 0)
    finally:
        await writer.aclose()

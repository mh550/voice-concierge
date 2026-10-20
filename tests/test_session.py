"""start_session (spec §4.3; plan C3 "Session start and end"): preload → agent → session.start → greeting, with
session_started / session_ended journaled off the greeting's path. A real AgentSession runs the FakeLLM; the room
half of session.start is patched out (fake_job_context's room never connects)."""

import functools
import sqlite3
from typing import Any

import pytest
from livekit.agents import llm
from livekit.agents.testing import fake_job_context

from concierge import session as concierge_session
from concierge.config import Settings
from concierge.erasure_hooks import forget_visitor
from concierge.greeting import INTRODUCTION
from concierge.knowledge import load_pack
from concierge.memory_writer import FLUSH_TIMEOUT_S
from concierge.models import AddFact
from concierge.prompt import MEMORY_HEADER, build_instructions
from concierge.session import start_session
from concierge.store import Store
from concierge.store_base import BUSY_TIMEOUT_S
from concierge.summary import SUMMARY_TIMEOUT_S
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.recording_session import RecordingSession
from concierge.testing.sessions import METADATA, VISIT_SUMMARY, VISITOR, shutdown, stage_llms, start
from concierge.worker import server


def last_text(call: Any) -> str:
    item = call.chat_ctx.items[-1]
    assert isinstance(item, llm.ChatMessage) and item.role == "system"
    return item.text_content or ""


def _add(slot: str, value: str, n: int) -> AddFact:
    return AddFact(slot=slot, value=value, source="user_said", channel="voice", turn_id=f"turn-{n}")


async def test_first_session_creates_the_thread_and_journals_session_started(db: Store, fakes: list[FakeLLM]) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        thread = db.thread_for(VISITOR)
        assert thread is not None and thread.visits == 1
        assert started.preloaded is not None and started.preloaded.block is None
        (row,) = [r for r in db.journal_rows(thread.id) if r.type == "session_started"]
        assert row.session_id == started.session_id
        assert row.payload == {"visits": 1, "preload_ms": started.preloaded.ms, "returning": False}
        assert last_text(fakes[0].calls[0]) == INTRODUCTION
        await shutdown(ctx, started)


async def test_second_session_counts_visit_two_and_greets_by_the_seeded_name(db: Store, fakes: list[FakeLLM]) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        first = await start(ctx, db)
        assert first.preloaded is not None
        db.apply_fact_ops(first.preloaded.thread_id, [_add("name", "Ada", 1), _add("asked_about", "LiveKit", 2)])
        await first.session.aclose()  # no shutdown callback between them: the store stays open

    with fake_job_context(job_metadata=METADATA) as ctx:
        second = await start(ctx, db)
        assert second.preloaded is not None and second.preloaded.visits == 2
        thread = db.thread_for(VISITOR)
        assert thread is not None and thread.visits == 2
        assert last_text(fakes[1].calls[0]).startswith('Greet "Ada" by name and offer to pick up ')
        rows = [r for r in db.journal_rows(thread.id) if r.type == "session_started"]
        assert [r.session_id for r in rows] == [first.session_id, second.session_id]
        assert rows[1].payload["visits"] == 2 and rows[1].payload["returning"] is True
        await shutdown(ctx, second)


async def test_greeting_is_not_part_of_the_cached_prefix(db: Store, fakes: list[FakeLLM]) -> None:
    thread = db.get_or_create_thread(VISITOR)
    db.apply_fact_ops(thread.id, [_add("name", "Ada", 1)])
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None and started.preloaded.block is not None
        await started.session.run(user_input="What does Michael do?")
        await shutdown(ctx, started)

    first, second = fakes[0].calls
    prefix = build_instructions(load_pack(), started.preloaded.block)
    for call in (first, second):
        assert call.chat_ctx.items[0].text_content == prefix  # byte-identical system prefix in every call
    assert MEMORY_HEADER in prefix and "Greet" not in prefix
    assert last_text(first).startswith('Greet "Ada"')
    assert not any("Greet" in (getattr(i, "text_content", "") or "") for i in second.chat_ctx.items)


async def test_shutdown_callback_journals_session_ended_and_closes_the_store(db: Store, fakes: list[FakeLLM]) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None
        await shutdown(ctx, started, reason="participant left")
    with pytest.raises(sqlite3.ProgrammingError):
        db.thread_for(VISITOR)
    with Store(db.path) as s:
        rows = s.journal_rows(started.preloaded.thread_id)
    # The greeting is journaled by the final flush (an agent turn: no extraction), before session_ended.
    assert [r.type for r in rows] == ["memory_preloaded", "session_started", "agent_turn", "session_ended"]
    ended = rows[-1]
    assert ended.session_id == started.session_id
    assert ended.payload["reason"] == "participant left" and isinstance(ended.payload["duration_s"], float)


async def test_session_ended_is_journaled_on_the_writers_store_thread(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:  # C5-02 review M7: after a cancelled run's last store call, so it goes through writer.call (C5 review A-M1)
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        writer = started.writer
        assert writer is not None
        kinds: list[str] = []
        real_call = writer.call

        async def recording_call(fn: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            if getattr(fn, "__name__", "") == "journal":
                kinds.append(args[2])
            return await real_call(fn, *args, **kwargs)

        monkeypatch.setattr(writer, "call", recording_call)
        await shutdown(ctx, started)
    assert kinds[-1] == "session_ended"


async def test_shutdown_after_forget_me_journals_nothing_and_still_closes(db: Store, fakes: list[FakeLLM]) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert db.forget_me(VISITOR)
        await shutdown(ctx, started)
    with pytest.raises(sqlite3.ProgrammingError):
        db.thread_for(VISITOR)
    with Store(db.path) as s:
        assert s.thread_for(VISITOR) is None
    conn = sqlite3.connect(db.path)
    try:
        assert conn.execute("SELECT count(*) FROM journal").fetchone() == (0,)
    finally:
        conn.close()


async def test_shutdown_closes_the_store_when_session_start_fails(db: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        def on(self, event: str, callback: Any = None) -> Any:
            return callback

        async def start(self, **_: Any) -> None:
            raise RuntimeError("no room")

    monkeypatch.setattr(concierge_session, "build_session", lambda ctx, settings: Failing())
    monkeypatch.setattr(concierge_session, "room_start_kwargs", lambda *args: {})
    with fake_job_context(job_metadata=METADATA) as ctx:
        with pytest.raises(RuntimeError, match="no room"):
            await start_session(ctx, db, Settings())
        (callback,) = ctx._shutdown_callbacks
        await callback("start failed")
    with pytest.raises(sqlite3.ProgrammingError):
        db.thread_for(VISITOR)


async def test_session_started_is_written_after_the_greeting_is_queued(
    db: Store, recording_session: type[RecordingSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_journal = db.journal

    def journal(thread_id: str, session_id: str, kind: Any, payload: dict[str, Any]) -> int:
        order.append(kind)
        return real_journal(thread_id, session_id, kind, payload)

    real_reply = RecordingSession.generate_reply

    def reply(self: RecordingSession, **kwargs: Any) -> str:
        order.append("greeting")
        return real_reply(self, **kwargs)

    monkeypatch.setattr(db, "journal", journal)
    monkeypatch.setattr(RecordingSession, "generate_reply", reply)
    with fake_job_context(job_metadata=METADATA) as ctx:
        ctx.proc.userdata["vad"] = "vad"
        started = await start_session(ctx, db, Settings())
        assert order == ["memory_preloaded", "greeting"]  # nothing awaited a store write after the greeting
        assert len(started.tasks) == 1
        for task in list(started.tasks):
            await task
        assert order == ["memory_preloaded", "greeting", "session_started"]
        (session,) = recording_session.instances
        assert session.replies == [{"instructions": INTRODUCTION}]
        for callback in ctx._shutdown_callbacks:
            await callback("test")
    assert order[-1] == "session_ended"


async def test_a_session_without_a_store_greets_as_new_and_journals_nothing(fakes: list[FakeLLM]) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, None)
        assert started.preloaded is None and started.tasks == set()
        assert last_text(fakes[0].calls[0]) == INTRODUCTION
        await shutdown(ctx, started)


async def test_the_writer_sees_the_greeting_and_the_turns_and_flushes_at_shutdown(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM
) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.writer is not None and started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        assert [(t.role, t.text) for t in started.writer.history] == [
            ("agent", "Hello there."), ("user", "I work at Acme."), ("agent", "Michael builds voice agents.")
        ]
        assert extractor.calls == []  # still inside the 2 s debounce
        await shutdown(ctx, started)
    assert len(extractor.calls) == 1  # the shutdown flush ran the final extraction
    with Store(db.path) as s:
        kinds = [r.type for r in s.journal_rows(started.preloaded.thread_id)]
    assert kinds[-6:] == ["agent_turn", "user_turn", "agent_turn", "extraction_ran", "summary_written", "session_ended"]


async def test_the_agent_gets_the_writer_as_its_memory(db: Store, fakes: list[FakeLLM]) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        agent = started.session.current_agent
        assert agent._memory is started.writer
        await shutdown(ctx, started)


async def test_store_closes_even_if_the_writer_fails_to_close(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:  # review M11
    async def failing_aclose(self: object) -> None:
        raise RuntimeError("provider close failed")

    monkeypatch.setattr(concierge_session.MemoryWriter, "aclose", failing_aclose)
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        await shutdown(ctx, started)
    with pytest.raises(sqlite3.ProgrammingError):
        db.thread_for(VISITOR)


# --- the session-end visit summary (C5-02; plan C5 "The shutdown sequence") ---------------------------------


async def test_shutdown_runs_the_final_extraction_then_the_summary(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []  # how many extractor calls had happened when the summarizer was called

    def respond(ctx: llm.ChatContext) -> str:
        seen.append(len(extractor.calls))
        return VISIT_SUMMARY

    summarizer = FakeLLM(respond=respond)
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=extractor, summarizer=summarizer))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        assert extractor.calls == []  # still inside the 2 s debounce: the shutdown's flush is the extraction
        await shutdown(ctx, started)
    assert seen == [1]
    with Store(db.path) as s:
        kinds = [r.type for r in s.journal_rows(started.preloaded.thread_id)]
        assert s.state(started.preloaded.thread_id).last_visit_summary == VISIT_SUMMARY
    assert kinds.index("extraction_ran") < kinds.index("summary_written") < kinds.index("session_ended")


async def test_no_summary_llm_call_after_forget_me(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM, summarizer: FakeLLM
) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.writer is not None
        await started.session.run(user_input="I work at Acme.")
        assert await forget_visitor(started.writer, VISITOR)
        await shutdown(ctx, started)
    assert summarizer.calls == [] and extractor.calls == []
    conn = sqlite3.connect(db.path)
    try:
        for table in ("threads", "facts", "state", "journal", "messages_for_michael"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table
    finally:
        conn.close()


async def test_no_summary_for_a_visit_without_user_turns(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM
) -> None:
    thread = db.get_or_create_thread(VISITOR)
    db.set_summary(thread.id, None, "The visitor runs a clinic.")
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)  # the greeting only
        await shutdown(ctx, started)
    assert summarizer.calls == []
    with Store(db.path) as s:
        assert s.state(thread.id).last_visit_summary == "The visitor runs a clinic."
        assert "summary_written" not in [r.type for r in s.journal_rows(thread.id)]


def test_shutdown_timeouts_fit_the_process_timeout() -> None:
    work = concierge_session.SHUTDOWN_WORK_S
    assert FLUSH_TIMEOUT_S + SUMMARY_TIMEOUT_S + BUSY_TIMEOUT_S <= work < server._shutdown_process_timeout


async def test_summary_written_journals_counts_not_text(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM
) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        await shutdown(ctx, started)
    assert len(summarizer.calls) == 1
    with Store(db.path) as s:
        (row,) = [r for r in s.journal_rows(started.preloaded.thread_id) if r.type == "summary_written"]
    assert set(row.payload) == {"chars", "sentences", "ms"}
    assert row.payload["chars"] == len(VISIT_SUMMARY) and row.payload["sentences"] == 1
    assert "Acme" not in str(row.payload)


async def test_the_summary_after_a_flush_timeout_still_runs(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A final extraction that misses its deadline is cancelled; the summary still runs after it."""
    slow = FakeLLM([FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": []}), delay_s=5)])
    pending: list[int] = []  # the writer's unfinished tasks when the summarizer was called

    def respond(ctx: llm.ChatContext) -> str:
        assert started.writer is not None
        pending.append(sum(not t.done() for t in started.writer._tasks))
        return VISIT_SUMMARY

    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=slow, summarizer=FakeLLM(respond=respond)))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.writer is not None and started.preloaded is not None
        monkeypatch.setattr(started.writer, "flush", functools.partial(started.writer.flush, timeout_s=0.2))
        await started.session.run(user_input="I work at Acme.")
        await shutdown(ctx, started)
    assert len(slow.calls) == 1 and pending == [0]  # the timed-out run was cancelled before the summary
    with Store(db.path) as s:
        assert s.state(started.preloaded.thread_id).last_visit_summary == VISIT_SUMMARY


async def test_a_summarizer_that_cannot_be_built_still_ends_the_session(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=extractor))  # "summarizer": KeyError
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        await shutdown(ctx, started)
    with Store(db.path) as s:
        rows = s.journal_rows(started.preloaded.thread_id)
    assert [r.payload for r in rows if r.type == "error"] == [{"stage": "summary", "type": "KeyError"}]
    assert rows[-1].type == "session_ended"


async def test_forget_me_during_the_summary_call_stores_nothing(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:  # review M6
    def respond(ctx: llm.ChatContext) -> str:
        assert started.writer is not None
        started.writer.cancel_all()  # "Forget me" lands while the summarizer is working
        return VISIT_SUMMARY

    summarizer = FakeLLM(respond=respond)
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=extractor, summarizer=summarizer))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        await shutdown(ctx, started)
    with Store(db.path) as s:
        assert s.state(started.preloaded.thread_id).last_visit_summary is None
        kinds = [r.type for r in s.journal_rows(started.preloaded.thread_id)]
    assert "summary_written" not in kinds and "session_ended" not in kinds


async def test_a_forgotten_value_stays_out_of_the_visit_summary(
    db: Store, fakes: list[FakeLLM], extractor: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:  # review I1
    summarizer = FakeLLM(["The visitor works at Acme."])
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=extractor, summarizer=summarizer))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        writer = started.writer
        assert writer is not None and started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        asked_at = writer.note_forget("where I work")  # what do_forget records (memory_tools.py)
        writer.forgotten.append(("company", "acme", asked_at))
        await shutdown(ctx, started)
    assert '"forgotten": ["where I work"]' in (summarizer.calls[0].chat_ctx.items[-1].text_content or "")
    with Store(db.path) as s:
        assert s.state(started.preloaded.thread_id).last_visit_summary is None
        rows = s.journal_rows(started.preloaded.thread_id)
    assert [r.payload for r in rows if r.type == "error"] == [{"stage": "summary", "type": "forgotten_value"}]

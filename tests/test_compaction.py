"""In-call compaction (spec §4.8; plan C5 Part 2). The pure functions over a ChatContext first, then the Compactor
through a real AgentSession over FakeLLMs, items added the way agent_activity.py:2684-2685 adds a user turn
(`agent._chat_ctx.items.append(msg)`, then `session._conversation_item_added(msg)`) and the state change emitted as
`_update_agent_state` emits it."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from livekit.agents import Agent, AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.voice.events import AgentStateChangedEvent

from concierge import session as concierge_session
from concierge.agent import ConciergeAgent
from concierge.compaction import (
    COMPACT_MAX_WORDS,
    COMPACTION_SYSTEM,
    build_compacted,
    compact_or_fallback,
    conversation_items,
    estimate_ctx_tokens,
    fallback_truncate,
    is_summary,
    is_turn,
    make_summary_message,
    needs_compaction,
    plan_compaction,
    rebase,
    summary_text,
)
from concierge.compactor import Compactor
from concierge.contract import MEMORY_TOPIC
from concierge.erasure_hooks import forget_visitor
from concierge.knowledge import load_pack
from concierge.prompt import MEMORY_HEADER, STATIC_INSTRUCTIONS
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.fake_room import FakeRoom
from concierge.testing.sessions import METADATA, VISIT_SUMMARY, VISITOR, shutdown, stage_llms, start

INSTRUCTIONS_ID = "lk.agent_task.instructions"  # voice/generation.py:1280
NO_OPS = FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": []}))
SUMMARY = "The visitor runs a clinic and asked how Michael's voice agents handle bookings."


def instructions() -> llm.ChatMessage:
    return llm.ChatMessage(id=INSTRUCTIONS_ID, role="system", content=[STATIC_INSTRUCTIONS], created_at=0.0)


def turn(n: int, text: str | None = None) -> llm.ChatMessage:
    role = "user" if n % 2 == 0 else "assistant"
    return llm.ChatMessage(id=f"t{n}", role=role, content=[text or f"turn {n}"], created_at=float(n + 1))


def ctx_of(n_turns: int, *extra: llm.ChatItem) -> llm.ChatContext:
    return llm.ChatContext([instructions(), *[turn(n) for n in range(n_turns)], *extra])


def pair(call_id: str, at: float) -> list[llm.ChatItem]:
    return [
        llm.FunctionCall(id=f"call-{call_id}", call_id=call_id, name="remember", arguments='{"fact": "x"}',
                         created_at=at),
        llm.FunctionCallOutput(id=f"out-{call_id}", call_id=call_id, name="remember", output="Saved.",
                               is_error=False, created_at=at + 0.01),
    ]


def ids(items: list[llm.ChatItem]) -> list[str]:
    return [it.id for it in items]


# --- the trigger --------------------------------------------------------------------------------------------


def test_needs_compaction_past_24_items() -> None:
    assert not needs_compaction(ctx_of(24))
    assert needs_compaction(ctx_of(25))


def test_needs_compaction_past_4000_estimated_tokens() -> None:
    long = "word " * 700  # 3,500 characters, about 1,000 tokens each
    ctx = llm.ChatContext([instructions(), *[turn(n, long) for n in range(4)]])
    assert len(conversation_items(ctx)) == 4
    assert estimate_ctx_tokens(ctx) > 4000
    assert needs_compaction(ctx)
    assert not needs_compaction(llm.ChatContext([instructions(), *[turn(n, long) for n in range(3)]]))


def test_instructions_are_not_counted() -> None:
    huge = llm.ChatMessage(id=INSTRUCTIONS_ID, role="system", content=["x" * 20_000])
    ctx = llm.ChatContext([huge, *[turn(n) for n in range(24)]])
    assert not needs_compaction(ctx)  # 24 items and a small conversation; 20,000 instruction characters ignored


# --- the split ----------------------------------------------------------------------------------------------


def test_plan_keeps_the_last_6_turns() -> None:
    ctx = ctx_of(30)
    to_fold, to_keep = plan_compaction(ctx)
    assert ids(to_keep) == [f"t{n}" for n in range(24, 30)]
    assert ids(to_fold) == [f"t{n}" for n in range(24)]
    assert INSTRUCTIONS_ID not in ids(to_fold) + ids(to_keep)


def test_tool_call_and_output_are_both_folded_or_both_kept() -> None:
    # A pair straddling the split (its call before the 6th turn from the end, its output after) moves to the kept
    # side; a pair wholly in the head is folded with both items.
    items: list[llm.ChatItem] = [instructions()]
    for n in range(20):
        items.append(turn(n))
        if n == 3:
            items.extend(pair("early", n + 1.5))
    straddle_call, straddle_out = pair("late", 14.5)
    items.insert(ids(items).index("t14"), straddle_call)  # before t14 (the 6th turn from the end)
    items.insert(ids(items).index("t15") + 1, straddle_out)  # after t15
    to_fold, to_keep = plan_compaction(llm.ChatContext(items))
    for call_id in ("early", "late"):
        sides = {("fold" if f"{k}-{call_id}" in ids(to_fold) else "keep") for k in ("call", "out")}
        assert len(sides) == 1, call_id
    assert {"call-early", "out-early"} <= set(ids(to_fold))
    assert ids(to_keep)[0] == "call-late"
    assert [it.id for it in to_keep if is_turn(it)] == [f"t{n}" for n in range(14, 20)]


def test_nothing_to_fold_under_7_turns() -> None:
    ctx = llm.ChatContext([instructions(), llm.AgentConfigUpdate(id="cfg"), *[turn(n) for n in range(6)]])
    to_fold, to_keep = plan_compaction(ctx)
    assert to_fold == []
    assert ids(to_keep) == ["cfg", *[f"t{n}" for n in range(6)]]


def test_config_updates_in_the_folded_part_are_dropped() -> None:
    ctx = llm.ChatContext([instructions(), llm.AgentConfigUpdate(id="cfg"), *[turn(n) for n in range(10)]])
    to_fold, to_keep = plan_compaction(ctx)
    assert "cfg" not in ids(to_fold) + ids(to_keep)


# --- the summarizer call ------------------------------------------------------------------------------------


async def test_build_compacted_has_one_summary_message_with_the_llm_text() -> None:
    fake = FakeLLM([SUMMARY])
    new = await build_compacted(fake, ctx_of(30), None)
    assert ids(new.items)[0] == INSTRUCTIONS_ID
    summaries = [it for it in new.items if is_summary(it)]
    assert len(summaries) == 1
    assert SUMMARY in (summaries[0].text_content or "")
    assert summaries[0].role == "assistant"
    assert ids(new.items)[2:] == [f"t{n}" for n in range(24, 30)]
    assert len(new.items) == 8
    assert summaries[0].created_at < new.items[2].created_at
    assert summary_text(new) == SUMMARY


async def test_summary_is_capped_at_120_words() -> None:
    fake = FakeLLM([" ".join(f"w{n}" for n in range(300))])
    text = summary_text(await build_compacted(fake, ctx_of(30), None))
    assert text is not None
    assert len(text.split()) == COMPACT_MAX_WORDS
    assert text.endswith("…")


async def test_previous_summary_is_in_the_summarizers_input() -> None:
    fake = FakeLLM(["New summary."])
    await build_compacted(fake, ctx_of(30), SUMMARY)
    sent = fake.calls[0].chat_ctx.items[-1]
    assert isinstance(sent, llm.ChatMessage) and sent.role == "user"
    assert SUMMARY in (sent.text_content or "")


async def test_summarizer_ctx_is_isolated_from_the_session_prompt() -> None:
    fake = FakeLLM([SUMMARY])
    await build_compacted(fake, ctx_of(30), None)
    sent = fake.calls[0].chat_ctx
    assert [it.role for it in sent.items if isinstance(it, llm.ChatMessage)] == ["system", "user"]
    text = "\n".join(it.text_content or "" for it in sent.items if isinstance(it, llm.ChatMessage))
    assert sent.items[0].text_content == COMPACTION_SYSTEM
    assert STATIC_INSTRUCTIONS[:80] not in text
    assert MEMORY_HEADER not in text
    assert "turn 0" in text and "turn 23" in text and "turn 24" not in text  # only the folded turns
    assert fake.calls[0].tools == []


async def test_existing_summary_survives_a_second_compaction() -> None:
    # Summary of summary (livekit/agents #7721): the second call's input carries the first summary, and the result
    # still has exactly one summary message.
    fake = FakeLLM([SUMMARY, "Second summary, still about the clinic."])
    first = await build_compacted(fake, ctx_of(30), None)
    grown = llm.ChatContext([*first.items, *[turn(n) for n in range(30, 50)]])
    second = await build_compacted(fake, grown, summary_text(grown))
    assert SUMMARY in (fake.calls[1].chat_ctx.items[-1].text_content or "")
    assert [summary_text(second)] == ["Second summary, still about the clinic."]
    assert sum(is_summary(it) for it in second.items) == 1
    assert ids(second.items)[2:] == [f"t{n}" for n in range(44, 50)]


async def test_an_empty_reply_is_a_failure() -> None:
    fake = FakeLLM(["  …  "])
    new, error = await compact_or_fallback(fake, ctx_of(30))
    assert error == "EmptyCompaction"
    assert not any(is_summary(it) for it in new.items)


# --- the fallback -------------------------------------------------------------------------------------------


def test_fallback_keeps_the_last_12_turns() -> None:
    new = fallback_truncate(ctx_of(30))
    assert ids(new.items) == [INSTRUCTIONS_ID, *[f"t{n}" for n in range(18, 30)]]


def test_fallback_carries_the_existing_summary_forward() -> None:
    kept = [turn(n) for n in range(20, 40)]
    summary = make_summary_message(SUMMARY, kept)
    new = fallback_truncate(llm.ChatContext([instructions(), summary, *kept]))
    assert ids(new.items) == [INSTRUCTIONS_ID, summary.id, *[f"t{n}" for n in range(28, 40)]]
    assert summary_text(new) == SUMMARY


async def test_compact_or_fallback_times_out_within_5_5_s() -> None:
    fake = FakeLLM([FakeResponse(text=SUMMARY, delay_s=6)])
    began = time.monotonic()
    new, error = await compact_or_fallback(fake, ctx_of(30))
    assert time.monotonic() - began < 5.5
    assert error == "TimeoutError"
    assert [it.id for it in new.items if is_turn(it)] == [f"t{n}" for n in range(18, 30)]


async def test_a_provider_error_falls_back() -> None:
    new, error = await compact_or_fallback(FakeLLM([FakeResponse(error="refused")]), ctx_of(30))
    assert error == "APIStatusError"
    assert len([it for it in new.items if is_turn(it)]) == 12


# --- the rebase ---------------------------------------------------------------------------------------------


async def test_rebase_keeps_items_added_after_the_snapshot() -> None:
    snapshot = llm.ChatContext([instructions(), llm.AgentConfigUpdate(id="cfg"), *[turn(n) for n in range(30)]])
    compacted = await build_compacted(FakeLLM([SUMMARY]), snapshot, None)
    snapshot_ids = set(ids(snapshot.items))
    folded = snapshot_ids - set(ids(compacted.items))
    assert "cfg" in folded  # dropped from the folded part: must not come back as "new"
    current = llm.ChatContext([*snapshot.items, turn(30), *pair("new", 31.5)])
    new = rebase(compacted, snapshot_ids, folded, current)
    assert new is not None
    assert ids(new.items)[-3:] == ["t30", "call-new", "out-new"]
    assert "cfg" not in ids(new.items)
    assert sum(is_summary(it) for it in new.items) == 1


async def test_rebase_drops_a_compaction_when_the_context_was_rewritten() -> None:
    snapshot = ctx_of(30)
    compacted = await build_compacted(FakeLLM([SUMMARY]), snapshot, None)
    folded = set(ids(snapshot.items)) - set(ids(compacted.items))
    rewritten = llm.ChatContext([instructions(), *[turn(n) for n in range(20, 30)]])
    assert rebase(compacted, set(ids(snapshot.items)), folded, rewritten) is None


@pytest.mark.parametrize("n", [0, 1, 6])
async def test_nothing_to_fold_makes_no_llm_call(n: int) -> None:
    fake = FakeLLM([])
    new = await build_compacted(fake, ctx_of(n), None)
    assert fake.calls == []
    assert ids(new.items) == ids(ctx_of(n).items)


# --- the Compactor through a real AgentSession --------------------------------------------------------------


def add_turns(session: AgentSession, agent: Agent, numbers: range) -> None:
    """User/assistant turns as 1.8 adds them (no await between them)."""
    for n in numbers:
        msg = llm.ChatMessage(id=f"t{n}", role="user" if n % 2 == 0 else "assistant", content=[f"turn {n}"])
        agent._chat_ctx.items.append(msg)
        session._conversation_item_added(msg)


def listening(session: AgentSession, old: str = "speaking") -> None:
    session.emit("agent_state_changed", AgentStateChangedEvent(old_state=old, new_state="listening"))


async def until(pred: Callable[[], bool], timeout_s: float = 6.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not pred():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.01)


def turn_ids(agent: Agent) -> list[str]:
    return [it.id for it in agent.chat_ctx.items if is_turn(it)]


@asynccontextmanager
async def live(summarizer: FakeLLM, **kwargs: Any) -> AsyncIterator[tuple[AgentSession, Agent, Compactor]]:
    session = AgentSession(llm=FakeLLM([]))
    agent = ConciergeAgent(load_pack())
    compactor = Compactor(agent, session, lambda: summarizer, **kwargs)
    session.on("conversation_item_added", compactor.on_item_added)
    session.on("agent_state_changed", compactor.on_state_changed)
    await session.start(agent)
    try:
        yield session, agent, compactor
    finally:
        await compactor.aclose()
        await session.aclose()


async def test_thirty_turns_compact_at_the_next_listening_transition(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 60)  # the turns are journaled at the flush
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        session, compactor = started.session, started.compactor
        assert compactor is not None and started.preloaded is not None
        agent = session.current_agent
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        assert len(agent.chat_ctx.items) == 33  # not applied yet: instructions, config update, greeting, 30 turns
        listening(session)
        await until(lambda: compactor.applied == 1)
        items = agent.chat_ctx.items
        assert len(items) <= 8
        summaries = [it for it in items if is_summary(it)]
        assert len(summaries) == 1 and VISIT_SUMMARY in (summaries[0].text_content or "")
        assert turn_ids(agent) == [f"t{n}" for n in range(24, 30)]
        assert len(session.history.items) >= 32  # the session's own history keeps every item
        await shutdown(ctx, started)
    with Store(db.path) as reopened:  # the shutdown closed it
        rows = reopened.journal_rows(started.preloaded.thread_id)
    journaled = [r.payload["turn_id"] for r in rows if r.type in ("user_turn", "agent_turn")]
    assert set(journaled) >= {f"t{n}" for n in range(30)}  # nothing lost
    assert len(journaled) == 31  # and the greeting
    (compacted,) = [r.payload for r in rows if r.type == "compacted"]
    assert compacted["items_before"] == 33 and compacted["items_after"] == len(items)
    assert compacted["tokens_after"] < compacted["tokens_before"]
    assert compacted["fallback"] is False
    assert summarizer.calls[0].chat_ctx.items[0].text_content == COMPACTION_SYSTEM


async def test_the_visit_summary_after_a_compaction_reads_every_turn(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM
) -> None:
    """Compaction edits only the agent's context: the session-end summary reads the writer's history, folded turns
    included (plan C5, 'Nothing is lost')."""
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        session, compactor = started.session, started.compactor
        assert compactor is not None
        agent = session.current_agent
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        listening(session)
        await until(lambda: compactor.applied == 1)
        assert "t0" not in turn_ids(agent)  # folded out of the agent's context
        await shutdown(ctx, started)
    compaction_call, visit_call = summarizer.calls
    assert compaction_call.chat_ctx.items[0].text_content == COMPACTION_SYSTEM
    visit_input = visit_call.chat_ctx.items[-1].text_content or ""
    assert all(f'"turn {n}"' in visit_input for n in range(30))


async def test_turns_added_while_compacting_trigger_another_compaction() -> None:
    replies = iter(["First summary.", "Second summary."])

    def respond(chat_ctx: llm.ChatContext) -> str:
        return next(replies)

    fake = FakeLLM(respond=respond)
    async with live(fake) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        for n in range(30, 50):  # with awaits: none of these are in the first snapshot
            add_turns(session, agent, range(n, n + 1))
            await asyncio.sleep(0)
        listening(session)
        await until(lambda: compactor.applied == 1)
        assert turn_ids(agent) == [f"t{n}" for n in range(24, 50)]  # the 20 new turns were kept by the rebase
        await until(lambda: compactor.ready is not None)  # still past the trigger: a second compaction
        listening(session)
        await until(lambda: compactor.applied == 2)
        assert turn_ids(agent) == [f"t{n}" for n in range(44, 50)]
        assert summary_text(agent.chat_ctx) == "Second summary."
        assert "First summary." in (fake.calls[1].chat_ctx.items[-1].text_content or "")  # carried forward
        assert sum(is_summary(it) for it in agent.chat_ctx.items) == 1


async def test_compaction_is_not_applied_before_listening() -> None:
    async with live(FakeLLM([SUMMARY])) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        for state in ("thinking", "speaking"):
            session.emit("agent_state_changed", AgentStateChangedEvent(old_state="listening", new_state=state))
        await asyncio.sleep(0.05)
        assert compactor.applied == 0 and len(turn_ids(agent)) == 30
        session._user_state = "speaking"  # the visitor talks over: a preemptive reply may run on the old context
        listening(session)
        await asyncio.sleep(0.05)
        assert compactor.applied == 0 and compactor.ready is not None
        session._user_state = "listening"
        listening(session)
        await until(lambda: compactor.applied == 1)


async def test_items_added_after_the_snapshot_are_kept() -> None:
    async with live(FakeLLM([SUMMARY])) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        add_turns(session, agent, range(30, 32))
        listening(session)
        await until(lambda: compactor.applied == 1)
        assert turn_ids(agent) == [f"t{n}" for n in range(24, 32)]


async def test_tool_pair_inserted_before_an_apply_lands_by_created_at() -> None:
    # An interrupted reply goes to listening with its tool still running; the call and its output land later, by
    # created_at, possibly before turns added since (agent_activity.py:4057).
    async with live(FakeLLM([SUMMARY])) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        add_turns(session, agent, range(30, 31))
        t27, t28 = (agent.chat_ctx.get_by_id(f"t{n}") for n in (27, 28))
        assert t27 is not None and t28 is not None and t27.created_at < t28.created_at
        late = pair("late", (t27.created_at + t28.created_at) / 2)
        late[1].created_at = late[0].created_at
        agent._chat_ctx.insert(late)  # between t27 and t28, both in the snapshot's kept tail
        listening(session)
        await until(lambda: compactor.applied == 1)
        tail = [it.id for it in agent.chat_ctx.items][-7:]
        assert tail == ["t26", "t27", "call-late", "out-late", "t28", "t29", "t30"]


async def test_slow_summarizer_falls_back_within_5_5_s(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    slow = FakeLLM([FakeResponse(text=SUMMARY, delay_s=6), VISIT_SUMMARY])
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=FakeLLM([NO_OPS] * 4), summarizer=slow))
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 60)
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        compactor = started.compactor
        assert compactor is not None and started.preloaded is not None
        agent = started.session.current_agent
        began = time.monotonic()
        add_turns(started.session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        assert time.monotonic() - began < 5.5
        listening(started.session)
        await until(lambda: compactor.applied == 1)
        assert turn_ids(agent) == [f"t{n}" for n in range(18, 30)]  # the last 12 turns
        assert not any(is_summary(it) for it in agent.chat_ctx.items)
        await shutdown(ctx, started)
    with Store(db.path) as reopened:  # the shutdown closed it
        rows = reopened.journal_rows(started.preloaded.thread_id)
    assert [r.payload for r in rows if r.type == "error"] == [{"stage": "compaction", "type": "TimeoutError"}]
    (compacted,) = [r.payload for r in rows if r.type == "compacted"]
    assert compacted["fallback"] is True


async def test_forget_me_cancels_a_running_compaction(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    slow = FakeLLM([FakeResponse(text=SUMMARY, delay_s=3)])
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=FakeLLM([]), summarizer=slow))
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 60)
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        compactor, writer = started.compactor, started.writer
        assert compactor is not None and writer is not None
        agent = started.session.current_agent
        add_turns(started.session, agent, range(30))
        await until(lambda: len(slow.calls) == 1)  # the summarizer call is in flight
        assert await forget_visitor(writer, VISITOR) is True
        assert compactor.disabled and compactor.ready is None
        await asyncio.sleep(0.05)
        assert not compactor._tasks  # the 3 s call was cancelled, not left to finish and be dropped (review B-I1)
        add_turns(started.session, agent, range(30, 60))  # however many items follow
        listening(started.session)
        await asyncio.sleep(0.1)
        assert len(slow.calls) == 1 and compactor.applied == 0
        assert len(turn_ids(agent)) == 61  # the greeting and 60 turns: the conversation goes on with its context
        await shutdown(ctx, started)
    assert len(slow.calls) == 1  # no visit summary either
    with Store(db.path) as reopened:
        assert reopened.thread_for(VISITOR) is None


async def test_shutdown_cancels_a_running_compaction(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    compacting_when_called: list[bool] = []
    holder: list[Compactor] = []

    class Recording(FakeLLM):
        def chat(self, **kwargs: Any) -> Any:  # noqa: ANN401
            compacting_when_called.append(bool(holder and holder[0]._tasks))
            return super().chat(**kwargs)

    slow = Recording([FakeResponse(text=SUMMARY, delay_s=4), VISIT_SUMMARY])
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=FakeLLM([NO_OPS] * 4), summarizer=slow))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        compactor = started.compactor
        holder.append(compactor)
        assert compactor is not None and started.preloaded is not None
        add_turns(started.session, started.session.current_agent, range(30))
        await until(lambda: len(slow.calls) == 1)
        began = time.monotonic()
        await shutdown(ctx, started)
        assert time.monotonic() - began < 2  # the 4 s call was cancelled, not waited for
    assert compacting_when_called == [True, False]  # cancelled before the visit summary's call, not after
    assert compactor.disabled and compactor.ready is None and compactor.applied == 0
    with Store(db.path) as reopened:  # the shutdown closed it
        rows = reopened.journal_rows(started.preloaded.thread_id)
    assert not [r for r in rows if r.type == "compacted" or r.payload.get("stage") == "compaction"]
    assert [r.type for r in rows if r.type == "summary_written"] == ["summary_written"]  # the visit summary ran


async def test_compaction_runs_without_memory(fakes: list[FakeLLM], summarizer: FakeLLM) -> None:
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, None)
        compactor = started.compactor
        assert compactor is not None and started.writer is None
        agent = started.session.current_agent
        add_turns(started.session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        listening(started.session)
        await until(lambda: compactor.applied == 1)
        assert len(agent.chat_ctx.items) <= 8
        await shutdown(ctx, started)
    assert len(summarizer.calls) == 1  # the compaction; no store, so no visit summary


async def test_item_handler_returns_fast_while_the_summarizer_sleeps() -> None:
    async with live(FakeLLM([FakeResponse(text=SUMMARY, delay_s=5)])) as (session, agent, compactor):
        add_turns(session, agent, range(23))  # 24 conversation items with the config update: not yet
        assert compactor._task is None
        msg = llm.ChatMessage(id="t23", role="assistant", content=["turn 23"])
        agent._chat_ctx.items.append(msg)
        began = time.perf_counter()
        session._conversation_item_added(msg)  # this one starts the compaction
        assert time.perf_counter() - began < 0.05
        assert compactor._task is not None
        await until(lambda: len(compactor._llm.calls) == 1 if isinstance(compactor._llm, FakeLLM) else False)
        began = time.perf_counter()
        add_turns(session, agent, range(24, 30))  # while the 5 s call sleeps
        assert time.perf_counter() - began < 0.05
        assert compactor.ready is None


async def test_a_summarizer_that_cannot_be_built_falls_back() -> None:
    def missing_key() -> llm.LLM:
        raise KeyError("ANTHROPIC_API_KEY")

    session = AgentSession(llm=FakeLLM([]))
    agent = ConciergeAgent(load_pack())
    journal: list[tuple[str, dict[str, Any]]] = []

    async def write(kind: str, payload: dict[str, Any]) -> None:
        journal.append((kind, payload))

    compactor = Compactor(agent, session, missing_key, journal=write)
    session.on("conversation_item_added", compactor.on_item_added)
    session.on("agent_state_changed", compactor.on_state_changed)
    await session.start(agent)
    try:
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        listening(session)
        await until(lambda: compactor.applied == 1)
        assert len(turn_ids(agent)) == 12
        assert journal[0] == ("error", {"stage": "compaction", "type": "KeyError"})
        assert journal[1][0] == "compacted" and journal[1][1]["fallback"] is True
    finally:
        await compactor.aclose()
        await session.aclose()


async def test_tool_pair_inserted_after_an_apply_is_kept() -> None:
    # The interrupted-tool path: the agent went to listening, the compaction was applied, then the call and its
    # output land by created_at in the compacted context; the next compaction keeps the pair whole.
    async with live(FakeLLM([SUMMARY, "Second summary."])) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        listening(session)
        await until(lambda: compactor.applied == 1)
        t28 = agent.chat_ctx.get_by_id("t28")
        assert t28 is not None
        late = pair("late", t28.created_at + 1e-6)
        late[1].created_at = late[0].created_at
        agent._chat_ctx.insert(late)  # what agent_activity.py:4057 does once the tool returns
        add_turns(session, agent, range(30, 52))
        await until(lambda: compactor.ready is not None)
        listening(session)
        await until(lambda: compactor.applied == 2)
        ids_now = [it.id for it in agent.chat_ctx.items]
        assert ("call-late" in ids_now) == ("out-late" in ids_now)
        assert "call-late" not in ids_now  # folded with t28, both items
        assert summary_text(agent.chat_ctx) == "Second summary."
        folded_turns = fakes_rendered(compactor)
        assert '"tool_call": "remember"' in folded_turns and '"tool_result": "remember"' in folded_turns


def fakes_rendered(compactor: Compactor) -> str:
    fake = compactor._llm
    assert isinstance(fake, FakeLLM)
    return fake.calls[-1].chat_ctx.items[-1].text_content or ""


async def test_apply_waits_when_the_agent_is_not_listening_anymore() -> None:
    # The listening event and the apply task are one loop turn apart: _apply re-reads the session's state.
    async with live(FakeLLM([SUMMARY])) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        listening(session)
        session._agent_state = "thinking"  # before the apply task runs
        await asyncio.sleep(0.05)
        assert compactor.applied == 0 and compactor.ready is not None
        session._agent_state = "listening"
        listening(session)
        await until(lambda: compactor.applied == 1)


def test_fallback_keeps_a_tool_pair_straddling_its_split_whole() -> None:
    items: list[llm.ChatItem] = [instructions(), *[turn(n) for n in range(20)]]
    call, out = pair("mid", 0)
    items.insert(ids(items).index("t8"), call)  # before t8, the 12th turn from the end
    items.insert(ids(items).index("t8") + 1, out)  # after t8
    new = fallback_truncate(llm.ChatContext(items))
    assert ids(new.items)[1:4] == ["call-mid", "t8", "out-mid"]


async def test_an_unproductive_attempt_waits_for_more_turns() -> None:
    # 8 turns with 9 tool pairs: past 24 items, but a failing provider's fallback (the last 12 turns) drops nothing.
    # The next attempt waits for 6 more turns instead of calling the summarizer on every turn.
    fake = FakeLLM([FakeResponse(error="overloaded")] * 3)
    async with live(fake) as (session, agent, compactor):
        for k in range(9):
            agent._chat_ctx.items.extend(pair(f"p{k}", time.time()))
        add_turns(session, agent, range(8))
        await until(lambda: len(fake.calls) == 1 and compactor._task is None)
        assert compactor.ready is None
        add_turns(session, agent, range(8, 13))
        await asyncio.sleep(0.05)
        assert len(fake.calls) == 1
        add_turns(session, agent, range(13, 14))  # 14 turns: 8 + KEEP_TURNS
        await until(lambda: len(fake.calls) == 2 and compactor._task is None)
        assert compactor.ready is not None  # now the fallback drops the 2 oldest turns


async def test_the_erase_hook_is_held_weakly() -> None:
    import gc
    import weakref

    from concierge.erasure_hooks import _hooks, add_erase_hook, cancel_pending

    class Writer:  # stands in for a MemoryWriter: the registry only needs cancel_all
        def cancel_all(self) -> None:
            pass

    class Holder:
        def __init__(self, writer: Writer) -> None:
            self.writer = writer  # like the Compactor's journal partial and erased lambda
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    writer = Writer()
    holder = Holder(writer)
    add_erase_hook(writer, holder.cancel)  # type: ignore[arg-type]
    cancel_pending(writer)  # type: ignore[arg-type]
    assert holder.cancelled and writer not in _hooks  # run once, then dropped
    add_erase_hook(writer, holder.cancel)  # type: ignore[arg-type]
    alive = weakref.ref(writer)
    del writer, holder
    gc.collect()
    assert alive() is None  # no cycle through the registry's value keeps the key alive


async def test_an_applied_compaction_publishes_the_memory(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V2-05: one more concierge.memory after the apply, saying so in about_agent.working (plan V2 "Publish points")."""
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 60)  # no merge, so no merge publish
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        compactor, agent = started.compactor, started.session.current_agent
        assert compactor is not None
        sends = lambda: room.local_participant.sent_on(MEMORY_TOPIC)  # noqa: E731
        (first,) = sends()
        working = json.loads(first)["about_agent"]["working"]  # built at the start, before the greeting landed
        assert (working["compacted"], working["compactions"]) == (False, 0) and working["items"] >= 1
        add_turns(started.session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        await asyncio.sleep(0.05)
        assert len(sends()) == 1  # ready is not applied: nothing yet
        listening(started.session)
        await until(lambda: len(sends()) == 2)
        body = json.loads(sends()[-1])
        assert compactor.applied == 1
        working = body["about_agent"]["working"]
        assert working["compacted"] is True and working["compactions"] == 1
        assert working["items"] == len(agent.chat_ctx.items) <= 8  # the compacted context
        await shutdown(ctx, started)


async def test_a_failing_on_compacted_never_breaks_the_apply(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        raise RuntimeError("publisher gone: Acme")

    async with live(FakeLLM([FakeResponse(text=SUMMARY)]), on_compacted=boom) as (session, agent, compactor):
        add_turns(session, agent, range(30))
        await until(lambda: compactor.ready is not None)
        listening(session)
        await until(lambda: compactor.applied == 1)
        assert len(turn_ids(agent)) == 6
    assert "wasn't published (RuntimeError)" in caplog.text and "Acme" not in caplog.text  # by type only

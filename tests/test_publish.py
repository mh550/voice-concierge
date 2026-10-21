"""Publishing `concierge.memory` (spec §6; plan C6 "publish", "MemoryPublisher and when concierge.memory is sent")."""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from livekit import rtc
from livekit.agents.testing import fake_job_context
from pydantic import BaseModel

from concierge import session as concierge_session
from concierge.contract import (
    MAX_BODY_BYTES,
    MEMORY_TOPIC,
    METRICS_TOPIC,
    AboutAgent,
    Cache,
    Knowledge,
    MemoryEvent,
    MemoryPayload,
    Working,
    body_bytes,
    build_memory_payload,
    empty_memory_payload,
    trim_to_fit,
)
from concierge.models import SET_ITEM_CAP, SET_MAX_ITEMS, SINGLE_CAP, SLOTS, AddFact
from concierge.prompt import MEMORY_BLOCK_MAX_CHARS
from concierge.publish import MemoryPublisher, PayloadTooLarge, publish
from concierge.store import Store
from concierge.summary import SUMMARY_MAX_CHARS
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.fake_room import FakeRoom
from concierge.testing.sessions import METADATA, VISITOR, shutdown, start


class Text(BaseModel):
    text: str


async def until(cond: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


def emit_add(slot: str, value: str, turn_id: str) -> FakeResponse:
    op = {"op": "ADD", "slot": slot, "value": value, "fact_id": None, "confidence": None, "turn_id": turn_id,
          "reason": None}
    return FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": [op]}))


def named(name: str) -> MemoryPayload:
    return empty_memory_payload().model_copy(update={"summary": name})


async def test_publish_sends_the_json_body_on_the_topic() -> None:
    room = FakeRoom()
    payload = empty_memory_payload()
    await publish(room, MEMORY_TOPIC, payload)
    assert room.local_participant.sent == [(payload.model_dump_json(), "concierge.memory")]


async def test_publish_raises_payload_too_large_over_15_kib() -> None:
    room = FakeRoom()
    wrapper = len(Text(text="").model_dump_json())
    await publish(room, MEMORY_TOPIC, Text(text="a" * (MAX_BODY_BYTES - wrapper)))  # exactly 15 KiB: sent
    secret = "語" * 6000  # 6,000 characters (under 15,360) but 18,000 bytes
    with pytest.raises(PayloadTooLarge) as caught:
        await publish(room, MEMORY_TOPIC, Text(text=secret))
    assert len(room.local_participant.sent) == 1
    assert "concierge.memory" in str(caught.value) and "語" not in str(caught.value)  # the size, never the body
    assert caught.value.size == 6000 * 3 + wrapper


async def test_a_failed_send_is_logged_and_dropped(caplog: pytest.LogCaptureFixture) -> None:
    room = FakeRoom()
    room.local_participant.fail_with = rtc.StreamError("the room is gone")
    publisher = MemoryPublisher(room, lambda: asyncio.sleep(0, named("Ada")))
    with caplog.at_level(logging.WARNING, logger="concierge.publish"):
        publisher.schedule()
        await publisher.idle()
    assert room.local_participant.sent == []
    assert "StreamError" in caplog.text and "Ada" not in caplog.text and "room is gone" not in caplog.text
    room.local_participant.fail_with = None
    publisher.schedule()  # the next merge still publishes
    await publisher.idle()
    assert len(room.local_participant.sent) == 1


async def test_a_failed_build_is_logged_and_dropped(caplog: pytest.LogCaptureFixture) -> None:
    async def failing() -> MemoryPayload:
        raise RuntimeError("Ada's value")

    room = FakeRoom()
    publisher = MemoryPublisher(room, failing)
    with caplog.at_level(logging.WARNING, logger="concierge.publish"):
        publisher.schedule()
        await publisher.idle()
    assert room.local_participant.sent == [] and "RuntimeError" in caplog.text and "Ada" not in caplog.text


async def test_sends_go_out_in_the_order_they_were_scheduled() -> None:
    room = FakeRoom()
    delays = iter([0.1, 0.0])
    count = iter(range(1, 3))

    async def build() -> MemoryPayload:
        n = next(count)
        await asyncio.sleep(next(delays))
        return named(f"payload {n}")

    publisher = MemoryPublisher(room, build)
    publisher.schedule()
    publisher.schedule()
    await publisher.idle()
    sent = room.local_participant.sent_on(MEMORY_TOPIC)
    assert [json.loads(t)["summary"] for t in sent] == ["payload 1", "payload 2"]  # the slow first build went first


async def test_no_memory_publish_after_the_publisher_is_closed() -> None:
    room = FakeRoom()
    publisher = MemoryPublisher(room, lambda: asyncio.sleep(0.5, named("late")))
    publisher.schedule()  # in flight: cancelled by aclose
    await asyncio.sleep(0.05)
    await publisher.aclose()
    assert publisher.closed
    publisher.schedule()
    await publisher.final(empty_memory_payload())
    await asyncio.sleep(0.6)
    assert room.local_participant.sent == []


async def test_final_is_the_last_memory_the_page_sees() -> None:
    """A build in flight when "Forget me" lands is dropped: the empty body is the last one sent (plan C6 I5)."""
    room = FakeRoom()
    publisher = MemoryPublisher(room, lambda: asyncio.sleep(0.2, named("Ada")))
    publisher.schedule()
    await asyncio.sleep(0.05)
    await publisher.final(empty_memory_payload())
    publisher.schedule()  # a merge after the erase: nothing
    await publisher.idle()
    await asyncio.sleep(0.3)
    (sent,) = room.local_participant.sent_on(MEMORY_TOPIC)
    assert json.loads(sent)["visitor"] == {"name": None, "visits": 0} and json.loads(sent)["summary"] is None


async def test_final_waiting_on_a_send_sends_nothing_after_aclose() -> None:
    """The room is gone once the shutdown closes the publisher: a "Forget me" queued behind a send stays quiet
    (review C6-02 I1)."""
    room = FakeRoom()
    publisher = MemoryPublisher(room, lambda: asyncio.sleep(0.2, named("Ada")))
    publisher.schedule()
    await asyncio.sleep(0.05)
    final = asyncio.create_task(publisher.final(empty_memory_payload()))
    await asyncio.sleep(0.01)  # final now waits on the lock
    await publisher.aclose()
    await asyncio.wait_for(final, 0.5)
    assert room.local_participant.sent == []


# --- through start_session (a real AgentSession over FakeLLMs, a FakeRoom as ctx.room) ----------------------------


async def test_session_start_publishes_memory_once(
    db: Store, fakes: list[FakeLLM], memory_validator: Draft202012Validator
) -> None:
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        (sent,) = room.local_participant.sent_on(MEMORY_TOPIC)
        memory_validator.validate(json.loads(sent))
        assert json.loads(sent)["visitor"] == {"name": None, "visits": 1}
        before = len(room.local_participant.sent)
        await shutdown(ctx, started)
    assert len(room.local_participant.sent) == before  # nothing at shutdown: the room is gone by then (plan C6)


async def test_the_start_memory_is_v2_and_validates(
    db: Store, fakes: list[FakeLLM], memory_validator: Draft202012Validator
) -> None:
    tid = db.get_or_create_thread(VISITOR).id  # a returning visitor, so the profile has something to repeat
    db.add_fact(tid, AddFact(slot="company", value="Acme", source="user_said", channel="voice", turn_id="t1"))
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        (sent,) = room.local_participant.sent_on(MEMORY_TOPIC)
        body = json.loads(sent)
        memory_validator.validate(body)
        assert body["v"] == 2 and body["retention_days"] == 30
        assert [f["value"] for f in body["about_visitor"]["profile"]] == ["Acme"]
        assert body["about_visitor"]["profile"] == body["facts"]
        await shutdown(ctx, started)


async def test_a_session_without_memory_publishes_the_empty_payload(
    fakes: list[FakeLLM], memory_validator: Draft202012Validator
) -> None:
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, None)
        (sent,) = room.local_participant.sent_on(MEMORY_TOPIC)
        memory_validator.validate(json.loads(sent))
        assert json.loads(sent)["facts"] == [] and json.loads(sent)["visitor"]["visits"] == 0
        await shutdown(ctx, started)


async def test_two_memory_publishes_after_one_merged_extraction(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM, monkeypatch: pytest.MonkeyPatch,
    memory_validator: Draft202012Validator,
) -> None:
    """The step's test: the start publish, then one after the merge, both valid, the second with the new fact."""
    extractors: list[FakeLLM] = []

    def build_llm(stage: str, settings: Any = None) -> FakeLLM:  # noqa: ANN401
        if stage == "summarizer":
            return summarizer
        assert started.writer is not None
        (turn,) = [t for t in started.writer.history if t.role == "user"]
        extractors.append(FakeLLM([emit_add("company", "Acme", turn.turn_id)]))
        return extractors[-1]

    monkeypatch.setattr(concierge_session, "build_llm", build_llm)
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 0.05)
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        await started.session.run(user_input="I work at Acme.")
        await until(lambda: len(room.local_participant.sent_on(MEMORY_TOPIC)) == 2, 3)
        await shutdown(ctx, started)
    assert len(extractors) == 1 and len(extractors[0].calls) == 1
    sent = [json.loads(t) for t in room.local_participant.sent_on(MEMORY_TOPIC)]
    assert len(sent) == 2 and {t for _, t in room.local_participant.sent} == {MEMORY_TOPIC, METRICS_TOPIC}
    for body in sent:
        memory_validator.validate(body)
    assert sent[0]["facts"] == []
    assert [(f["slot"], f["value"]) for f in sent[1]["facts"]] == [("company", "Acme")]
    with Store(db.path) as s:
        thread = s.thread_for(VISITOR)
        assert thread is not None and [f.id for f in s.valid_facts(thread.id)] == [sent[1]["facts"][0]["id"]]


async def test_a_merge_in_the_shutdown_flush_publishes_nothing(
    db: Store, fakes: list[FakeLLM], summarizer: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final extraction merges after the publisher is closed (the room is disconnected by then): no send."""

    def build_llm(stage: str, settings: Any = None) -> FakeLLM:  # noqa: ANN401
        if stage == "summarizer":
            return summarizer
        assert started.writer is not None
        (turn,) = [t for t in started.writer.history if t.role == "user"]
        return FakeLLM([emit_add("company", "Acme", turn.turn_id)])

    monkeypatch.setattr(concierge_session, "build_llm", build_llm)
    monkeypatch.setattr(concierge_session, "EXTRACTION_DEBOUNCE_S", 60.0)  # only the flush extracts
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        await started.session.run(user_input="I work at Acme.")
        await until(lambda: len(room.local_participant.sent_on(METRICS_TOPIC)) == 2, 3)  # sent before the shutdown
        before = len(room.local_participant.sent)
        await shutdown(ctx, started)
    with Store(db.path) as s:
        thread = s.thread_for(VISITOR)
        assert thread is not None and [f.value for f in s.valid_facts(thread.id)] == ["Acme"]  # the flush merged
    assert len(room.local_participant.sent_on(MEMORY_TOPIC)) == 1 and len(room.local_participant.sent) == before


# --- the size rule (V2-05; plan V2 "The size rule") -----------------------------------------------------------------

V1_KEYS = ("visitor", "facts", "summary", "updated_at")
SINGLE_SLOTS = [slot for slot, spec in SLOTS.items() if spec.kind == "single"]
SET_SLOTS = [slot for slot, spec in SLOTS.items() if spec.kind == "set"]


def maximal_store(  # noqa: ANN401 (FakeClock)
    store: Store, clock: Any, ch: str = "a", summary_ch: str = "s", episode_ch: str | None = None  # noqa: ANN401
) -> str:
    """Every single slot at its 120-character cap, every set slot 8 items at the 60-character cap (the maximal valid
    fact list: 20 facts), a 400-character last-visit summary and 5 completed visits with 400-character summaries."""
    tid = store.get_or_create_thread(VISITOR).id
    n = 0
    for slot in [*SINGLE_SLOTS, *(s for s in SET_SLOTS for _ in range(SET_MAX_ITEMS))]:
        n += 1
        cap = SINGLE_CAP if slot in SINGLE_SLOTS else SET_ITEM_CAP
        store.add_fact(tid, AddFact(slot=slot, value=f"{n:02d}" + ch * (cap - 2), source="user_said",
                                    channel="voice", turn_id=f"t{n}"))
        clock.advance(1)
    assert len(store.valid_facts(tid)) == len(SINGLE_SLOTS) + SET_MAX_ITEMS * len(SET_SLOTS) == 20
    store.set_summary(tid, None, summary_ch * SUMMARY_MAX_CHARS)
    for visit in range(1, 6):
        store.begin_visit(tid, visit, clock())
        store.end_visit(tid, visit, clock() + 1, f"{visit}" + (episode_ch or ch) * (SUMMARY_MAX_CHARS - 1))
    return tid


def maximal_events(ch: str = "e") -> list[MemoryEvent]:
    return [MemoryEvent(ts="2026-10-21T09:15:02.123Z", type="fact_added", detail=f"{n:02d}" + ch * 118)
            for n in range(12)]  # newest first: 00 is the newest


def maximal_about_agent(ch: str = "x") -> AboutAgent:
    return AboutAgent(
        knowledge=Knowledge(words=99_999, est_tokens=99_999, sources_commit="0" * 40,
                            sections=[f"{n:02d}" + ch * 78 for n in range(20)]),
        instructions_est_tokens=99_999, memory_block_chars=MEMORY_BLOCK_MAX_CHARS,
        working=Working(items=99_999, est_tokens=99_999, compacted=True, compactions=99),
        cache=Cache(cached_share=0.123456789),
    )


def v1_facts(payload: MemoryPayload) -> list[Any]:
    """The facts a v1 agent would send for the same store: the body without its v2 keys, trimmed to the cap."""
    v1 = payload.model_copy(update={"v": None, "about_visitor": None, "about_agent": None, "retention_days": None})
    return trim_to_fit(v1, MAX_BODY_BYTES).facts


def test_the_largest_allowed_body_fits(store: Store, clock: Any, memory_validator: Draft202012Validator) -> None:  # noqa: ANN401
    """V2 review I1: the oldest events go first, and a v1 page still gets every fact."""
    tid = maximal_store(store, clock)
    events, agent = maximal_events(), maximal_about_agent()
    uncapped = build_memory_payload(store, tid, max_bytes=None, about_agent=agent, events=events)
    assert body_bytes(uncapped) > MAX_BODY_BYTES  # the plan's measured worst case, 16,671 bytes, is over
    payload = build_memory_payload(store, tid, about_agent=agent, events=events)
    assert body_bytes(payload) <= 15 * 1024
    memory_validator.validate(json.loads(payload.model_dump_json()))
    assert payload.about_visitor is not None and uncapped.about_visitor is not None
    assert payload.facts == uncapped.facts == v1_facts(uncapped) and len(payload.facts) == 20
    assert payload.about_visitor.profile == payload.facts and len(payload.about_visitor.episodes) == 5
    kept = payload.about_visitor.events
    assert 0 < len(kept) < 12 and kept == events[: len(kept)]  # the oldest events went, only those it had to
    for key in ("visitor", "summary", "v", "about_agent", "retention_days"):
        assert getattr(payload, key) == getattr(uncapped, key), key


@pytest.mark.parametrize("ch", ["🙂", "𝄞"])
def test_a_multibyte_body_trims_events_then_episodes_then_profile(store: Store, clock: Any, ch: str) -> None:  # noqa: ANN401
    """4-byte characters: every event goes, then the episodes, oldest first, then the oldest of profile; the v1 facts
    stay as a v1 agent would send them (V2 review I1, D19)."""
    tid = maximal_store(store, clock, ch)
    events, agent = maximal_events(ch), maximal_about_agent()  # the section titles are the pack's own
    uncapped = build_memory_payload(store, tid, max_bytes=None, about_agent=agent, events=events)
    payload = build_memory_payload(store, tid, about_agent=agent, events=events)
    assert body_bytes(payload) <= MAX_BODY_BYTES
    about, full = payload.about_visitor, uncapped.about_visitor
    assert about is not None and full is not None
    assert payload.facts == uncapped.facts == v1_facts(uncapped) and len(payload.facts) == 20
    assert about.events == [] and about.episodes == []
    assert 0 < len(about.profile) < 20 and about.profile == full.profile[-len(about.profile):]  # the newest kept
    probe = payload.model_copy(update={"about_visitor": about.model_copy(
        update={"profile": full.profile[-len(about.profile) - 1:]})})
    assert body_bytes(probe) > MAX_BODY_BYTES  # it dropped only what it had to


def test_a_multibyte_body_drops_only_the_oldest_episodes_it_must(store: Store, clock: Any) -> None:  # noqa: ANN401
    tid = maximal_store(store, clock, episode_ch="🙂")
    events, agent = maximal_events("🙂"), maximal_about_agent()
    full = build_memory_payload(store, tid, max_bytes=None, about_agent=agent, events=events).about_visitor
    payload = build_memory_payload(store, tid, about_agent=agent, events=events)
    assert payload.about_visitor is not None and full is not None and len(payload.facts) == 20
    kept = payload.about_visitor.episodes
    assert payload.about_visitor.events == [] and payload.about_visitor.profile == payload.facts
    assert 0 < len(kept) < 5 and kept == full.episodes[: len(kept)]  # newest first: the oldest went
    assert [e.visit for e in kept] == list(range(5, 5 - len(kept), -1))


def test_the_trimmer_never_drops_a_v1_key(store: Store, clock: Any) -> None:  # noqa: ANN401
    """A body that can't fit (the about_agent alone is over): every fact, event and episode goes, no key does."""
    tid = maximal_store(store, clock)
    huge = maximal_about_agent().model_copy(update={"knowledge": Knowledge(
        words=1, est_tokens=1, sources_commit="abc1234", sections=["y" * 100] * 200)})
    uncapped = build_memory_payload(store, tid, max_bytes=None, about_agent=huge, events=maximal_events())
    payload = build_memory_payload(store, tid, about_agent=huge, events=maximal_events())
    dumped, full = payload.model_dump(), uncapped.model_dump()
    assert list(dumped) == list(full)  # every key is still there
    for key in ("visitor", "summary", "v", "about_agent", "retention_days"):
        assert dumped[key] == full[key], key
    assert dumped["facts"] == [] and dumped["about_visitor"] == {"profile": [], "episodes": [], "events": []}
    assert all(key in dumped for key in V1_KEYS)

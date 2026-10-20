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
from concierge.contract import MAX_BODY_BYTES, MEMORY_TOPIC, MemoryPayload, empty_memory_payload
from concierge.publish import MemoryPublisher, PayloadTooLarge, publish
from concierge.store import Store
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
        await shutdown(ctx, started)
    assert len(room.local_participant.sent) == 1  # nothing at shutdown: the room is gone by then (plan C6)


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
    assert len(sent) == 2 and len(room.local_participant.sent) == 2
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
        await shutdown(ctx, started)
    with Store(db.path) as s:
        thread = s.thread_for(VISITOR)
        assert thread is not None and [f.value for f in s.valid_facts(thread.id)] == ["Acme"]  # the flush merged
    assert len(room.local_participant.sent_on(MEMORY_TOPIC)) == 1 and len(room.local_participant.sent) == 1

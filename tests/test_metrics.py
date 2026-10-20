"""Per-turn latency and tokens (spec §4.7, §4.10, §6 `concierge.metrics`, B9; plan C6 Part 3).

The messages are real `llm.ChatMessage`s whose `.metrics` are `MetricsReport` dicts (1.8.8 has one TypedDict for both
roles, llm/chat_context.py:286): the user keys on user messages, the assistant keys on assistant messages.
"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from livekit.agents import Agent, AgentSession, function_tool, llm
from livekit.agents.llm.chat_context import MetricsReport
from livekit.agents.metrics import LLMMetrics
from livekit.agents.testing import fake_job_context
from livekit.agents.voice.events import AgentStateChangedEvent, ConversationItemAddedEvent

from concierge import session as concierge_session
from concierge.contract import METRICS_TOPIC, MetricsPayload
from concierge.merge import merge
from concierge.metrics import TurnMetricsCollector
from concierge.models import TurnMetrics
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.fake_room import FakeRoom
from concierge.testing.sessions import METADATA, VISITOR, shutdown, start

ANONYMOUS_COLUMNS = [
    "session_id", "turn", "eou_ms", "stt_ms", "llm_ttft_ms", "tts_ttfb_ms", "total_ms", "memory_on_turn_path_ms",
    "preload_ms", "extraction_ms", "prompt_tokens", "cached_tokens", "compacted", "created_at",
]
VOICE_USER: MetricsReport = {
    "started_speaking_at": 1_760_000_000.0, "stopped_speaking_at": 1_760_000_002.0,
    "transcription_delay": 0.2, "end_of_turn_delay": 0.35, "on_user_turn_completed_delay": 0.0123,
}
ASSISTANT: MetricsReport = {
    "started_speaking_at": 1_760_000_003.0, "stopped_speaking_at": 1_760_000_005.0,
    "llm_node_ttft": 0.41, "tts_node_ttfb": 0.18, "e2e_latency": 1.03, "playback_latency": 0.0,
}


def message(role: str, text: str, metrics: MetricsReport | None = None) -> ConversationItemAddedEvent:
    item = llm.ChatMessage(role=role, content=[text], metrics=metrics or MetricsReport())  # type: ignore[arg-type]
    return ConversationItemAddedEvent(item=item)


def listening() -> AgentStateChangedEvent:
    return AgentStateChangedEvent(old_state="speaking", new_state="listening")


def llm_metrics(prompt_tokens: int, cached: int, *, cancelled: bool = False) -> LLMMetrics:
    return LLMMetrics(
        label="fake", request_id=uuid.uuid4().hex, timestamp=time.time(), duration=0.5, ttft=0.2, cancelled=cancelled,
        completion_tokens=10, prompt_tokens=prompt_tokens, prompt_cached_tokens=cached, total_tokens=prompt_tokens + 10,
        tokens_per_second=20.0,
    )


class Published:
    """The collector's `publish`: records each payload, optionally failing."""

    def __init__(self) -> None:
        self.payloads: list[MetricsPayload] = []
        self.fail_with: Exception | None = None

    async def __call__(self, payload: MetricsPayload) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.payloads.append(payload)


def rows(store: Store) -> list[dict[str, Any]]:
    conn = sqlite3.connect(store.path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM anonymous_turn_metrics ORDER BY id")]
    finally:
        conn.close()


def turn(collector: TurnMetricsCollector, user: MetricsReport | None = None, assistant: MetricsReport | None = None,
         *, greeting: bool = False) -> None:
    """One user message (unless `greeting`), one assistant message, then `listening`, as AgentSession sends them."""
    if not greeting:
        collector.on_item_added(message("user", "I work at Acme.", user))
    collector.on_item_added(message("assistant", "Nice.", assistant))
    collector.on_state_changed(listening())


@pytest.fixture
def session_id() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def published() -> Published:
    return Published()


@pytest.fixture
def collector(store: Store, session_id: str, published: Published) -> TurnMetricsCollector:
    return TurnMetricsCollector(store, session_id, published)


async def test_one_row_per_turn_with_the_anonymous_columns(
    store: Store, collector: TurnMetricsCollector, session_id: str, clock: Any  # noqa: ANN401
) -> None:
    for _ in range(3):
        turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    with sqlite3.connect(store.path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(anonymous_turn_metrics)")]
    assert [c for c in columns if c != "id"] == ANONYMOUS_COLUMNS
    assert "visitor_id" not in columns and "thread_id" not in columns and "text" not in columns
    written = rows(store)
    assert [r["turn"] for r in written] == [1, 2, 3]
    assert {r["session_id"] for r in written} == {session_id}
    assert all(isinstance(r["created_at"], int) and 0 <= clock.now - r["created_at"] < 60_000 for r in written)
    assert "Acme" not in json.dumps(written)  # numbers only, never the text


async def test_user_and_assistant_fields_map_to_section_6_keys(
    collector: TurnMetricsCollector, published: Published
) -> None:
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    (p,) = published.payloads
    assert p.model_dump() == {
        "turn": 1, "eou_ms": 350.0, "stt_ms": 200.0, "llm_ttft_ms": 410.0, "tts_ttfb_ms": 180.0, "total_ms": 1030.0,
        "memory_on_turn_path_ms": 12.0, "preload_ms": None, "extraction_ms": None, "prompt_tokens": None,
        "cached_tokens": None, "compacted": False,
    }


async def test_memory_on_turn_path_ms_is_measured(collector: TurnMetricsCollector, published: Published) -> None:
    turn(collector, {"on_user_turn_completed_delay": 0.0123}, ASSISTANT)
    turn(collector, {"on_user_turn_completed_delay": 0.0871}, ASSISTANT)
    await collector.idle()
    assert [p.memory_on_turn_path_ms for p in published.payloads] == [12.0, 87.0]  # what 1.8 measured, not a constant


async def test_missing_e2e_latency_is_null(collector: TurnMetricsCollector, published: Published) -> None:
    assistant = {k: v for k, v in ASSISTANT.items() if k != "e2e_latency"}
    turn(collector, VOICE_USER, assistant)  # type: ignore[arg-type]
    await collector.idle()
    (p,) = published.payloads
    assert p.total_ms is None and p.llm_ttft_ms == 410.0


async def test_a_text_turn_leaves_eou_stt_and_turn_path_null(
    store: Store, collector: TurnMetricsCollector, published: Published
) -> None:
    turn(collector, MetricsReport(), ASSISTANT)  # a typed message: no STT, no on_user_turn_completed
    await collector.idle()
    (p,) = published.payloads
    assert (p.eou_ms, p.stt_ms, p.memory_on_turn_path_ms) == (None, None, None)
    assert (p.llm_ttft_ms, p.tts_ttfb_ms, p.total_ms) == (410.0, 180.0, 1030.0)
    (row,) = rows(store)
    assert (row["eou_ms"], row["stt_ms"], row["memory_on_turn_path_ms"]) == (None, None, None)


async def test_one_publish_per_turn_validates_against_the_schema(
    collector: TurnMetricsCollector, published: Published, metrics_validator: Draft202012Validator
) -> None:
    turn(collector, assistant=ASSISTANT, greeting=True)
    turn(collector, VOICE_USER, ASSISTANT)
    turn(collector, MetricsReport(), MetricsReport())
    await collector.idle()
    assert [p.turn for p in published.payloads] == [1, 2, 3]
    for p in published.payloads:
        metrics_validator.validate(json.loads(p.model_dump_json()))


async def test_preload_ms_is_on_turn_1_only(store: Store, session_id: str, published: Published) -> None:
    collector = TurnMetricsCollector(store, session_id, published, preload_ms=3.4)
    turn(collector, assistant=ASSISTANT, greeting=True)  # the greeting is turn 1 (§6 "first message only")
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    assert [p.preload_ms for p in published.payloads] == [3.0, None]
    assert [r["preload_ms"] for r in rows(store)] == [3.0, None]
    first = published.payloads[0]
    assert (first.eou_ms, first.stt_ms, first.memory_on_turn_path_ms) == (None, None, None)  # no user message


async def test_extraction_ms_is_on_the_turn_after_a_merge(
    store: Store, collector: TurnMetricsCollector, published: Published, visitor_id: str
) -> None:
    thread_id = store.get_or_create_thread(visitor_id).id
    result = await asyncio.to_thread(
        merge, store, thread_id, [], set(), "s1", extraction={"ms": 812.4, "prompt_tokens": 900}
    )
    assert result.extraction_ms == 812.4  # the extraction_ran row's ms, carried on the MergeResult
    (ran,) = [r for r in store.journal_rows(thread_id) if r.type == "extraction_ran"]
    assert ran.payload["ms"] == result.extraction_ms
    turn(collector, VOICE_USER, ASSISTANT)
    collector.note_extraction(result.extraction_ms)  # the writer's on_merged, 2 s after turn 1 (the debounce)
    turn(collector, VOICE_USER, ASSISTANT)
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    assert [p.extraction_ms for p in published.payloads] == [None, 812.0, None]


async def test_a_merge_without_an_extraction_has_no_extraction_ms(store: Store, visitor_id: str) -> None:
    thread_id = store.get_or_create_thread(visitor_id).id
    assert merge(store, thread_id, [], set(), "s1").extraction_ms is None


async def test_compacted_is_true_on_the_turn_after_a_compaction(
    store: Store, session_id: str, published: Published
) -> None:
    applied = [0]
    collector = TurnMetricsCollector(store, session_id, published, compactions=lambda: applied[0])
    turn(collector, VOICE_USER, ASSISTANT)
    applied[0] += 1  # the Compactor applies after turn 1's `listening` (a task, after the handlers ran)
    turn(collector, VOICE_USER, ASSISTANT)
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    assert [p.compacted for p in published.payloads] == [False, True, False]
    assert [r["compacted"] for r in rows(store)] == [0, 1, 0]


async def test_llm_metrics_tokens_land_on_the_next_turn(
    collector: TurnMetricsCollector, published: Published
) -> None:
    """The step's test: the FakeLLM's own stream emits metrics_collected (base LLMStream, llm.py:487)."""
    fake = FakeLLM([FakeResponse(text="Hello there.", prompt_tokens=1234, prompt_cached_tokens=1000)])
    fake.on("metrics_collected", collector.on_llm_metrics)
    async with fake.chat(chat_ctx=llm.ChatContext.empty()) as stream:
        async for _ in stream:
            pass
    await asyncio.sleep(0)  # the metrics task emits after the last chunk
    turn(collector, VOICE_USER, ASSISTANT)
    turn(collector, VOICE_USER, ASSISTANT)  # no call since: no tokens
    await collector.idle()
    assert [(p.prompt_tokens, p.cached_tokens) for p in published.payloads] == [(1234, 1000), (None, None)]


async def test_tokens_of_two_calls_in_one_turn_are_summed(
    collector: TurnMetricsCollector, published: Published
) -> None:
    collector.on_item_added(message("user", "I work at Acme.", VOICE_USER))
    collector.on_llm_metrics(llm_metrics(100, 50))
    collector.on_llm_metrics(llm_metrics(200, 150))
    collector.on_item_added(message("assistant", "Saved.", ASSISTANT))
    collector.on_state_changed(listening())
    await collector.idle()
    (p,) = published.payloads
    assert (p.prompt_tokens, p.cached_tokens) == (300, 200)


async def test_cancelled_llm_metrics_are_not_counted(collector: TurnMetricsCollector, published: Published) -> None:
    collector.on_llm_metrics(llm_metrics(5000, 4000, cancelled=True))  # a discarded preemptive reply
    collector.on_llm_metrics(llm_metrics(1234, 1000))
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    (p,) = published.payloads
    assert (p.prompt_tokens, p.cached_tokens) == (1234, 1000)


async def test_negative_ttft_is_null(collector: TurnMetricsCollector, published: Published) -> None:
    turn(collector, {**VOICE_USER, "transcription_delay": -1.0}, {**ASSISTANT, "llm_node_ttft": -1.0})
    turn(collector, {"end_of_turn_delay": float("nan")}, {"tts_node_ttfb": float("inf"), "e2e_latency": -0.5})
    await collector.idle()
    first, second = published.payloads
    assert first.llm_ttft_ms is None and first.stt_ms is None and first.eou_ms == 350.0
    assert second.eou_ms is None and second.tts_ttfb_ms is None and second.total_ms is None


async def test_two_assistant_messages_in_one_turn_are_one_row_first_value_wins(
    store: Store, collector: TurnMetricsCollector, published: Published
) -> None:
    """With a tool call, the text before the call and the reply after it are two assistant messages of one turn."""
    collector.on_item_added(message("user", "Remember Acme.", VOICE_USER))
    collector.on_item_added(message("assistant", "One moment.", {"llm_node_ttft": 0.3}))
    collector.on_item_added(message("assistant", "Saved.", {"llm_node_ttft": 0.9, "tts_node_ttfb": 0.2}))
    collector.on_state_changed(listening())
    await collector.idle()
    (p,) = published.payloads
    assert (p.llm_ttft_ms, p.tts_ttfb_ms) == (300.0, 200.0)
    assert len(rows(store)) == 1


async def test_a_second_user_message_before_the_reply_replaces_the_first(
    collector: TurnMetricsCollector, published: Published
) -> None:
    collector.on_item_added(message("user", "I work at", {"end_of_turn_delay": 0.9}))
    collector.on_item_added(message("user", "Acme.", {"end_of_turn_delay": 0.3}))
    collector.on_item_added(message("assistant", "Nice.", ASSISTANT))
    collector.on_state_changed(listening())
    await collector.idle()
    (p,) = published.payloads
    assert p.turn == 1 and p.eou_ms == 300.0


async def test_the_next_user_message_closes_a_turn_without_listening(
    collector: TurnMetricsCollector, published: Published
) -> None:
    collector.on_item_added(message("user", "Hi.", VOICE_USER))
    collector.on_item_added(message("assistant", "Hello.", ASSISTANT))  # interrupted: no listening before the next
    collector.on_item_added(message("user", "And Acme?", VOICE_USER))
    await collector.idle()
    assert [p.turn for p in published.payloads] == [1]


async def test_listening_without_a_reply_closes_nothing(
    collector: TurnMetricsCollector, published: Published
) -> None:
    collector.on_state_changed(listening())  # the session's first listening, before the greeting
    collector.on_item_added(message("user", "Hi.", VOICE_USER))
    collector.on_state_changed(listening())  # e.g. an empty reply
    collector.on_item_added(message("system", "ignored"))
    await collector.idle()
    assert published.payloads == []


def state(old: str, new: str) -> AgentStateChangedEvent:
    return AgentStateChangedEvent(old_state=old, new_state=new)  # type: ignore[arg-type]


def reply(text: str, metrics: MetricsReport | None = None, *, interrupted: bool = False) -> ConversationItemAddedEvent:
    item = llm.ChatMessage(
        role="assistant", content=[text], metrics=metrics or MetricsReport(), interrupted=interrupted
    )
    return ConversationItemAddedEvent(item=item)


async def test_a_paused_reply_that_resumes_is_one_turn(collector: TurnMetricsCollector, published: Published) -> None:
    """Pause on interruption (agent_activity.py:2390) sets `listening` before the reply's message exists; a false
    interruption resumes it. That `listening` closes nothing."""
    collector.on_item_added(message("user", "Hi.", VOICE_USER))
    collector.on_state_changed(state("thinking", "speaking"))
    collector.on_state_changed(state("speaking", "listening"))  # the visitor coughs: paused
    collector.on_llm_metrics(llm_metrics(100, 50))
    collector.on_state_changed(state("listening", "speaking"))  # resumed
    collector.on_item_added(reply("Hello.", ASSISTANT))
    collector.on_state_changed(state("speaking", "listening"))
    await collector.idle()
    (p,) = published.payloads
    assert (p.turn, p.prompt_tokens, p.llm_ttft_ms) == (1, 100, 410.0)


async def test_an_interrupted_reply_closes_when_its_message_lands(
    collector: TurnMetricsCollector, published: Published
) -> None:
    """A real interruption after the pause: the interrupted message is added while the agent is already listening,
    so no `listening` follows it (agent_activity.py:3946). The turn closes on the message, and the next reply's
    tokens go to the next turn."""
    collector.on_item_added(message("user", "Tell me about Michael.", VOICE_USER))
    collector.on_state_changed(state("thinking", "speaking"))
    collector.on_state_changed(state("speaking", "listening"))  # the visitor talks over the reply: paused
    collector.on_item_added(reply("Michael is", ASSISTANT, interrupted=True))
    collector.on_llm_metrics(llm_metrics(700, 600))  # the next reply's (preemptive) call
    collector.on_item_added(message("user", "Actually, his projects?", VOICE_USER))
    collector.on_state_changed(state("thinking", "speaking"))
    collector.on_item_added(reply("He built a voice agent.", ASSISTANT))
    collector.on_state_changed(state("speaking", "listening"))
    await collector.idle()
    assert [(p.turn, p.prompt_tokens) for p in published.payloads] == [(1, None), (2, 700)]


async def test_a_pause_during_a_tool_reply_is_not_a_turn(
    store: Store, collector: TurnMetricsCollector, published: Published
) -> None:
    """Text before a tool call, then the tool reply paused by a cough and resumed: one row, numbering unshifted."""
    collector.on_item_added(message("user", "Remember Acme.", VOICE_USER))
    collector.on_state_changed(state("thinking", "speaking"))
    collector.on_item_added(reply("One moment.", {"llm_node_ttft": 0.3}))
    collector.on_state_changed(state("speaking", "thinking"))  # the tool runs (agent_activity.py:3939)
    collector.on_state_changed(state("thinking", "speaking"))
    collector.on_state_changed(state("speaking", "listening"))  # paused
    collector.on_state_changed(state("listening", "speaking"))  # resumed
    collector.on_item_added(reply("Saved.", {"llm_node_ttft": 0.9}))
    collector.on_state_changed(state("speaking", "listening"))
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    assert [(p.turn, p.llm_ttft_ms) for p in published.payloads] == [(1, 300.0), (2, 410.0)]
    assert len(rows(store)) == 2


async def test_no_write_after_aclose(store: Store, collector: TurnMetricsCollector, published: Published) -> None:
    await collector.aclose()
    turn(collector, VOICE_USER, ASSISTANT)  # a turn closing while the session drains: the store is closing
    await collector.idle()
    assert rows(store) == [] and published.payloads == []


async def test_a_tool_call_turn_is_one_row(store: Store, session_id: str, published: Published) -> None:
    """A real AgentSession: the greeting, then a turn whose reply calls a tool before answering. 1.8.8 doesn't pass
    through `listening` between the call and the reply, so the turn is one row with both calls' tokens."""

    class Remembering(Agent):
        def __init__(self) -> None:
            super().__init__(instructions="Be brief.")

        @function_tool
        async def remember(self, about: str) -> str:
            """Remember something the visitor asked you to."""
            return "Saved."

    fake = FakeLLM([
        FakeResponse(text="Hello there.", prompt_tokens=900, prompt_cached_tokens=0),
        FakeResponse(tool_call=FakeToolCall(name="remember", arguments={"about": "Acme"}), prompt_tokens=1000,
                     prompt_cached_tokens=800),
        FakeResponse(text="Saved, you work at Acme.", prompt_tokens=1100, prompt_cached_tokens=1000),
    ])
    collector = TurnMetricsCollector(store, session_id, published)
    async with AgentSession(llm=fake) as session:
        session.on("conversation_item_added", collector.on_item_added)
        session.on("agent_state_changed", collector.on_state_changed)
        fake.on("metrics_collected", collector.on_llm_metrics)
        await session.start(Remembering())
        await session.generate_reply(instructions="Greet the visitor.")
        await session.run(user_input="Remember that I work at Acme.")
        await until(lambda: len(published.payloads) == 2, 2)
    await collector.idle()
    assert len(fake.calls) == 3
    greeting, tool_turn = published.payloads
    assert (greeting.turn, greeting.prompt_tokens) == (1, 900)
    assert (tool_turn.turn, tool_turn.prompt_tokens, tool_turn.cached_tokens) == (2, 2100, 1800)
    assert tool_turn.llm_ttft_ms is not None
    assert [r["turn"] for r in rows(store)] == [1, 2]


async def test_no_publish_after_stop_publishing(
    store: Store, collector: TurnMetricsCollector, published: Published
) -> None:
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    collector.stop_publishing()  # on_shutdown, first: the room is gone
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    assert [p.turn for p in published.payloads] == [1]
    assert [r["turn"] for r in rows(store)] == [1, 2]  # the anonymous row is still written


async def test_a_failed_publish_is_logged_and_the_row_still_written(
    store: Store, collector: TurnMetricsCollector, published: Published, caplog: pytest.LogCaptureFixture
) -> None:
    published.fail_with = RuntimeError("the room is gone: Acme")
    with caplog.at_level(logging.WARNING, logger="concierge.metrics"):
        turn(collector, VOICE_USER, ASSISTANT)
        await collector.idle()
    assert len(rows(store)) == 1
    assert "RuntimeError" in caplog.text and "Acme" not in caplog.text


async def test_a_failed_write_is_logged_and_the_turn_still_published(
    session_id: str, published: Published, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    broken = Store(tmp_path / "closed.db")
    broken.close()
    collector = TurnMetricsCollector(broken, session_id, published)
    with caplog.at_level(logging.WARNING, logger="concierge.metrics"):
        turn(collector, VOICE_USER, ASSISTANT)
        await collector.idle()
    assert len(published.payloads) == 1
    assert "ProgrammingError" in caplog.text


async def test_without_a_store_turns_are_published_only(session_id: str, published: Published) -> None:
    collector = TurnMetricsCollector(None, session_id, published)
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    await collector.aclose()
    assert len(published.payloads) == 1


async def test_metrics_survive_forget_me(
    store: Store, collector: TurnMetricsCollector, visitor_id: str
) -> None:
    store.get_or_create_thread(visitor_id)
    turn(collector, VOICE_USER, ASSISTANT)
    turn(collector, VOICE_USER, ASSISTANT)
    await collector.idle()
    store.forget_me(visitor_id)
    assert len(rows(store)) == 2  # B9: anonymous numbers, no visitor id: erasure leaves them


async def test_collector_aclose_waits_for_its_writes(
    session_id: str, published: Published, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slow = Store(tmp_path / "slow.db")
    real = slow.add_turn_metrics
    done: list[int] = []

    def add(sid: str, metrics: TurnMetrics) -> None:
        time.sleep(0.3)
        real(sid, metrics)
        done.append(metrics.turn)

    monkeypatch.setattr(slow, "add_turn_metrics", add)
    collector = TurnMetricsCollector(slow, session_id, published)
    turn(collector, VOICE_USER, ASSISTANT)
    await until(lambda: len(published.payloads) == 1, 1)  # the publish is quick; the write sleeps
    collector.on_item_added(message("user", "Bye.", VOICE_USER))
    collector.on_item_added(message("assistant", "Goodbye.", ASSISTANT))  # open at shutdown: written, not published
    collector.stop_publishing()
    await collector.aclose()
    assert done == [1, 2]  # both writes finished before aclose returned, so the store can close next
    assert [p.turn for p in published.payloads] == [1]
    slow.close()


async def test_collector_aclose_gives_up_on_a_stuck_write(
    session_id: str, published: Published, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    from concierge import metrics as concierge_metrics

    monkeypatch.setattr(concierge_metrics, "CLOSE_WAIT_S", 0.2)
    monkeypatch.setattr(store, "add_turn_metrics", lambda sid, m: time.sleep(1.0))
    collector = TurnMetricsCollector(store, session_id, published)
    turn(collector, VOICE_USER, ASSISTANT)
    began = time.monotonic()
    await collector.aclose()
    assert time.monotonic() - began < 0.6


async def until(cond: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


# --- through start_session (a real AgentSession over FakeLLMs, a FakeRoom as ctx.room) ----------------------------


async def test_session_publishes_concierge_metrics_per_turn_with_the_llm_tokens(
    db: Store, monkeypatch: pytest.MonkeyPatch, extractor: FakeLLM, summarizer: FakeLLM,
    metrics_validator: Draft202012Validator,
) -> None:
    """The step's wiring: the conversation LLM's metrics_collected (prompt_tokens=1234, prompt_cached_tokens=1000)
    reaches the turn the session publishes on concierge.metrics and writes to anonymous_turn_metrics."""
    conversation = FakeLLM([
        FakeResponse(text="Hello there.", prompt_tokens=900),
        FakeResponse(text="Michael builds voice agents.", prompt_tokens=1234, prompt_cached_tokens=1000),
    ])
    monkeypatch.setattr(concierge_session, "build_session", lambda ctx, settings: AgentSession(llm=conversation))
    monkeypatch.setattr(concierge_session, "room_start_kwargs", lambda *args: {})
    by_stage = {"extractor": extractor, "summarizer": summarizer}
    monkeypatch.setattr(concierge_session, "build_llm", lambda stage, settings=None: by_stage[stage])
    room = FakeRoom()
    with fake_job_context(job_metadata=METADATA, room=room) as ctx:
        started = await start(ctx, db)
        await started.session.run(user_input="What does Michael build?")
        await until(lambda: len(room.local_participant.sent_on(METRICS_TOPIC)) == 2, 3)
        await shutdown(ctx, started)
    sent = [json.loads(t) for t in room.local_participant.sent_on(METRICS_TOPIC)]
    for body in sent:
        metrics_validator.validate(body)
    assert [(b["turn"], b["prompt_tokens"], b["cached_tokens"]) for b in sent] == [(1, 900, 0), (2, 1234, 1000)]
    assert sent[0]["preload_ms"] is not None and sent[1]["preload_ms"] is None
    assert sent[1]["eou_ms"] is None and sent[1]["memory_on_turn_path_ms"] is None  # a typed turn
    with Store(db.path) as s:
        assert s.thread_for(VISITOR) is not None
    written = rows(db)
    assert [(r["turn"], r["prompt_tokens"], r["cached_tokens"]) for r in written] == [(1, 900, 0), (2, 1234, 1000)]

"""Two sessions for one visitor (a refresh, a second tab; spec §4.2) never overwrite the visit summary blindly (C5
review A-I3): the shutdown starts from the summary stored now, not the one preloaded, and stores its own only if that
is still the stored one, else summarizes once more from the newer one."""

import json
from collections.abc import AsyncIterator, Callable

import pytest
from livekit.agents import llm

from concierge.memory_tools import do_forget
from concierge.memory_writer import MemoryWriter
from concierge.models import AddFact
from concierge.session_end import write_summary
from concierge.store import Store, StaleSummary
from concierge.testing.fake_llm import FakeLLM
from concierge.turns import Turn

S0 = "Ada works at Acme. She is building a clinic voice agent."
A_SUMMARY = "Ada is building a clinic voice agent. She asked about pricing."


def previous_of(ctx: llm.ChatContext) -> str | None:
    """The previous summary in the summarizer's input (summary.build_summary_ctx: a header line, then JSON)."""
    return json.loads((ctx.items[-1].text_content or "").split("\n", 1)[1])["previous_summary"]


def echo(extra: str) -> Callable[[llm.ChatContext], str]:
    return lambda ctx: f"{previous_of(ctx) or ''} {extra}".strip()


@pytest.fixture
def thread_id(store: Store, visitor_id: str) -> str:
    return store.get_or_create_thread(visitor_id).id


@pytest.fixture
async def tabs(store: Store, thread_id: str) -> AsyncIterator[tuple[MemoryWriter, MemoryWriter]]:
    a = MemoryWriter(store, thread_id, "sa", lambda: FakeLLM([]), debounce_s=60)
    b = MemoryWriter(store, thread_id, "sb", lambda: FakeLLM([]), debounce_s=60)
    a.history.append(Turn(turn_id="ua", role="user", text="Forget Acme.", channel="voice"))
    b.history.append(Turn(turn_id="ub", role="user", text="Tell me about Rust.", channel="voice"))
    yield a, b
    await a.aclose()
    await b.aclose()


def test_swap_summary_raises_stale_summary_when_the_stored_one_changed(store: Store, thread_id: str) -> None:
    store.set_summary(thread_id, None, S0)
    with pytest.raises(StaleSummary):
        store.swap_summary(thread_id, None, "Newer.")
    assert store.state(thread_id).last_visit_summary == S0
    assert store.swap_summary(thread_id, S0, A_SUMMARY).last_visit_summary == A_SUMMARY


async def test_the_visit_summary_starts_from_the_stored_summary(
    store: Store, thread_id: str, tabs: tuple[MemoryWriter, MemoryWriter]
) -> None:
    _, b = tabs
    store.set_summary(thread_id, None, S0)  # what tab B preloaded
    store.set_summary(thread_id, None, A_SUMMARY)  # tab A's shutdown, before B's
    summarizer = FakeLLM(respond=echo("She asked about Rust."))
    await write_summary(b, lambda: summarizer)
    assert previous_of(summarizer.calls[0].chat_ctx) == A_SUMMARY
    assert store.state(thread_id).last_visit_summary == f"{A_SUMMARY} She asked about Rust."


async def test_a_second_tab_never_brings_back_a_forgotten_value(
    store: Store, thread_id: str, tabs: tuple[MemoryWriter, MemoryWriter]
) -> None:
    a, b = tabs
    store.apply_fact_ops(thread_id, [AddFact(slot="company", value="Acme", source="user_said", channel="voice",
                                             turn_id="old")])
    store.set_summary(thread_id, None, S0)  # both tabs preloaded it
    assert await do_forget(a, "Acme")
    await write_summary(a, lambda: FakeLLM(["Ada is building a clinic voice agent."]))
    await write_summary(b, lambda: FakeLLM(respond=echo("She asked about Rust.")))
    final = store.state(thread_id).last_visit_summary
    assert final == "Ada is building a clinic voice agent. She asked about Rust."


async def test_a_summary_stored_during_the_call_is_carried_forward_not_overwritten(
    store: Store, thread_id: str, tabs: tuple[MemoryWriter, MemoryWriter]
) -> None:
    _, b = tabs
    store.set_summary(thread_id, None, S0)
    seen: list[str | None] = []

    def tab_a_finishes_first(ctx: llm.ChatContext) -> str:
        seen.append(previous_of(ctx))
        if len(seen) == 1:
            store.set_summary(thread_id, None, A_SUMMARY)  # tab A's shutdown lands during B's call
        return f"{previous_of(ctx)} She asked about Rust."

    await write_summary(b, lambda: FakeLLM(respond=tab_a_finishes_first))
    assert seen == [S0, A_SUMMARY]
    assert store.state(thread_id).last_visit_summary == f"{A_SUMMARY} She asked about Rust."


async def test_a_summary_that_keeps_changing_is_left_alone_after_one_retry(
    store: Store, thread_id: str, tabs: tuple[MemoryWriter, MemoryWriter]
) -> None:
    _, b = tabs
    store.set_summary(thread_id, None, S0)
    calls = 0

    def always_raced(ctx: llm.ChatContext) -> str:
        nonlocal calls
        calls += 1
        store.set_summary(thread_id, None, f"Another tab wrote this, take {calls}.")
        return "Tab B's summary."

    await write_summary(b, lambda: FakeLLM(respond=always_raced))
    assert calls == 2
    assert store.state(thread_id).last_visit_summary == "Another tab wrote this, take 2."
    errors = [r.payload for r in store.journal_rows(thread_id) if r.type == "error"]
    assert errors == [{"stage": "summary", "type": "StaleSummary"}]

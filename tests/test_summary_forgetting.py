"""A forgotten value never survives in the visit summary (C5 review A-I1, A-I2): "forget" clears a stored summary
that names it at once, without waiting for the shutdown, and the session-end check also covers values the visitor
asked to forget before extraction stored them."""

import json
from typing import Any

import pytest
from livekit.agents.testing import fake_job_context

from concierge import session as concierge_session
from concierge.memory_tools import FORGOTTEN, NOTHING_TO_FORGET, do_forget
from concierge.memory_writer import MemoryWriter
from concierge.models import AddFact
from concierge.session_end import write_summary
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall
from concierge.testing.sessions import METADATA, VISITOR, shutdown, stage_llms, start

S0 = "Ada works at Acme. She is building a clinic voice agent."


def seed_acme(store: Store, thread_id: str, summary: str | None = S0) -> None:
    store.apply_fact_ops(thread_id, [AddFact(slot="company", value="Acme", source="user_said", channel="voice",
                                             turn_id="old")])
    store.set_summary(thread_id, None, summary)


def summary_of(store: Store, thread_id: str) -> str | None:
    return store.state(thread_id).last_visit_summary


def errors(store: Store, thread_id: str) -> list[dict[str, Any]]:
    return [r.payload for r in store.journal_rows(thread_id) if r.type == "error"]


@pytest.fixture
def thread_id(store: Store, visitor_id: str) -> str:
    return store.get_or_create_thread(visitor_id).id


@pytest.fixture
async def writer(store: Store, thread_id: str) -> Any:  # noqa: ANN401
    w = MemoryWriter(store, thread_id, "s1", lambda: FakeLLM([]), debounce_s=60)
    yield w
    await w.aclose()


# --- forget clears the stored summary at once (A-I1) ---------------------------------------------------------


async def test_forget_clears_a_stored_summary_that_names_the_value(
    store: Store, thread_id: str, writer: MemoryWriter
) -> None:
    seed_acme(store, thread_id)
    assert await do_forget(writer, "Acme") == FORGOTTEN
    assert summary_of(store, thread_id) is None  # no shutdown needed


async def test_forget_by_slot_clears_a_summary_that_names_the_deleted_value(
    store: Store, thread_id: str, writer: MemoryWriter
) -> None:
    seed_acme(store, thread_id)
    assert await do_forget(writer, "where I work") == FORGOTTEN
    assert summary_of(store, thread_id) is None


async def test_forget_of_a_value_only_the_summary_holds_clears_it(
    store: Store, thread_id: str, writer: MemoryWriter
) -> None:
    store.set_summary(thread_id, None, S0)  # no fact: the summary is the only place "Acme" is
    assert await do_forget(writer, "Acme") == FORGOTTEN
    assert summary_of(store, thread_id) is None


async def test_forget_keeps_a_summary_that_does_not_name_the_value(
    store: Store, thread_id: str, writer: MemoryWriter
) -> None:
    seed_acme(store, thread_id, "Ada is building a clinic voice agent.")
    assert await do_forget(writer, "Acme") == FORGOTTEN
    assert summary_of(store, thread_id) == "Ada is building a clinic voice agent."
    assert await do_forget(writer, "Rust") == NOTHING_TO_FORGET


async def test_a_summarizer_that_cannot_be_built_still_clears_a_forgotten_value(
    store: Store, thread_id: str, writer: MemoryWriter
) -> None:
    await do_forget(writer, "Acme")  # nothing stored yet
    store.set_summary(thread_id, None, S0)  # e.g. another tab wrote it after the forget

    def no_provider() -> Any:  # noqa: ANN401
        raise KeyError("CONCIERGE_SUMMARIZER_KEY")

    await write_summary(writer, no_provider)
    assert summary_of(store, thread_id) is None
    assert errors(store, thread_id) == [{"stage": "summary", "type": "KeyError"}]


# --- a value forgotten before extraction stored it (A-I2) ----------------------------------------------------


class AcmeExtractor(FakeLLM):
    """The final flush's extractor: ADD company Acme citing the visit's first visitor turn."""

    def chat(self, **kwargs: Any) -> Any:  # noqa: ANN401
        turns = json.loads(kwargs["chat_ctx"].items[-1].text_content.rsplit("\n", 1)[-1])
        turn_id = [t["turn_id"] for t in turns if t["speaker"] == "visitor"][0]
        op = {"op": "ADD", "slot": "company", "value": "Acme", "fact_id": None, "confidence": None,
              "turn_id": turn_id, "reason": None}
        self._script.append(FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": [op]})))
        return super().chat(**kwargs)


@pytest.mark.parametrize("about", ["Acme", "where I work"])
async def test_a_value_forgotten_before_extraction_stays_out_of_the_visit_summary(
    db: Store, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch, about: str
) -> None:
    summarizer = FakeLLM(["The visitor works at Acme and asked what Michael builds."])
    extractor = AcmeExtractor([])
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=extractor, summarizer=summarizer))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.writer is not None and started.preloaded is not None
        await started.session.run(user_input="I work at Acme.")
        assert await do_forget(started.writer, about) == NOTHING_TO_FORGET  # inside the debounce: nothing stored
        await shutdown(ctx, started)
    assert len(extractor.calls) == 1 and len(summarizer.calls) == 1
    with Store(db.path) as s:
        thread = s.thread_for(VISITOR)
        assert thread is not None
        assert s.valid_facts(thread.id) == []
        assert summary_of(s, thread.id) is None
        assert errors(s, thread.id) == [{"stage": "summary", "type": "forgotten_value"}]

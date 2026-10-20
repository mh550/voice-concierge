"""Summary of summary (spec §4.4 "At session end", §7; cf. livekit/agents #7721): the second visit's summary is
written from the first one and still carries its key point. Two real sessions through start_session and its
shutdown callback, each with its own summarizer FakeLLM."""

import json
from pathlib import Path
from typing import Any

import pytest
from livekit.agents import llm
from livekit.agents.testing import fake_job_context

from concierge import session as concierge_session
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM
from concierge.testing.sessions import METADATA, shutdown, stage_llms, start

FIRST_SUMMARY = (
    "The visitor is building a voice agent for a clinic. They asked how Michael handles memory across calls. "
    "They want to hear back about a follow-up."
)


def summarizer_input(ctx: llm.ChatContext) -> dict[str, Any]:
    """The JSON the summarizer received (its user message, after the one-line header)."""
    return json.loads((ctx.items[-1].text_content or "").split("\n", 1)[1])


def echo_first_sentence(ctx: llm.ChatContext) -> str:
    """Visit 2's summarizer: the previous summary's first sentence, then what is new."""
    previous = summarizer_input(ctx)["previous_summary"] or ""
    first = previous.split(". ")[0].rstrip(".") + "."
    return f"{first} This time they asked about pricing."


async def _visit(db: Store, extractor: FakeLLM, summarizer: FakeLLM, said: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(concierge_session, "build_llm", stage_llms(extractor=extractor, summarizer=summarizer))
    with fake_job_context(job_metadata=METADATA) as ctx:
        started = await start(ctx, db)
        assert started.preloaded is not None
        await started.session.run(user_input=said)
        await shutdown(ctx, started)  # closes this visit's store
    return started.preloaded.thread_id


async def _two_visits(
    path: Path, extractor: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeLLM, FakeLLM, str | None, str | None]:
    """Visit 1 (a scripted 3-sentence summary), then visit 2 (a template over the previous summary)."""
    first, second = FakeLLM([FIRST_SUMMARY]), FakeLLM(respond=echo_first_sentence)
    thread_id = await _visit(Store(path), extractor, first, "I'm building a voice agent for a clinic.", monkeypatch)
    with Store(path) as s:
        after_first = s.state(thread_id).last_visit_summary
    await _visit(Store(path), extractor, second, "How do you price a project like this?", monkeypatch)
    with Store(path) as s:
        after_second = s.state(thread_id).last_visit_summary
    return first, second, after_first, after_second


async def test_second_visit_summary_keeps_the_first_visits_key_point(
    tmp_path: Path, extractor: FakeLLM, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, after_first, after_second = await _two_visits(tmp_path / "visits.db", extractor, monkeypatch)
    assert len(first.calls) == 1 and len(second.calls) == 1
    assert after_first == FIRST_SUMMARY and "clinic" in after_first
    assert after_second == "The visitor is building a voice agent for a clinic. This time they asked about pricing."
    assert "clinic" in after_second


async def test_summarizer_context_contains_the_previous_summary(
    tmp_path: Path, extractor: FakeLLM, fakes: list[FakeLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, _, _ = await _two_visits(tmp_path / "visits.db", extractor, monkeypatch)
    assert summarizer_input(first.calls[0].chat_ctx)["previous_summary"] is None
    data = summarizer_input(second.calls[0].chat_ctx)
    assert data["previous_summary"] == FIRST_SUMMARY
    assert [t["text"] for t in data["turns"] if t["speaker"] == "visitor"] == ["How do you price a project like this?"]

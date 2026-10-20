"""The session's first reply (spec §4.3 step 5; plan C3 "Greetings"): a new visitor gets an introduction, a returning
one is greeted by name (or without one) and offered the last topic."""

import json

from concierge.greeting import INTRODUCTION, greeting_instructions
from concierge.models import VisitorState
from concierge.preload import Preloaded

ASKED = "the LiveKit project"
SUMMARY = "Ada asked about the portfolio's voice agent."


def preloaded(state: VisitorState, block: str | None = "block") -> Preloaded:
    return Preloaded(thread_id="t", version=3, visits=2, state=state, facts=[], block=block, ms=0.2)


def test_new_visitor_gets_the_introduction() -> None:
    text = greeting_instructions(preloaded(VisitorState(), block=None))
    assert text == INTRODUCTION
    assert text.startswith("Introduce yourself in one sentence")


def test_session_without_memory_gets_the_introduction() -> None:
    assert greeting_instructions(None) == INTRODUCTION


def test_returning_visitor_with_a_name_is_greeted_by_name_with_the_last_topic() -> None:
    text = greeting_instructions(preloaded(VisitorState(name="Ada", asked_about=[ASKED])))
    assert text.startswith('Greet "Ada" by name and offer to pick up ')
    assert "the last asked_about line in your notes" in text


def test_returning_visitor_with_a_summary_but_no_name_is_greeted_without_a_name() -> None:
    text = greeting_instructions(preloaded(VisitorState(last_visit_summary=SUMMARY)))
    assert text.startswith("Welcome the visitor back without using a name and offer to pick up ")
    assert "Greet" not in text and '"' not in text
    assert "the Last visit line in your notes" in text


def test_last_topic_points_at_asked_about_then_the_summary() -> None:
    both = greeting_instructions(preloaded(VisitorState(name="Ada", asked_about=[ASKED], last_visit_summary=SUMMARY)))
    assert "asked_about line" in both and "Last visit line" not in both
    summary_only = greeting_instructions(preloaded(VisitorState(name="Ada", last_visit_summary=SUMMARY)))
    assert "Last visit line" in summary_only
    neither = greeting_instructions(preloaded(VisitorState(name="Ada", company="Acme")))
    assert "offer to pick up the conversation." in neither


def test_a_returning_thread_with_nothing_to_recall_is_greeted_as_new() -> None:
    assert greeting_instructions(preloaded(VisitorState(), block=None)) == INTRODUCTION


def test_the_name_is_quoted_and_no_other_visitor_value_is_copied() -> None:
    name = 'Zoë "Z" O\'Neil'
    state = VisitorState(
        name=name, company="Quillworks", interests=["voice agents"], asked_about=[ASKED], last_visit_summary=SUMMARY
    )
    text = greeting_instructions(preloaded(state))
    assert json.dumps(name, ensure_ascii=False) in text
    for value in ("Quillworks", "voice agents", ASKED, SUMMARY):
        assert value not in text

"""The offline eval twin (spec §4.9; plan C4 "Offline eval twin"): every evals/memory/*.yaml script replayed through
the real Turn building, extract() and merge(), with a FakeLLM that returns the script's recorded emit_ops arguments."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from concierge.evals.runner import ScriptResult, check, run_script
from concierge.evals.script import MemoryScript, load_script
from concierge.models import Fact
from concierge.testing.replay import Replay

EVALS = Path(__file__).resolve().parents[1] / "evals" / "memory"
SCRIPTS = sorted(EVALS.glob("*.yaml"))
REQUIRED = [
    "01-introduction",
    "02-correction",
    "03-interrupted-fake-fact",
    "04-agent-guess-unconfirmed",
    "05-injection",
    "06-forget-request",
    "07-second-visit-merge",
]


async def _run(stem: str) -> tuple[ScriptResult, Replay]:
    script = load_script(EVALS / f"{stem}.yaml")
    replay = Replay(script)
    return await run_script(script, replay), replay


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.stem for p in SCRIPTS])
async def test_script(path: Path):
    script = load_script(path)
    result = await run_script(script, Replay(script))
    assert result.missing_expected == []
    assert result.forbidden_hits == []


def test_required_cases_exist():
    stems = {p.stem for p in SCRIPTS}
    assert [name for name in REQUIRED if name not in stems] == []


def test_between_10_and_15_scripts():
    assert 10 <= len(SCRIPTS) <= 15


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.stem for p in SCRIPTS])
def test_every_script_validates(path: Path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("name", "visits", "expected", "forbidden", "recorded_ops"):
        assert key in raw, key
    script = load_script(path)
    assert script.name == path.stem
    assert len(script.recorded_ops) == len(script.visits)


async def test_interrupted_fake_fact_never_reaches_the_extractor():
    result, replay = await _run("03-interrupted-fake-fact")
    (fake,) = replay.llms
    assert len(fake.calls) == 1  # what the extractor LLM was actually sent
    sent = "\n".join(m.text_content or "" for m in fake.calls[0].chat_ctx.messages())
    assert "Great." in sent and "initech" not in sent.casefold()
    # Its recorded ADD of the fake company is rejected as ungrounded: the merge read the heard text too. With the
    # generated text visible it would have been "agent_attributed".
    company = [r for r in result.rejected if r["slot"] == "company"]
    assert [r["reason"] for r in company] == ["ungrounded"]


async def test_injection_is_rejected_by_the_gate():
    result, _ = await _run("05-injection")
    assert "instruction" in [r["reason"] for r in result.rejected]
    assert all("ignore" not in f.value.casefold() for f in result.history)


async def test_correction_keeps_the_old_fact_in_history():
    result, _ = await _run("02-correction")
    old, new = [f for f in result.history if f.slot == "company"]
    assert (old.value, new.value) == ("Initech", "Acme")
    assert old.valid_to is not None and old.superseded_by == new.id


async def test_forget_request_invalidates_and_keeps_the_row():
    result, _ = await _run("06-forget-request")
    rust = [f for f in result.history if f.value == "Rust"]
    assert len(rust) == 1 and rust[0].valid_to is not None


async def test_typed_turns_store_typed_facts():
    result, _ = await _run("10-typed-channel")
    (company,) = [f for f in result.history if f.slot == "company"]
    assert (company.channel, company.source) == ("text", "user_typed")


async def test_ninth_interest_keeps_the_eight_newest():
    result, _ = await _run("12-ninth-interest")
    interests = [v for s, v in result.stored if s == "interests"]
    assert len(interests) == 8 and "Rust" not in interests
    (rust,) = [f for f in result.history if f.value == "Rust"]
    assert rust.valid_to is not None and rust.superseded_by == result.history[-1].id  # Swift, the ninth


async def test_agent_guess_is_agent_attributed_both_ways():
    result, _ = await _run("04-agent-guess-unconfirmed")
    assert [(r["turn_id"], r["reason"]) for r in result.rejected] == [
        ("v1-t3", "agent_attributed"),
        ("v1-t2", "agent_attributed"),
    ]


async def test_a_text_reply_is_zero_ops():
    result, replay = await _run("11-nothing-to-store")
    assert result.stored == [] and result.rejected == []
    assert [r["tool_called"] for r in result.runs] == [True, False]
    assert [len(fake.calls) for fake in replay.llms] == [1, 1]


async def test_a_visit_without_a_visitor_turn_makes_no_call():
    script = _inline(visits=[[{"role": "agent", "text": "Hi!"}]], recorded_ops=[{"ops": []}])
    replay = Replay(script)
    result = await run_script(script, replay)
    assert [len(fake.calls) for fake in replay.llms] == [0]
    assert result.runs == [{"ms": 0, "prompt_tokens": None, "dropped": 0, "tool_called": False, "ops": 0,
                            "rejected": 0, "skipped": 0, "applied": 0}]


# --- the runner's own checks, so a broken runner can't pass every file vacuously ---------------------------------


def _inline(**overrides) -> MemoryScript:
    raw = {
        "name": "inline",
        "visits": [[{"role": "user", "text": "I work at Initech on support tooling."}]],
        "expected": [],
        "forbidden": [],
        "recorded_ops": [{"ops": [{"op": "ADD", "slot": "company", "value": "Initech", "turn_id": "v1-t1"}]}],
    }
    return MemoryScript.model_validate({**raw, **overrides})


async def test_runner_detects_a_forbidden_hit():
    script = _inline(forbidden=[{"slot": "company", "value_contains": "initech"}])
    result = await run_script(script, Replay(script))
    assert result.stored == [("company", "Initech")]
    assert result.forbidden_hits == ["forbidden company: Initech"]


async def test_runner_detects_a_missing_expected_fact():
    script = _inline(expected=[{"slot": "company", "value": "Acme"}])
    result = await run_script(script, Replay(script))
    assert result.missing_expected == ["company: Acme"]


def _fact(id_: int, slot: str, value: str, *, valid_to: int | None = None) -> Fact:
    return Fact(id=id_, thread_id="t", slot=slot, value=value, confidence=1.0, source="user_said", channel="voice",
                turn_id="v1-t1", created_at=0, valid_from=0, valid_to=valid_to)


def test_runner_detects_a_duplicate():
    facts = [_fact(1, "interests", "Voice agents"), _fact(2, "interests", "voice  AGENTS")]
    _, hits = check(_inline(), valid=facts, history=facts)
    assert hits == ["duplicate interests: voice agents"]


def test_runner_detects_a_gone_value_that_was_never_stored():
    _, hits = check(_inline(gone=[{"slot": "interests", "value": "Rust"}]), valid=[], history=[])
    assert hits == ["never stored interests: Rust"]


def test_an_expected_fact_matches_an_alternative_spelling():
    script = _inline(expected=[{"slot": "role", "value": "PM", "also": ["product manager"]}])
    facts = [_fact(1, "role", "Product  Manager")]
    assert check(script, valid=facts, history=facts) == ([], [])


def test_runner_detects_a_value_still_valid_that_should_be_gone():
    facts = [_fact(1, "interests", "Rust")]
    _, hits = check(_inline(gone=[{"slot": "interests", "value": "rust"}]), valid=facts, history=facts)
    assert hits == ["still valid interests: rust"]


def test_runner_detects_a_forbidden_value_even_when_invalidated():
    facts = [_fact(1, "role", "Recruiter", valid_to=5)]
    _, hits = check(_inline(forbidden=[{"value_contains": "recruit"}]), valid=[], history=facts)
    assert hits == ["forbidden role: Recruiter"]


def test_runner_detects_something_stored_when_nothing_should_be():
    facts = [_fact(1, "interests", "Rust")]
    _, hits = check(_inline(nothing_stored=True), valid=facts, history=facts)
    assert hits == ["stored interests: Rust"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"recorded_ops": []},  # one entry per visit
        {"visits": [[{"role": "agent", "text": "Hi.", "channel": "text"}]]},  # agent turns are voice
        {"visits": [[{"role": "user", "text": "Hi.", "interrupted_heard": "H"}]]},  # only agent turns are cut
        {"visits": [[{"role": "agent", "text": "Hi.", "confidence": 0.4}]]},  # only user turns have STT confidence
        {"recorded_ops": [{"ops": [], "text": "both"}]},  # ops or text, not both
        {"surprise": 1},  # extra="forbid"
    ],
)
def test_a_malformed_script_is_rejected(overrides):
    with pytest.raises(ValidationError):
        _inline(**overrides)


def test_load_script_needs_the_name_to_match_the_file(tmp_path):
    path = tmp_path / "other.yaml"
    path.write_text(yaml.safe_dump(_inline().model_dump(exclude_none=True)))
    with pytest.raises(ValueError, match="other"):
        load_script(path)

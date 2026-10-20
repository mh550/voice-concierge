"""The offline eval twin's runner (spec §4.9; plan C4 "run_script"): a script's visits go through the real Turn
building, extract() and merge() against a temp Store, on one thread. Only the LLM is swapped: offline it replays the
script's recorded emit_ops arguments (`concierge.testing.replay.Replay`); the live eval (C7) passes a real one.

One extraction per visit, over the whole visit: the session-end flush does the same, and a debounced run sees the
same window when the visit is shorter than the writer's 24-turn cap.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from livekit.agents import llm
from pydantic import BaseModel

from concierge.evals.script import MemoryScript, ScriptTurn
from concierge.extractor import extract, extraction_window
from concierge.fact_ops import value_key
from concierge.merge import merge
from concierge.models import Fact
from concierge.store import Store
from concierge.turns import Turn, turn_from_message

LLMFactory = Callable[[int], llm.LLM]  # visit index (0-based) -> the extractor's LLM for that visit


class ScriptResult(BaseModel):
    stored: list[tuple[str, str]]  # (slot, value) of the valid facts at the end, oldest first
    missing_expected: list[str]  # "slot: value"
    forbidden_hits: list[str]  # forbidden, duplicate, gone-but-not-removed and stored-when-nothing-should-be
    runs: list[dict[str, Any]]  # the extraction_ran journal payloads, one per visit
    rejected: list[dict[str, Any]]  # the gate_rejected journal payloads, in order
    history: list[Fact]  # every fact row at the end, valid or not


def build_turns(visit_number: int, turns: Sequence[ScriptTurn]) -> list[Turn]:
    """A visit's turns, built the way the session builds them: a 1.8 ChatMessage through turn_from_message.

    1.8 records an interrupted reply's content as its heard text, and never adds one nobody heard
    (concierge/turns.py). The Turn then gets the generated text back, so only `visible_text` keeps the unheard part
    out of the extractor's context and the merge's checks."""
    out: list[Turn] = []
    for index, st in enumerate(turns, start=1):
        turn_id = f"v{visit_number}-t{index}"
        if st.role == "user":
            msg = llm.ChatMessage(id=turn_id, role="user", content=[st.text], transcript_confidence=st.confidence)
            turn = turn_from_message(msg, st.channel)
        else:
            heard = st.text if st.interrupted_heard is None else st.interrupted_heard
            msg = llm.ChatMessage(id=turn_id, role="assistant", content=[heard] if heard else [],
                                  interrupted=st.interrupted_heard is not None)
            turn = turn_from_message(msg)
            if turn is not None and turn.interrupted:
                turn = turn.model_copy(update={"text": st.text})
        if turn is not None:
            out.append(turn)
    return out


def check(script: MemoryScript, *, valid: Sequence[Fact], history: Sequence[Fact]) -> tuple[list[str], list[str]]:
    """(missing_expected, forbidden_hits) for the facts at the end. Values compare casefolded with whitespace
    collapsed (an expected fact by its value or any `also` spelling); a forbidden value is a substring match against
    every row, invalidated ones included. A `gone` value must have been stored and be valid no more."""
    have = {(f.slot, value_key(f.value)) for f in valid}
    ever = {(f.slot, value_key(f.value)) for f in history}
    missing = [f"{e.slot}: {e.value}" for e in script.expected
               if not any((e.slot, value_key(v)) in have for v in (e.value, *e.also))]
    hits: list[str] = []
    for fact in history:
        if any((x.slot is None or x.slot == fact.slot) and x.value_contains.casefold() in fact.value.casefold()
               for x in script.forbidden):
            hits.append(f"forbidden {fact.slot}: {fact.value}")
    for g in script.gone:
        if (g.slot, value_key(g.value)) in have:
            hits.append(f"still valid {g.slot}: {g.value}")
        elif (g.slot, value_key(g.value)) not in ever:
            hits.append(f"never stored {g.slot}: {g.value}")
    seen: set[tuple[str, str]] = set()
    for fact in valid:
        key = (fact.slot, value_key(fact.value))
        if key in seen:
            hits.append(f"duplicate {fact.slot}: {key[1]}")
        seen.add(key)
    if script.nothing_stored:
        hits += [f"stored {f.slot}: {f.value}" for f in valid]
    return missing, hits


async def run_script(script: MemoryScript, llm_factory: LLMFactory) -> ScriptResult:
    """Replay a script's visits on one visitor's thread in a temp Store; one extraction and merge per visit."""
    with tempfile.TemporaryDirectory(prefix="concierge-eval-") as tmp:
        store = Store(Path(tmp) / "eval.db")
        try:
            visitor_id = str(uuid.uuid4())
            for n, visit in enumerate(script.visits):
                thread_id = store.get_or_create_thread(visitor_id).id
                window = extraction_window(build_turns(n + 1, visit), 0)
                facts = store.valid_facts(thread_id)
                result = await extract(llm_factory(n), window, facts)
                known = {t.turn_id for t in window if t.role == "user"}
                meta = {"ms": result.ms, "prompt_tokens": result.prompt_tokens, "dropped": len(result.dropped),
                        "tool_called": result.tool_called}
                merge(store, thread_id, result.ops, known, f"eval-v{n + 1}", turns=window, extraction=meta)
            valid, history = store.valid_facts(thread_id), store.fact_history(thread_id)
            journal = store.journal_rows(thread_id)
        finally:
            store.close()
    valid = sorted(valid, key=lambda f: f.id)
    missing, hits = check(script, valid=valid, history=history)
    return ScriptResult(
        stored=[(f.slot, f.value) for f in valid],
        missing_expected=missing,
        forbidden_hits=hits,
        runs=[r.payload for r in journal if r.type == "extraction_ran"],
        rejected=[r.payload for r in journal if r.type == "gate_rejected"],
        history=sorted(history, key=lambda f: f.id),
    )


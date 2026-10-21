"""The conversation evals (spec 2026-10-21 §6; plan V4 "The runner"): one evals/conversation/*.yaml file is one
visitor's typed turns and the checks on each reply. `run_conversation` sends them through the production
ConciergeAgent (its instructions, pack and tools) on a real AgentSession's text path, `session.run(user_input=...)`,
and reads each reply and its tool calls from the RunResult's events.

Any LLM: live (scripts/eval_conversation.py, the llm tier) the configured conversation model; offline (the twin)
`offline_llm(script)`, a FakeLLM replaying each turn's `fake_reply` or `fake_tool_call`. No room, STT, TTS or Store.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from livekit.agents import AgentSession, llm
from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent, RunEvent
from pydantic import BaseModel, ConfigDict, Field, model_validator

from concierge.agent import agent_or_memoryless
from concierge.knowledge import load_pack
from concierge.summary import sentences
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall

# Never in any reply, in any script (spec §6; the instructions forbid them, V3-03).
FORBIDDEN_EVERYWHERE = ("pack", "knowledge pack", "source:")

_FAKE_TOOL_CALL_KEYS = {"name", "arguments", "reply"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TurnCheck(_Strict):
    user: str = Field(min_length=1)  # what the visitor types
    must_mention: list[str] = []  # any of, case-insensitive; [] is no check
    must_not_mention: list[str] = []  # none of, case-insensitive
    max_sentences: int = Field(default=3, ge=1)
    tool_called: str | None = None  # a function the agent must call this turn
    # The offline twin's scripted reply for this turn, exactly one of the two. A tool call is
    # {name, arguments (default {}), reply}: the session asks the LLM again after the tool, and `reply` is that answer.
    fake_reply: str | None = None
    fake_tool_call: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_fake(self) -> TurnCheck:
        if (self.fake_reply is None) == (self.fake_tool_call is None):
            raise ValueError("a turn has exactly one of fake_reply or fake_tool_call")
        call = self.fake_tool_call
        if call is not None and not (
            {"name", "reply"} <= call.keys() <= _FAKE_TOOL_CALL_KEYS
            and isinstance(call["name"], str) and isinstance(call["reply"], str)
            and isinstance(call.get("arguments", {}), dict)
        ):
            raise ValueError("fake_tool_call is {name: str, arguments: dict (optional), reply: str}")
        return self


class ConversationScript(_Strict):
    name: str
    about: str  # one line: what the script checks and why
    turns: list[TurnCheck] = Field(min_length=1)


class TurnResult(BaseModel):
    turn: int  # 1-based
    reply: str  # every assistant message of the turn, joined by a space
    tools_called: list[str]  # function names, in call order
    failures: list[str]  # one per broken assertion, in check order; [] is a pass


class ConversationResult(BaseModel):
    name: str
    turns: list[TurnResult]
    passed: bool  # no turn has a failure


def load_conversation(path: Path) -> ConversationScript:
    """Read and validate one script; its name must be the file's stem."""
    script = ConversationScript.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if script.name != path.stem:
        raise ValueError(f"script name {script.name!r} is not the file's stem {path.stem!r}")
    return script


def _normal(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").casefold()


def _contains(text: str, phrase: str) -> bool:
    """Case-insensitive, as whole words with an optional plural ("pack" is in "packs", not in "package" or
    "backpack"); a space in the phrase also matches "_" or "-", and trailing punctuation may follow a space
    ("source:" is in "Sources :", not in "sources in")."""
    needle = _normal(phrase).strip()
    core = needle.rstrip(":;,.!?")
    words = r"[\s_-]+".join(re.escape(w) for w in core.split())
    tail = r"\s*" + re.escape(needle[len(core):]) if len(core) < len(needle) else r"(?![^\W_])"
    return re.search(rf"(?<![^\W_]){words}s?{tail}", _normal(text)) is not None


def _sentence_count(reply: str) -> int:
    """By concierge.summary.sentences, line by line, so list items without full stops count one each."""
    return sum(len(sentences(" ".join(line.split()))) for line in reply.splitlines() if line.strip())


def reply_failures(turn: TurnCheck, reply: str, tools_called: Sequence[str]) -> list[str]:
    """Every assertion the turn's reply or tool calls break, as the report's "failing assertion" text."""
    failures: list[str] = []
    if not any(ch.isalnum() for ch in reply):  # a turn that says nothing (only tool calls) never passes
        failures.append("reply: empty")
    if turn.must_mention and not any(_contains(reply, p) for p in turn.must_mention):
        failures.append("must_mention: none of " + ", ".join(repr(p) for p in turn.must_mention))
    failures += [f"must_not_mention: {p!r}" for p in turn.must_not_mention if _contains(reply, p)]
    failures += [f"forbidden: {p!r}" for p in FORBIDDEN_EVERYWHERE if _contains(reply, p)]
    if (n := _sentence_count(reply)) > turn.max_sentences:
        failures.append(f"max_sentences: {n} > {turn.max_sentences}")
    if turn.tool_called is not None and turn.tool_called not in tools_called:
        failures.append(f"tool_called: {turn.tool_called!r} not called (called: {', '.join(tools_called) or 'none'})")
    return failures


def _read(events: Sequence[RunEvent]) -> tuple[str, list[str]]:
    """(the reply, the tools called) from one run's events. The visitor's own message is not among them."""
    texts = [e.item.text_content or "" for e in events
             if isinstance(e, ChatMessageEvent) and e.item.role == "assistant"]
    tools = [e.item.name for e in events if isinstance(e, FunctionCallEvent)]
    return " ".join(t.strip() for t in texts if t.strip()), tools


async def run_conversation(
    script: ConversationScript, llm_factory: Callable[[], llm.LLM], *, pack: str = load_pack(),
    memory_block: str | None = None, turn_timeout_s: float = 60.0,
) -> ConversationResult:
    """Run every turn through a new session with the production agent, built as the worker builds it (a rejected
    memory block means no memory; memory=None: the tools save nothing and no Store is opened), and check each reply.
    The caller owns the LLM the factory returns and closes it."""
    session = AgentSession(llm=llm_factory())
    results: list[TurnResult] = []
    try:
        await session.start(agent_or_memoryless(pack, memory_block))  # no room: the text path only
        for index, turn in enumerate(script.turns, start=1):
            try:
                run = await asyncio.wait_for(session.run(user_input=turn.user), turn_timeout_s)
            except Exception as exc:  # a timeout, a provider error or a refusal: this turn fails, and the run is
                # still pending (a next run would be nested), so the script ends here; aclose() fails the run
                what = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                rest = "; the rest did not run" if index < len(script.turns) else ""
                failure = f"error: {what} (turn {index} of {len(script.turns)}{rest})"
                results.append(TurnResult(turn=index, reply="", tools_called=[], failures=[failure]))
                break
            reply, tools = _read(run.events)
            results.append(TurnResult(turn=index, reply=reply, tools_called=tools,
                                      failures=reply_failures(turn, reply, tools)))
    finally:
        await session.aclose()
    return ConversationResult(name=script.name, turns=results, passed=all(not t.failures for t in results))


def offline_llm(script: ConversationScript) -> FakeLLM:
    """The twin's LLM: per turn, its fake_reply as text, or its fake_tool_call and then the reply after the tool."""
    responses: list[FakeResponse] = []
    for turn in script.turns:
        if turn.fake_tool_call is None:
            responses.append(FakeResponse(text=turn.fake_reply))
            continue
        call = turn.fake_tool_call
        tool = FakeToolCall(name=call["name"], arguments=call.get("arguments", {}))
        responses += [FakeResponse(tool_call=tool), FakeResponse(text=call["reply"])]
    return FakeLLM(responses)

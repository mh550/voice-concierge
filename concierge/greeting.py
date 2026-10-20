"""The session's first reply (spec §4.3 step 5; plan C3 "Greetings").

The text goes to `session.generate_reply(instructions=...)`, which sends it for that one call only, after the cached
prefix. The confirmed name is the one visitor value copied here (quoted); the topic points at the memory section
instead of repeating visitor text outside it.
"""

from __future__ import annotations

import json

from concierge.preload import Preloaded

INTRODUCTION = (
    "Introduce yourself in one sentence as the concierge on Michael Herron's portfolio site, "
    "then ask what they would like to know about his work."
)
_ENDING = "Keep it to two short sentences."


def _topic(block: str) -> str:
    """Points only at a line the block has: trimming can drop every asked_about item, and a blank summary renders
    no Last visit line. Values are JSON strings, so no value starts a line of its own."""
    lines = block.split("\n")
    if any(line.startswith("- asked_about: ") for line in lines):
        return "the newest thing they asked about (the last asked_about line in your notes)"
    if any(line.startswith("Last visit: ") for line in lines):
        return "where you left off last visit (the Last visit line in your notes)"
    return "the conversation"


def greeting_instructions(preloaded: Preloaded | None) -> str:
    """The introduction for a new visitor (or a session without memory, or a thread with nothing to recall);
    a greeting by name with an offer to pick up the last topic for a returning one."""
    if preloaded is None or preloaded.block is None:
        return INTRODUCTION
    topic = _topic(preloaded.block)
    if preloaded.state.name:
        name = json.dumps(preloaded.state.name, ensure_ascii=False)
        return f"Greet {name} by name and offer to pick up {topic}. {_ENDING}"
    return f"Welcome the visitor back without using a name and offer to pick up {topic}. {_ENDING}"

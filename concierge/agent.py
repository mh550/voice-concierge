"""The concierge Agent: its instructions are the §5 prefix, built once at session start and never rewritten.

Its tools are the visitor's explicit requests, and each writes before it returns: `remember` and `forget` (spec §4.4,
B4, B5) and `leave_message_for_michael` (§4.6, C8). Everything else about the visitor is noted in the background by
the MemoryWriter.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from livekit.agents import Agent, llm

from concierge.events import EventRing
from concierge.memory_tools import do_forget, do_remember
from concierge.memory_writer import MemoryWriter
from concierge.message_tool import do_leave_message
from concierge.prompt import build_instructions

logger = logging.getLogger("concierge.session")  # its warning is the session's


class ConciergeAgent(Agent):
    def __init__(
        self, pack: str, memory_block: str | None = None, memory: MemoryWriter | None = None, *,
        events: EventRing | None = None, on_changed: Callable[[], None] | None = None,
    ) -> None:
        # Mid-session facts reach the model through the conversation, so nothing here calls update_instructions
        # (that would change the cached prefix). memory=None: a session without memory; the tools save nothing.
        # events / on_changed: the session's event ring and its publisher.schedule (V2-04), for the two tools.
        self._memory = memory
        self._events = events
        self._on_changed = on_changed
        super().__init__(instructions=build_instructions(pack, memory_block))

    @llm.function_tool
    async def remember(self, fact: str) -> str:
        """Save something about the visitor, only when they ask you to remember it.

        Args:
            fact: "<slot>: <value>", slot one of name, role, company, interest, follow-up (e.g. "company: Acme"),
                the value in the visitor's own words. Confirm a name before saving it.
        """
        return await do_remember(self._memory, fact, events=self._events, on_changed=self._on_changed)

    @llm.function_tool
    async def forget(self, about: str) -> str:
        """Delete what you remember about something, when the visitor asks you to forget it.

        Args:
            about: what to forget, in the visitor's words (e.g. "where I work", "my name", "Rust").
        """
        return await do_forget(self._memory, about, events=self._events, on_changed=self._on_changed)

    @llm.function_tool
    async def leave_message_for_michael(self, text: str, contact: str | None = None) -> str:
        """Pass a message on to Michael, when the visitor asks to leave him one.

        Args:
            text: the message, in the visitor's words, without their contact details.
            contact: how Michael can reach them (an email or phone number), only if they offer one; read it back
                to them once before saving.
        """
        return await do_leave_message(self._memory, text, contact)


def agent_or_memoryless(
    pack: str, memory_block: str | None, writer: MemoryWriter | None = None, *, events: EventRing | None = None,
    on_changed: Callable[[], None] | None = None,
) -> ConciergeAgent:
    """The agent with the visitor's memory block, or without one if build_instructions rejects it (the renderer
    keeps it under the cap, so this is the backstop that keeps a session from failing over memory)."""
    try:
        return ConciergeAgent(pack, memory_block, memory=writer, events=events, on_changed=on_changed)
    except ValueError:
        logger.warning("no memory this session: the memory block was rejected")
        return ConciergeAgent(pack, memory=writer, events=events, on_changed=on_changed)

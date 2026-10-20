"""The concierge Agent: its instructions are the §5 prefix, built once at session start and never rewritten.

Its two tools are the visitor's explicit memory requests (spec §4.4, B4, B5): `remember` and `forget` write before
they return. Everything else about the visitor is noted in the background by the MemoryWriter.
"""

from __future__ import annotations

from livekit.agents import Agent, llm

from concierge.memory_tools import do_forget, do_remember
from concierge.memory_writer import MemoryWriter
from concierge.prompt import build_instructions


class ConciergeAgent(Agent):
    def __init__(self, pack: str, memory_block: str | None = None, memory: MemoryWriter | None = None) -> None:
        # Mid-session facts reach the model through the conversation, so nothing here calls update_instructions
        # (that would change the cached prefix). memory=None: a session without memory; the tools save nothing.
        self._memory = memory
        super().__init__(instructions=build_instructions(pack, memory_block))

    @llm.function_tool
    async def remember(self, fact: str) -> str:
        """Save something about the visitor, only when they ask you to remember it.

        Args:
            fact: "<slot>: <value>", slot one of name, role, company, interest, follow-up (e.g. "company: Acme"),
                the value in the visitor's own words. Confirm a name before saving it.
        """
        return await do_remember(self._memory, fact)

    @llm.function_tool
    async def forget(self, about: str) -> str:
        """Delete what you remember about something, when the visitor asks you to forget it.

        Args:
            about: what to forget, in the visitor's words (e.g. "where I work", "my name", "Rust").
        """
        return await do_forget(self._memory, about)

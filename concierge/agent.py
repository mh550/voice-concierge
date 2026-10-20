"""The concierge Agent: its instructions are the §5 prefix, built once at session start and never rewritten."""

from livekit.agents import Agent

from concierge.prompt import build_instructions


class ConciergeAgent(Agent):
    def __init__(self, pack: str, memory_block: str | None = None) -> None:
        # No tools yet: C4 adds remember/forget. Mid-session facts reach the model through the conversation,
        # so nothing here calls update_instructions (that would change the cached prefix).
        super().__init__(instructions=build_instructions(pack, memory_block))

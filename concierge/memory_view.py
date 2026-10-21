"""What `concierge.memory` and `concierge.get_memory` carry (spec 2026-10-21 §2; plan V2 "One build path").

The session builds both through one callable, `current_memory(..., events=, agent=)`, so the RPC answers with what the
topic last sent. The agent's half (`AgentView.about_agent()`) and the event lines are read on the event loop (the
agent's `chat_ctx` is not thread-safe); the store's half runs on the writer's thread, in order with its writes. None
of it runs in a `conversation_item_added` handler: the publisher's `schedule` only starts a task.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from concierge.compaction import estimate_ctx_tokens
from concierge.contract import (
    AboutAgent,
    Cache,
    MemoryPayload,
    Working,
    build_memory_payload,
    empty_memory_payload,
)
from concierge.events import EventRing, Line, shown
from concierge.fact_ops import value_key
from concierge.knowledge import pack_stats
from concierge.prompt import STATIC_INSTRUCTIONS, estimate_tokens

if TYPE_CHECKING:
    from concierge.agent import ConciergeAgent
    from concierge.compactor import Compactor
    from concierge.memory_writer import MemoryWriter
    from concierge.metrics import TurnMetricsCollector
    from concierge.store import Store

logger = logging.getLogger("concierge.memory_view")

INSTRUCTIONS_EST_TOKENS = estimate_tokens(STATIC_INSTRUCTIONS)  # a constant per process


@dataclass(frozen=True)
class AgentView:
    """`about_agent`: the pack, the instructions, the memory block the agent was built with, its working context,
    the compactions applied and the last turn's cached share. No compactor or collector: 0 and null."""

    agent: ConciergeAgent
    compactor: Compactor | None = None
    collector: TurnMetricsCollector | None = None

    def about_agent(self) -> AboutAgent:
        ctx = self.agent.chat_ctx  # a read-only wrapper over the live list (voice/agent.py:169-179): no copy
        applied = self.compactor.applied if self.compactor is not None else 0
        block = self.agent.memory_block
        return AboutAgent(
            knowledge=pack_stats(),
            instructions_est_tokens=INSTRUCTIONS_EST_TOKENS,
            memory_block_chars=len(block) if block else None,
            working=Working(items=len(ctx.items), est_tokens=estimate_ctx_tokens(ctx), compacted=applied > 0,
                            compactions=applied),
            cache=Cache(cached_share=self.collector.last_cached_share if self.collector is not None else None),
        )


def _about(view: AgentView) -> AboutAgent | None:
    """`about_agent` is optional in the contract: a failed read costs that key, never the body (review I1)."""
    try:
        return view.about_agent()
    except Exception as exc:
        logger.warning("about_agent wasn't read (%s)", type(exc).__name__)
        return None


def _memory_for_visitor(store: Store, visitor_id: str, about_agent: AboutAgent | None = None) -> MemoryPayload:
    """Read-only: no thread is created for a visitor who has none."""
    thread = store.thread_for(visitor_id)
    if thread is None:
        return empty_memory_payload().model_copy(update={"about_agent": about_agent})
    return build_memory_payload(store, thread.id, about_agent=about_agent)


def memory_with_events(
    store: Store, thread_id: str, lines: list[Line], about_agent: AboutAgent | None = None
) -> MemoryPayload:
    """On the writer's thread: the body with this session's events, each line naming a value the store no longer
    holds (forgotten, here or in another session) in its value-free form (D17 (l))."""
    stored = {value_key(f.value) for f in store.fact_history(thread_id)}
    return build_memory_payload(store, thread_id, events=shown(lines, stored), about_agent=about_agent)


async def current_memory(
    store: Store | None, writer: MemoryWriter | None, visitor_id: str, *, events: EventRing | None = None,
    agent: AgentView | None = None,
) -> MemoryPayload:
    """The visitor's memory as the page shows it, with the agent's half when there is an `agent` view: on the writer's
    thread (in order with its writes) when the session has memory, with this session's `events`, else read from the
    store in a thread (the preload missed its deadline, or the daily cap), else nobody. The ring and the view are
    read here, on the event loop."""
    about = _about(agent) if agent is not None else None
    if writer is not None:
        lines = events.lines() if events is not None else []
        return await writer.call(memory_with_events, writer.store, writer.thread_id, lines, about)
    if store is not None:
        return await asyncio.to_thread(_memory_for_visitor, store, visitor_id, about)
    return empty_memory_payload().model_copy(update={"about_agent": about})

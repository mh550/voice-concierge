"""The agent's half of the v2 body (V2-05; plan V2 "One build path"): `AgentView.about_agent()` reads the pack, the
instructions, the memory block, the working context, the compactions and the cache share, on the event loop."""

import logging
from types import SimpleNamespace

import pytest
from livekit.agents import llm

from concierge.agent import ConciergeAgent, agent_or_memoryless
from concierge.compaction import estimate_ctx_tokens
from concierge.contract import AboutAgent
from concierge.knowledge import load_pack, pack_stats
from concierge.memory_view import AgentView, current_memory
from concierge.models import AddFact
from concierge.prompt import MEMORY_BLOCK_MAX_CHARS, MEMORY_HEADER, STATIC_INSTRUCTIONS, estimate_tokens
from concierge.store import Store

BLOCK = f"{MEMORY_HEADER}\n- company: \"Acme\""


def test_about_agent_reads_the_pack_and_the_instructions() -> None:
    about = AgentView(ConciergeAgent(load_pack())).about_agent()
    assert isinstance(about, AboutAgent)
    assert about.knowledge == pack_stats()
    assert about.instructions_est_tokens == estimate_tokens(STATIC_INSTRUCTIONS) > 0
    assert about.memory_block_chars is None  # a new visitor
    assert about.cache.cached_share is None and not about.working.compacted and about.working.compactions == 0


def test_memory_block_chars_is_the_blocks_length_or_none() -> None:
    assert AgentView(ConciergeAgent(load_pack(), BLOCK)).about_agent().memory_block_chars == len(BLOCK)
    assert AgentView(ConciergeAgent(load_pack(), "  \n")).about_agent().memory_block_chars is None  # blank: none
    dropped = agent_or_memoryless(load_pack(), "x" * (MEMORY_BLOCK_MAX_CHARS + 1))  # rejected: the agent has none
    assert AgentView(dropped).about_agent().memory_block_chars is None


async def test_working_is_the_agents_live_context() -> None:
    agent = ConciergeAgent(load_pack())
    view = AgentView(agent)
    before = view.about_agent().working
    assert before.items == len(agent.chat_ctx.items) and before.est_tokens == estimate_ctx_tokens(agent.chat_ctx)
    agent._chat_ctx.items.append(llm.ChatMessage(role="user", content=["I work at Acme. " * 20]))  # as 1.8 adds a turn
    after = view.about_agent().working
    assert after.items == before.items + 1 and after.est_tokens > before.est_tokens


def test_compactions_and_cached_share_come_from_the_compactor_and_collector() -> None:
    compactor, collector = SimpleNamespace(applied=2), SimpleNamespace(last_cached_share=0.8)
    about = AgentView(ConciergeAgent(load_pack()), compactor, collector).about_agent()  # type: ignore[arg-type]
    assert about.working.compacted and about.working.compactions == 2
    assert about.cache.cached_share == 0.8


class BrokenView:
    def about_agent(self) -> AboutAgent:
        raise FileNotFoundError("knowledge/sources/SOURCE.md")


async def test_a_failing_agent_view_still_sends_the_v1_body(
    store: Store, visitor_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Review I1: about_agent is optional in the contract, so a failed read costs that key, never the body."""
    tid = store.get_or_create_thread(visitor_id).id
    store.add_fact(tid, AddFact(slot="company", value="Acme", source="user_said", channel="voice", turn_id="t1"))
    with caplog.at_level(logging.WARNING, logger="concierge.memory_view"):
        body = await current_memory(store, None, visitor_id, agent=BrokenView())  # type: ignore[arg-type]
    assert [f.value for f in body.facts] == ["Acme"] and body.v == 2 and body.about_agent is None
    assert "FileNotFoundError" in caplog.text and "SOURCE.md" not in caplog.text  # by type only
    assert (await current_memory(None, None, visitor_id, agent=BrokenView())).about_agent is None  # type: ignore[arg-type]

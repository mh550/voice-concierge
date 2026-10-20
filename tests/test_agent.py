from livekit.agents import Agent, AgentSession, llm
from livekit.agents.testing import fake_job_context
from livekit.agents.voice.generation import INSTRUCTIONS_MESSAGE_ID

from concierge.agent import ConciergeAgent
from concierge.knowledge import load_pack
from concierge.prompt import MEMORY_HEADER, build_instructions
from concierge.testing.fake_llm import FakeLLM

MEMORY = f'{MEMORY_HEADER}\n- name: "Ada" (voice, 2026-10-19)\nLast visit: asked about the portfolio site.'


def _instructions_text(item: llm.ChatItem) -> str:
    assert item.type == "message"
    return "".join(part for part in item.content if isinstance(part, str))


def test_agent_takes_built_instructions_and_no_tools() -> None:
    pack = load_pack()
    agent = ConciergeAgent(pack, MEMORY)
    assert isinstance(agent, Agent)
    assert agent.instructions == build_instructions(pack, MEMORY)
    assert ConciergeAgent(pack).instructions == build_instructions(pack, None)
    assert agent.tools == []


async def test_prefix_is_stable_across_two_turns() -> None:
    pack = load_pack()
    expected = build_instructions(pack, MEMORY)
    fake = FakeLLM(["Michael is a systems and process engineer.", "He studied computer science at Duke."])
    agent = ConciergeAgent(pack, MEMORY)

    with fake_job_context():
        async with AgentSession(llm=fake) as session:
            await session.start(agent)
            await session.run(user_input="What does Michael do?")
            await session.run(user_input="Where did he study?")

            assert len(fake.calls) == 2
            first, second = (call.chat_ctx.items for call in fake.calls)

            # Both calls open with the same instructions item, holding exactly the built prompt (§5 blocks 1–3).
            for items in (first, second):
                head = items[0]
                assert (head.type, head.id, head.role) == ("message", INSTRUCTIONS_MESSAGE_ID, "system")
                assert _instructions_text(head) == expected
            assert first[0].model_dump_json() == second[0].model_dump_json()

            # Call 2's context begins with every item of call 1, in order and byte for byte.
            assert len(second) > len(first)
            assert [i.model_dump_json() for i in second[: len(first)]] == [i.model_dump_json() for i in first]

            # The conversation is what grew: call 1's reply and the second user turn follow the shared prefix.
            tail = [(i.role, i.text_content) for i in second[len(first) :] if i.type == "message"]
            assert tail == [
                ("assistant", "Michael is a systems and process engineer."),
                ("user", "Where did he study?"),
            ]

            # The session's instructions were not rewritten between the turns.
            assert session.current_agent is agent
            assert agent.instructions == expected

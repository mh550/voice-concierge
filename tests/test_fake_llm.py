import json

import pytest
from livekit.agents import llm
from livekit.agents.metrics import LLMMetrics

from concierge.testing.fake_llm import FakeLLM, FakeLLMStream, FakeResponse, FakeToolCall


def _ctx(text: str = "hello") -> llm.ChatContext:
    ctx = llm.ChatContext.empty()
    ctx.add_message(role="user", content=text)
    return ctx


async def _chunks(stream: llm.LLMStream) -> list[llm.ChatChunk]:
    async with stream:
        return [chunk async for chunk in stream]


async def test_text_chunks_concatenate_to_script() -> None:
    text = "Michael builds voice agents and data tools."
    fake = FakeLLM([FakeResponse(text=text, chunk_size=5)])
    stream = fake.chat(chat_ctx=_ctx())
    assert isinstance(stream, FakeLLMStream)
    chunks = await _chunks(stream)
    content = [c.delta.content for c in chunks if c.delta and c.delta.content]
    assert "".join(content) == text
    assert len(content) == -(-len(text) // 5)
    assert all(c.delta.role == "assistant" for c in chunks if c.delta)
    assert len({c.id for c in chunks}) == 1


async def test_collect_returns_text() -> None:
    fake = FakeLLM(["First reply.", "Second reply."])
    assert (await fake.chat(chat_ctx=_ctx()).collect()).text == "First reply."
    assert (await fake.chat(chat_ctx=_ctx()).collect()).text == "Second reply."


async def test_tool_script_yields_function_tool_call() -> None:
    args = {"fact": "works at Acme", "slot": "company"}
    fake = FakeLLM([FakeResponse(tool_call=FakeToolCall(name="remember", arguments=args))])
    chunks = await _chunks(fake.chat(chat_ctx=_ctx()))
    calls = [tc for c in chunks if c.delta for tc in c.delta.tool_calls]
    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call, llm.FunctionToolCall)
    assert call.name == "remember"
    assert json.loads(call.arguments) == args
    assert call.call_id

    fake2 = FakeLLM([FakeResponse(tool_call=FakeToolCall(name="forget_me"))])
    collected = await fake2.chat(chat_ctx=_ctx()).collect()
    assert [(tc.name, json.loads(tc.arguments)) for tc in collected.tool_calls] == [("forget_me", {})]


async def test_last_chunk_carries_usage() -> None:
    fake = FakeLLM([FakeResponse(text="Hi.", prompt_tokens=900, prompt_cached_tokens=640, completion_tokens=3)])
    chunks = await _chunks(fake.chat(chat_ctx=_ctx()))
    assert [c.usage is not None for c in chunks] == [False] * (len(chunks) - 1) + [True]
    usage = chunks[-1].usage
    assert usage == llm.CompletionUsage(
        completion_tokens=3, prompt_tokens=900, prompt_cached_tokens=640, total_tokens=903
    )


async def test_emits_metrics_collected_with_scripted_tokens() -> None:
    fake = FakeLLM([FakeResponse(text="Hello there.", prompt_tokens=1200, prompt_cached_tokens=1024)])
    seen: list[LLMMetrics] = []
    fake.on("metrics_collected", seen.append)
    await fake.chat(chat_ctx=_ctx()).collect()  # collect() closes the stream, which awaits the metrics task
    assert len(seen) == 1
    metrics = seen[0]
    assert isinstance(metrics, LLMMetrics)
    assert (metrics.prompt_tokens, metrics.prompt_cached_tokens) == (1200, 1024)
    assert metrics.metadata is not None
    assert (metrics.metadata.model_name, metrics.metadata.model_provider) == ("fake", "fake")


async def test_records_calls() -> None:
    tool = llm.function_tool(lambda: None, name="ping", description="ping")
    fake = FakeLLM(["a", "b"])
    ctx = _ctx("first")
    await fake.chat(chat_ctx=ctx, tools=[tool], tool_choice="required").collect()
    ctx.add_message(role="user", content="mutated after the call")
    await fake.chat(chat_ctx=ctx).collect()

    assert len(fake.calls) == 2
    first, second = fake.calls
    assert [m.text_content for m in first.chat_ctx.messages()] == ["first"]  # a copy, not the live context
    assert first.tools == [tool]
    assert first.tool_choice == "required"
    assert second.tools == []
    assert second.tool_choice is None
    assert len(second.chat_ctx.messages()) == 2


async def test_running_past_script_fails_clearly() -> None:
    fake = FakeLLM(["only one"])
    await fake.chat(chat_ctx=_ctx()).collect()
    with pytest.raises(AssertionError, match="script"):
        await fake.chat(chat_ctx=_ctx()).collect()


def test_response_needs_exactly_one_of_text_or_tool_call() -> None:
    with pytest.raises(ValueError):
        FakeResponse()
    with pytest.raises(ValueError):
        FakeResponse(text="x", tool_call=FakeToolCall(name="t"))

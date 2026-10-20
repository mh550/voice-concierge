"""A scripted llm.LLM for the offline suite, shaped like livekit-agents 1.8.8 (agents/llm/llm.py).

FakeLLMStream._run pushes ChatChunks the way the real providers do: one chunk per piece of text (or one chunk with
the tool call), each with role "assistant", then a last chunk carrying only CompletionUsage. The base LLMStream's
metrics task turns that usage into the "metrics_collected" event, so the fake never emits metrics itself.

Every chat() call uses up one script entry, cancelled ones included. AgentSession's preemptive generation (on by
default) can start a reply before a voice turn ends, so audio-path tests should turn it off; run(user_input=...)
is not affected.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from livekit.agents import APIStatusError, llm, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr
from pydantic import BaseModel, Field, model_validator


class FakeToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)  # serialized to JSON for FunctionToolCall.arguments


class FakeResponse(BaseModel):
    """One scripted reply: spoken text, a single tool call or a provider error, plus the token counts to report."""

    text: str | None = None
    tool_call: FakeToolCall | None = None
    error: str | None = None  # raised as a non-retryable APIStatusError, the way a refusal or a 4xx surfaces
    prompt_tokens: int = 0
    prompt_cached_tokens: int = 0
    completion_tokens: int = 0
    chunk_size: int = Field(default=8, gt=0)  # characters per text chunk
    delay_s: float = Field(default=0.0, ge=0)  # seconds before the first chunk (a slow provider)

    @model_validator(mode="after")
    def _one_kind(self) -> FakeResponse:
        if sum(x is not None for x in (self.text, self.tool_call, self.error)) != 1:
            raise ValueError("a FakeResponse has exactly one of text, tool_call or error")
        return self


@dataclass
class FakeLLMCall:
    """What one chat() call received. chat_ctx is a deep snapshot, so later session changes (in-place edits included)
    can't rewrite it."""

    chat_ctx: llm.ChatContext
    tools: list[llm.Tool]
    tool_choice: llm.ToolChoice | None
    parallel_tool_calls: bool | None = None


def _snapshot(item: llm.ChatItem) -> llm.ChatItem:
    """A deep copy, except an AgentConfigUpdate's in-memory `_tools` (bound FunctionTools, which hold the agent and
    its tasks, can't be deep-copied): a shallow copy, sharing the tool list."""
    if isinstance(item, llm.AgentConfigUpdate):
        return item.model_copy()
    return item.model_copy(deep=True)


class FakeLLM(llm.LLM):
    def __init__(self, script: Sequence[FakeResponse | str]) -> None:
        super().__init__()
        self._script = [r if isinstance(r, FakeResponse) else FakeResponse(text=r) for r in script]
        self.calls: list[FakeLLMCall] = []

    @property
    def model(self) -> str:
        return "fake"

    @property
    def provider(self) -> str:
        return "fake"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> FakeLLMStream:
        index = len(self.calls)
        self.calls.append(
            FakeLLMCall(
                chat_ctx=llm.ChatContext([_snapshot(item) for item in chat_ctx.items]),
                tools=list(tools or []),
                tool_choice=tool_choice if utils.is_given(tool_choice) else None,
                parallel_tool_calls=parallel_tool_calls if utils.is_given(parallel_tool_calls) else None,
            )
        )
        response = self._script[index] if index < len(self._script) else None
        return FakeLLMStream(
            self, chat_ctx=chat_ctx, tools=list(tools or []), conn_options=conn_options, response=response, index=index
        )


class FakeLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm_: FakeLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
        response: FakeResponse | None,
        index: int,
    ) -> None:
        # Set before super().__init__, which starts the task that runs _run().
        self._response = response
        self._index = index
        super().__init__(llm_, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)

    async def _run(self) -> None:
        r = self._response
        if r is None:
            raise AssertionError(f"FakeLLM script exhausted: chat() call {self._index + 1} has no scripted response")
        request_id = f"fake-{self._index}"
        if r.delay_s:
            await asyncio.sleep(r.delay_s)
        if r.error is not None:
            raise APIStatusError(r.error, retryable=False)
        if r.tool_call is not None:
            call = llm.FunctionToolCall(
                name=r.tool_call.name,
                arguments=json.dumps(r.tool_call.arguments),
                call_id=utils.shortuuid("fake_call_"),
            )
            await self._send(request_id, llm.ChoiceDelta(role="assistant", tool_calls=[call]))
        else:
            text = r.text or ""
            for start in range(0, len(text), r.chunk_size):
                piece = text[start : start + r.chunk_size]
                await self._send(request_id, llm.ChoiceDelta(role="assistant", content=piece))
        usage = llm.CompletionUsage(
            completion_tokens=r.completion_tokens,
            prompt_tokens=r.prompt_tokens,
            prompt_cached_tokens=r.prompt_cached_tokens,
            total_tokens=r.prompt_tokens + r.completion_tokens,
        )
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, usage=usage))

    async def _send(self, request_id: str, delta: llm.ChoiceDelta) -> None:
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, delta=delta))
        await asyncio.sleep(0)  # yield between chunks, so a test can interrupt a reply partway

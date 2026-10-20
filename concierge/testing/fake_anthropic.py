"""An offline anthropic.AsyncAnthropic for tests of concierge.claude_llm, shaped like anthropic 1.15.0.

The plugin (livekit/plugins/anthropic/llm.py) calls `await client.messages.create(..., stream=True, **extra)` and then
`async with stream: async for event in stream`, reading `RawMessageStreamEvent`s, and reads `client._base_url` for
its `provider`. FakeAnthropicClient is a real AsyncAnthropic (so `_base_url` and `api_key` exist and nothing goes on
the network at construction) whose `messages` records every `create` call's kwargs and streams scripted events built
from the SDK's own pydantic types.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

import anthropic
from anthropic import types as t
from anthropic.resources.messages import AsyncMessages

_CREATE = inspect.signature(AsyncMessages.create)


def _message_start(input_tokens: int) -> t.RawMessageStreamEvent:
    return t.RawMessageStartEvent.model_validate(
        {
            "type": "message_start",
            "message": {
                "id": "msg_fake",
                "type": "message",
                "role": "assistant",
                "model": "fake",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 1},
            },
        }
    )


def _block(index: int, start: dict[str, Any], deltas: list[dict[str, Any]]) -> list[t.RawMessageStreamEvent]:
    first = {"type": "content_block_start", "index": index, "content_block": start}
    events: list[t.RawMessageStreamEvent] = [t.RawContentBlockStartEvent.model_validate(first)]
    events += [
        t.RawContentBlockDeltaEvent.model_validate({"type": "content_block_delta", "index": index, "delta": d})
        for d in deltas
    ]
    events.append(t.RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": index}))
    return events


def reply_events(
    text: str, *, thinking: str | None = None, chunk_size: int = 8, stop_reason: str = "end_turn"
) -> list[t.RawMessageStreamEvent]:
    """The events of one streamed reply: an optional thinking block, then the text in chunks, then stop_reason."""
    events = [_message_start(input_tokens=12)]
    index = 0
    if thinking is not None:
        events += _block(
            index,
            {"type": "thinking", "thinking": "", "signature": ""},
            [{"type": "thinking_delta", "thinking": thinking}, {"type": "signature_delta", "signature": "sig"}],
        )
        index += 1
    pieces = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    events += _block(index, {"type": "text", "text": ""}, [{"type": "text_delta", "text": p} for p in pieces])
    events.append(
        t.RawMessageDeltaEvent.model_validate(
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": len(pieces)},
            }
        )
    )
    events.append(t.RawMessageStopEvent.model_validate({"type": "message_stop"}))
    return events


class FakeStream:
    """Stands in for anthropic.AsyncStream: an async context manager that iterates the scripted events."""

    def __init__(self, events: list[t.RawMessageStreamEvent]) -> None:
        self._events = events

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[t.RawMessageStreamEvent]:
        for event in self._events:
            yield event


class FakeMessages:
    def __init__(self, replies: list[list[t.RawMessageStreamEvent]]) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeStream:  # noqa: ANN401 - mirrors the SDK's keyword surface
        _CREATE.bind(None, **kwargs)  # a keyword the real SDK lacks raises TypeError here, as it would live
        self.calls.append(kwargs)
        return FakeStream(self._replies.pop(0) if self._replies else reply_events("ok"))


class FakeAnthropicClient(anthropic.AsyncAnthropic):
    """A real AsyncAnthropic with an offline `messages`; `messages.calls` holds each request's kwargs."""

    def __init__(self, replies: list[list[t.RawMessageStreamEvent]] | None = None) -> None:
        super().__init__(api_key="offline-fake-key", max_retries=0)
        self.fake_messages = FakeMessages(replies or [])
        self.__dict__["messages"] = self.fake_messages  # `messages` is a cached_property on the SDK client

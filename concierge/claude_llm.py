"""Claude through livekit-plugins-anthropic 1.8.8, with the request settings each stage needs (spec D5, B1, §4.10).

The plugin's `LLM.chat(extra_kwargs=...)` merges extra_kwargs into `messages.create` (llm.py:165-166) but then sets
`max_tokens` from the constructor (llm.py:183), so a stage's max_tokens goes to the constructor. Its prefill guard
covers only the 4.6 ids (llm.py:41-46, 227), and 5.x models reject a trailing assistant message, so `chat()` here
appends a user turn itself. No temperature is ever passed: 5.x models reject sampling parameters.

The plugin's stream never reads `stop_reason` (llm.py:357-418), so a refusal (including one the server-side fallback
couldn't rescue) would look like a finished reply. ClaudeLLMStream records it, and for the background stages turns it
into a non-retryable APIStatusError, so a declined extraction or summary is never stored.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

import anthropic as anthropic_sdk
from anthropic import types as anthropic_types
from livekit.agents import APIStatusError, llm
from livekit.agents.llm.tool_context import Tool
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr
from livekit.agents.utils import is_given
from livekit.plugins import anthropic

if TYPE_CHECKING:
    from concierge.config import Stage

# Anthropic's server-side refusal fallback: the beta header plus the body field that turns it on.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Haiku 5.5 accepts thinking disabled at its default effort: the fastest first token for a spoken reply.
CONVERSATION_KWARGS: dict[str, Any] = {"thinking": {"type": "disabled"}}
# Extractor and summarizer run in the background, so they trade speed for a longer, steadier answer.
BACKGROUND_KWARGS: dict[str, Any] = {
    "output_config": {"effort": "low"},
    "extra_headers": {"anthropic-beta": FALLBACK_BETA},
    "extra_body": {"fallbacks": "default"},
}
BACKGROUND_MAX_TOKENS = 4096

# The text of the user turn appended after a trailing assistant message; the plugin's own guard uses the same.
TRAILING_USER_TEXT = "."


# Request kwargs whose dicts combine (a caller's header doesn't drop the fallback beta, a caller's output format
# doesn't drop the effort); any other key, such as the tagged union `thinking`, is replaced whole.
MERGED_KEYS = frozenset({"extra_headers", "extra_body", "output_config"})


def merge_kwargs(base: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """A fresh copy of base updated with extra; the MERGED_KEYS dicts are merged one level down."""
    merged = copy.deepcopy(dict(base))
    for key, value in copy.deepcopy(dict(extra)).items():
        if key in MERGED_KEYS and isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def ends_on_user(chat_ctx: llm.ChatContext) -> llm.ChatContext:
    """chat_ctx itself if its Anthropic messages end on the user; otherwise a copy with a short user turn appended."""
    messages, _ = chat_ctx.to_provider_format(format="anthropic")
    if not messages or messages[-1]["role"] != "assistant":
        return chat_ctx
    ctx = chat_ctx.copy()
    ctx.add_message(role="user", content=TRAILING_USER_TEXT)
    return ctx


class ClaudeLLMStream(anthropic.LLMStream):
    """The plugin stream plus the reply's stop_reason; raises on a refusal when its LLM says so."""

    stop_reason: str | None = None

    def _parse_event(self, event: anthropic_types.RawMessageStreamEvent) -> llm.ChatChunk | None:
        if event.type == "message_delta" and event.delta.stop_reason is not None:
            self.stop_reason = event.delta.stop_reason
        return super()._parse_event(event)

    async def _run(self) -> None:
        self.stop_reason = None  # per attempt
        await super()._run()
        if self.stop_reason == "refusal" and isinstance(self._llm, ClaudeLLM) and self._llm.refusal_is_error:
            raise APIStatusError(f"{self._llm.model} refused the request", retryable=False)


class ClaudeLLM(anthropic.LLM):
    """The plugin LLM with fixed per-stage request kwargs merged into every chat() call."""

    def __init__(
        self,
        *,
        model: str,
        extra_kwargs: Mapping[str, Any] | None = None,
        caching: NotGivenOr[Literal["ephemeral"]] = NOT_GIVEN,
        max_tokens: NotGivenOr[int] = NOT_GIVEN,
        client: anthropic_sdk.AsyncClient | None = None,
        refusal_is_error: bool = False,
    ) -> None:
        super().__init__(model=model, caching=caching, max_tokens=max_tokens, client=client)
        self._stage_kwargs: dict[str, Any] = copy.deepcopy(dict(extra_kwargs or {}))
        self.refusal_is_error = refusal_is_error

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> ClaudeLLMStream:
        stream = super().chat(
            chat_ctx=ends_on_user(chat_ctx),
            tools=tools,
            conn_options=conn_options,
            parallel_tool_calls=parallel_tool_calls,
            tool_choice=tool_choice,
            extra_kwargs=merge_kwargs(self._stage_kwargs, extra_kwargs if is_given(extra_kwargs) else {}),
        )
        # The plugin's chat() builds its own LLMStream (llm.py:282). Its task is created in __init__ but hasn't run
        # yet (no await since), so switching the instance's class here takes effect before the first _run.
        stream.__class__ = ClaudeLLMStream
        assert isinstance(stream, ClaudeLLMStream)
        return stream


def build_claude_llm(stage: Stage, model: str, *, client: anthropic_sdk.AsyncClient | None = None) -> ClaudeLLM:
    """The Claude LLM for one stage. Raises ValueError naming ANTHROPIC_API_KEY when the key is unset."""
    if stage == "conversation":
        return ClaudeLLM(model=model, extra_kwargs=CONVERSATION_KWARGS, caching="ephemeral", client=client)
    return ClaudeLLM(
        model=model,
        extra_kwargs=BACKGROUND_KWARGS,
        max_tokens=BACKGROUND_MAX_TOKENS,
        client=client,
        refusal_is_error=True,  # a declined extraction or summary is dropped, never stored
    )

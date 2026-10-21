"""Per-turn latency and tokens (spec §4.7, §4.10, §6 `concierge.metrics`, B9; plan C6 Part 3).

Latency comes from `ChatMessage.metrics` (a `MetricsReport`, llm/chat_context.py:286: every key optional, the user
keys on user messages, the assistant keys on assistant messages) as `conversation_item_added` sends them; tokens come
from the conversation LLM's `metrics_collected` (`LLMMetrics`, agents/metrics/base.py:21). A turn opens at a user
message (or at the greeting) and closes on `listening` after a reply, or at the next user message, so a tool call's
two assistant messages stay one turn. A `listening` with no assistant message since the agent last started speaking
is a paused reply (pause on interruption, voice/agent_activity.py:2390), not the end of one; a reply interrupted while
paused gets no later `listening` (agent_activity.py:3946), so its message closes the turn. Closing a turn writes one
`anonymous_turn_metrics` row and publishes it; the handlers only start tasks, so nothing here runs on the turn path.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any

from livekit.agents import llm
from livekit.agents.metrics import LLMMetrics
from livekit.agents.voice.events import AgentStateChangedEvent, ConversationItemAddedEvent

from concierge.contract import MetricsPayload
from concierge.store import Store
from concierge.tasks import track

logger = logging.getLogger("concierge.metrics")

CLOSE_WAIT_S = 5.0  # aclose's wait for the store writes; the store closes right after it
USER_KEYS = {"end_of_turn_delay": "eou_ms", "transcription_delay": "stt_ms",
             "on_user_turn_completed_delay": "memory_on_turn_path_ms"}
ASSISTANT_KEYS = {"llm_node_ttft": "llm_ttft_ms", "tts_node_ttfb": "tts_ttfb_ms", "e2e_latency": "total_ms"}


def _ms(value: object, *, scale: float = 1000.0) -> float | None:
    """Seconds (or ms, with scale=1) → whole ms; None for a missing key, a non-number, a non-finite or a negative
    value (ttft is -1 when nothing was generated, metrics/base.py:28)."""
    if not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        return None
    return float(round(value * scale))


class TurnMetricsCollector:
    """One session's turns. `store` None: published only. `compactions` is the Compactor's applied count."""

    def __init__(
        self,
        store: Store | None,
        session_id: str,
        publish: Callable[[MetricsPayload], Awaitable[None]],
        *,
        preload_ms: float | None = None,
        compactions: Callable[[], int] = lambda: 0,
    ) -> None:
        self._store = store
        self._session_id = session_id
        self._publish: Callable[[MetricsPayload], Awaitable[None]] | None = publish
        self._preload_ms = preload_ms
        self._compactions = compactions
        self._compactions_seen = compactions()
        self._turn = 1
        self._replied = False  # the open turn has an assistant message
        self._said_since_speaking = True  # an assistant message arrived since the agent last entered `speaking`
        self._listening = False
        self._closed = False
        self._fields: dict[str, float | None] = {}
        self._tokens: tuple[int, int] | None = None  # (prompt, cached), summed since the last turn closed
        self._extraction_ms: float | None = None
        # about_agent.cache.cached_share: cached / prompt tokens of the last closed turn that had LLM metrics
        # (None before one, or when its prompt_tokens were 0)
        self.last_cached_share: float | None = None
        self._writes: set[asyncio.Task[Any]] = set()
        self._publishes: set[asyncio.Task[Any]] = set()

    def on_item_added(self, ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if not isinstance(item, llm.ChatMessage):  # an AgentHandoff
            return
        metrics: dict[str, Any] = dict(item.metrics or {})
        if item.role == "user":
            if self._replied:  # no `listening` since the reply (an interruption): that turn is over
                self._close()
            # A second user message before any reply replaces the first: the reply answers the last one.
            self._fields = {key: _ms(metrics.get(name)) for name, key in USER_KEYS.items()}
        elif item.role == "assistant":
            self._replied = self._said_since_speaking = True  # opens a turn when no user message did (the greeting)
            for name, key in ASSISTANT_KEYS.items():
                if self._fields.get(key) is None:  # first non-null wins: a tool call's later message adds none
                    self._fields[key] = _ms(metrics.get(name))
            if item.interrupted and self._listening:  # cut off while paused: no `listening` will follow
                self._close()

    def on_state_changed(self, ev: AgentStateChangedEvent) -> None:
        self._listening = ev.new_state == "listening"
        if ev.new_state == "speaking":
            self._said_since_speaking = False
        elif self._listening and self._replied and self._said_since_speaking:
            self._close()

    def on_llm_metrics(self, m: LLMMetrics) -> None:
        if m.cancelled:  # a stream cut off before its usage chunk; a discarded preemptive call that finished counts
            return
        prompt, cached = self._tokens or (0, 0)
        self._tokens = (prompt + m.prompt_tokens, cached + m.prompt_cached_tokens)

    def note_extraction(self, ms: float | None) -> None:
        """A merge's extraction time, carried by the next turn that closes (the writer's `on_merged`)."""
        if ms is not None:
            self._extraction_ms = ms

    def stop_publishing(self) -> None:
        """First in the shutdown: the room is disconnected by then. Rows are still written."""
        self._publish = None
        for task in list(self._publishes):
            task.cancel()

    async def idle(self) -> None:
        """Wait for the writes and publishes started so far."""
        while pending := self._writes | self._publishes:
            await asyncio.wait(pending)

    async def aclose(self) -> None:
        """Write a turn left open with a reply (not published), then wait at most CLOSE_WAIT_S for the writes, so
        the store can close after it. A write past the wait is left to fail on the closed store."""
        self.stop_publishing()
        if self._replied:
            self._close()
        self._closed = True  # the store closes next: a turn closing while the session drains is dropped
        if self._writes:
            _, late = await asyncio.wait(set(self._writes), timeout=CLOSE_WAIT_S)
            if late:
                logger.warning("%d turn metrics writes missed the %.0f s close wait", len(late), CLOSE_WAIT_S)

    def _close(self) -> None:
        compactions = self._compactions()
        prompt, cached = self._tokens if self._tokens is not None else (None, None)
        if prompt is not None and cached is not None:
            self.last_cached_share = min(cached / prompt, 1.0) if prompt > 0 else None
        payload = MetricsPayload(
            turn=self._turn,
            **self._fields,
            preload_ms=_ms(self._preload_ms, scale=1) if self._turn == 1 else None,
            extraction_ms=_ms(self._extraction_ms, scale=1),
            prompt_tokens=prompt,
            cached_tokens=cached,
            compacted=compactions > self._compactions_seen,
        )
        self._turn += 1
        self._replied = False
        self._fields, self._tokens, self._extraction_ms, self._compactions_seen = {}, None, None, compactions
        if self._store is not None and not self._closed:
            write = asyncio.to_thread(self._store.add_turn_metrics, self._session_id, payload)
            track(self._writes, write, log=logger)
        if self._publish is not None:
            track(self._publishes, self._publish(payload), log=logger)

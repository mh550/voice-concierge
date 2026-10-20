"""Typed turns (spec §4.5): tag the channel, then hand the turn to the framework's own text callback.

1.8's default callback (`voice/room_io/types.py`) claims the user turn, interrupts, and calls `generate_reply`, but
records no channel. Typed turns never reach `on_user_turn_completed`, so channels are matched later from
`conversation_item_added` (which fires for both doors) against the texts tagged here.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Literal

from livekit.agents.voice.room_io.types import TextInputEvent, _default_text_input_cb

if TYPE_CHECKING:
    from livekit.agents import AgentSession

logger = logging.getLogger("concierge.text_input")

Channel = Literal["voice", "text"]


def make_text_input_cb(
    on_text: Callable[[TextInputEvent], None],
    on_dropped: Callable[[TextInputEvent], None] | None = None,
) -> Callable[[AgentSession, TextInputEvent], Coroutine[None, None, None]]:
    """A `TextInputOptions.text_input_cb` that calls `on_text` (synchronously, so it can't stall the turn) and
    then awaits the default callback, keeping the framework's turn handling. A failing tag never drops the turn; a
    turn the default drops (it raises, e.g. `interrupt()` during uninterruptible speech) is passed to `on_dropped`."""

    async def text_input_cb(sess: AgentSession, ev: TextInputEvent) -> None:
        try:
            on_text(ev)
        except Exception:
            logger.exception("tagging a typed turn failed")  # no text: it's the visitor's words
        try:
            await _default_text_input_cb(sess, ev)
        except Exception:
            if on_dropped is not None:
                on_dropped(ev)
            raise

    return text_input_cb


class ChannelTags:
    """Which user messages arrived typed. Each typed text matches one later user message; the rest are voice.

    `channel_of` is consumed from `conversation_item_added` (C4); until then the oldest unmatched tags are dropped
    past MAX_PENDING, so a long typed session can't grow this without bound."""

    MAX_PENDING = 32

    def __init__(self) -> None:
        self._typed: deque[str] = deque(maxlen=self.MAX_PENDING)

    def on_text(self, ev: TextInputEvent) -> None:
        self._typed.append(ev.text)

    def on_dropped(self, ev: TextInputEvent) -> None:
        """The typed turn never reached the chat, so no user message will match its tag."""
        for i in range(len(self._typed) - 1, -1, -1):
            if self._typed[i] == ev.text:
                del self._typed[i]
                return

    def channel_of(self, user_text: str) -> Channel:
        if user_text in self._typed:
            self._typed.remove(user_text)
            return "text"
        return "voice"

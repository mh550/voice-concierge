"""A session that only speaks and closes, for the limit and RPC tests (plan C6 "Fixtures and fakes").

Shaped from livekit-agents 1.8.8: `AgentSession.say(text, *, audio, allow_interruptions, add_to_chat_ctx) ->
SpeechHandle` (voice/agent_session.py:1544-1551; it raises RuntimeError when the session isn't running, :1552-1553),
`SpeechHandle.wait_for_playout()` (voice/speech_handle.py:229) and `AgentSession.aclose()` (agent_session.py:1445).
"""

from __future__ import annotations

import asyncio
from typing import Any


class FakeSpeechHandle:
    def __init__(self, say_s: float) -> None:
        self._say_s = say_s

    async def wait_for_playout(self) -> None:
        await asyncio.sleep(self._say_s)


class FakeSpeakingSession:
    def __init__(self, *, say_s: float = 0.0, fail: Exception | None = None) -> None:
        self.said: list[tuple[str, dict[str, Any]]] = []  # (text, keyword arguments), in order
        self.closed = 0
        self._say_s = say_s
        self._fail = fail

    def say(self, text: str, **kwargs: Any) -> FakeSpeechHandle:  # noqa: ANN401
        if self._fail is not None:
            raise self._fail
        self.said.append((text, kwargs))
        return FakeSpeechHandle(self._say_s)

    async def aclose(self) -> None:
        self.closed += 1

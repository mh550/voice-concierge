"""A session that only speaks and closes, for the limit and RPC tests (plan C6 "Fixtures and fakes").

Shaped from livekit-agents 1.8.8: `AgentSession.say(text, *, audio, allow_interruptions, add_to_chat_ctx) ->
SpeechHandle` (voice/agent_session.py:1544-1551; it raises RuntimeError when the session isn't running, :1552-1553),
`SpeechHandle.wait_for_playout()` (voice/speech_handle.py:229), `AgentSession.interrupt(*, force) -> Future`
(agent_session.py:1648; it raises RuntimeError when the session isn't running) and `AgentSession.aclose()`
(agent_session.py:1445). `current_reply_s` models a reply already playing: a new speech is queued behind it
(agent_activity.py `_schedule_speech`) until `interrupt` cuts it (agent_activity.py:1909).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


class FakeSpeechHandle:
    def __init__(self, say_s: float) -> None:
        self._say_s = say_s
        self.played_out = False

    async def wait_for_playout(self) -> None:
        await asyncio.sleep(self._say_s)
        self.played_out = True


class FakeSpeakingSession:
    def __init__(self, *, say_s: float = 0.0, fail: Exception | None = None, current_reply_s: float = 0.0) -> None:
        self.said: list[tuple[str, dict[str, Any]]] = []  # (text, keyword arguments), in order
        self.interrupts: list[bool] = []  # the `force` of each interrupt() call
        self.handles: list[FakeSpeechHandle] = []
        self.closed = 0
        self._say_s = say_s
        self._fail = fail
        self._reply_ends = time.monotonic() + current_reply_s

    def say(self, text: str, **kwargs: Any) -> FakeSpeechHandle:  # noqa: ANN401
        if self._fail is not None:
            raise self._fail
        self.said.append((text, kwargs))
        handle = FakeSpeechHandle(max(0.0, self._reply_ends - time.monotonic()) + self._say_s)
        self.handles.append(handle)
        return handle

    def interrupt(self, *, force: bool = False) -> asyncio.Future[None]:
        if self._fail is not None:
            raise self._fail
        self.interrupts.append(force)
        self._reply_ends = time.monotonic()
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        done.set_result(None)
        return done

    async def aclose(self) -> None:
        self.closed += 1

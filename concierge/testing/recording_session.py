"""A stand-in for AgentSession in the entrypoint tests (tests/conftest.py's `recording_session` installs it)."""

from __future__ import annotations

import inspect
from typing import Any

from livekit.agents import AgentSession

from concierge.text_input import ChannelTags


class RecordingSession:
    """Keeps what it was built and started with and the replies asked of it; each call binds the real AgentSession
    signature."""

    instances: list[RecordingSession] = []
    tags: list[ChannelTags] = []

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        inspect.signature(AgentSession.__init__).bind(None, **kwargs)  # the real constructor takes these
        self.kwargs = kwargs
        self.started: dict[str, Any] | None = None
        self.replies: list[dict[str, Any]] = []
        RecordingSession.instances.append(self)

    async def start(self, agent: Any = None, **kwargs: Any) -> None:  # noqa: ANN401
        inspect.signature(AgentSession.start).bind(None, agent, **kwargs)
        self.started = {"agent": agent, **kwargs}

    def generate_reply(self, **kwargs: Any) -> str:  # noqa: ANN401
        inspect.signature(AgentSession.generate_reply).bind(None, **kwargs)
        self.replies.append(kwargs)
        return "speech-handle"

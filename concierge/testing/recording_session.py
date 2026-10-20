"""A stand-in for AgentSession in the entrypoint tests (tests/conftest.py's `recording_session` installs it)."""

from __future__ import annotations

import inspect
from typing import Any

from livekit.agents import AgentSession

from concierge.text_input import ChannelTags


class RecordingSession:
    """Keeps what it was built and started with; both calls bind the real AgentSession signatures."""

    instances: list[RecordingSession] = []
    tags: list[ChannelTags] = []

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        inspect.signature(AgentSession.__init__).bind(None, **kwargs)  # the real constructor takes these
        self.kwargs = kwargs
        self.started: dict[str, Any] | None = None
        RecordingSession.instances.append(self)

    async def start(self, agent: Any = None, **kwargs: Any) -> None:  # noqa: ANN401
        inspect.signature(AgentSession.start).bind(None, agent, **kwargs)
        self.started = {"agent": agent, **kwargs}

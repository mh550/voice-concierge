"""Smoke test: the pinned LiveKit Agents version is the one installed."""

import livekit.agents


def test_livekit_agents_version_is_pinned() -> None:
    assert livekit.agents.__version__ == "1.8.8"

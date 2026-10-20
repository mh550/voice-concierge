"""Helpers for tests that drive start_session to its first reply and through its shutdown callback."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from livekit.agents import llm

from concierge.config import Settings
from concierge.session import Started, start_session
from concierge.store import Store

VISITOR = "3f2b8c1e-9a4d-4c7b-8e21-5d6f7a8b9c0d"
METADATA = json.dumps({"visitor_id": VISITOR, "channel_hint": "web"})
VISIT_SUMMARY = "The visitor works at Acme and asked what Michael builds."  # the summarizer fixture's reply


async def start(ctx: Any, store: Store | None) -> Started:  # noqa: ANN401 (fake_job_context's JobContext)
    """One session to its first reply, with session_started written."""
    started = await start_session(ctx, store, Settings())
    await started.greeting
    for task in list(started.tasks):
        await task
    return started


async def shutdown(ctx: Any, started: Started, reason: str = "test") -> None:  # noqa: ANN401
    """What the job does at shutdown: close the session, then run the callbacks (job_proc_lazy_main.py)."""
    await started.session.aclose()
    for callback in ctx._shutdown_callbacks:
        await callback(reason)


def stage_llms(**by_stage: llm.LLM) -> Callable[..., llm.LLM]:
    """A `build_llm(stage, settings)` stand-in that gives each stage its own fake; an unexpected stage is a KeyError."""
    return lambda stage, settings=None: by_stage[stage]

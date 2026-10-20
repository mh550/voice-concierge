"""One visitor session: preload, agent, `session.start`, greeting, and the journaled start and end (spec §4.3;
plan C3 "The preload sequence", "Session start and end").

Every store call runs in a thread (the store blocks up to 5 s), and none sits between the preload and the greeting:
`session_started` is written by a background task after the greeting is queued.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from livekit.agents import AgentSession, JobContext
from livekit.agents.voice import SpeechHandle
from livekit.agents.voice.agent_session import RecordingOptions
from livekit.agents.voice.room_io import RoomOptions, TextInputOptions
from pydantic import ValidationError

from concierge.agent import ConciergeAgent
from concierge.config import Settings, build_llm, build_stt, build_tts
from concierge.dispatch import DispatchInfo, parse_dispatch
from concierge.greeting import greeting_instructions
from concierge.knowledge import load_pack
from concierge.models import JournalType
from concierge.preload import Preloaded, preload
from concierge.store import Store, StoreError, ThreadMissing
from concierge.text_input import ChannelTags, make_text_input_cb

logger = logging.getLogger("concierge.session")

# D9: the preload runs while the room is already connected and RoomIO's lk.chat and pre-connect audio handlers
# aren't registered yet (session.start registers them), so it gets a short deadline. A normal one takes < 1 ms.
PRELOAD_TIMEOUT_S = 1.0

_STORE_ERRORS = (StoreError, sqlite3.Error, ValidationError)


@dataclass
class Started:
    """What start_session set going; `greeting` is the first reply's handle (not awaited by start_session)."""

    session: AgentSession
    preloaded: Preloaded | None
    session_id: str
    greeting: SpeechHandle
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)


def recording_options(settings: Settings | None = None) -> RecordingOptions:
    """B11: no visitor audio at LiveKit unless CONCIERGE_RECORD_AUDIO=1; transcripts, traces and logs stay on
    (unset keys default to True in `_resolve_recording_options`), with redaction requested."""
    s = settings or Settings()
    return {"audio": s.record_audio, "redaction": True}


def room_start_kwargs(ctx: JobContext, info: DispatchInfo, settings: Settings, channels: ChannelTags) -> dict[str, Any]:
    """The room half of session.start. A seam: tests drive a real AgentSession without a room (fake_job_context's
    room never connects, and RoomIO can't start on it)."""
    return {
        "room": ctx.room,
        "room_options": RoomOptions(
            participant_identity=f"visitor-{info.visitor_id}",
            text_input=TextInputOptions(
                text_input_cb=make_text_input_cb(channels.on_text, on_dropped=channels.on_dropped),
            ),
        ),
        "record": recording_options(settings),
    }


def build_session(ctx: JobContext, settings: Settings) -> AgentSession:
    return AgentSession(
        llm=build_llm("conversation", settings),
        stt=build_stt(settings),
        tts=build_tts(settings),
        vad=ctx.proc.userdata["vad"],
        # D7. Interruptions by VAD too: with no mode, dev/console mode builds the hosted adaptive detector.
        turn_handling={"turn_detection": "vad", "interruption": {"mode": "vad"}},
    )


async def _preload_or_none(task: asyncio.Task[Preloaded] | None) -> Preloaded | None:
    """The visitor's memory, or None (a session without memory). On the deadline the task is left running, not
    cancelled: its store thread can't be stopped, so on_shutdown waits for it before closing the store. Only the
    error type is logged: a message can quote visitor data."""
    if task is None:
        return None
    done, _ = await asyncio.wait({task}, timeout=PRELOAD_TIMEOUT_S)
    try:
        if not done:
            raise TimeoutError
        return task.result()
    except (*_STORE_ERRORS, TimeoutError) as exc:
        logger.warning("no memory this session: the preload failed (%s)", type(exc).__name__)
        return None


def _agent_or_memoryless(pack: str, preloaded: Preloaded | None) -> ConciergeAgent:
    """The agent with the visitor's memory block, or without one if build_instructions rejects it (the renderer
    keeps it under the cap, so this is the backstop that keeps a session from failing over memory)."""
    try:
        return ConciergeAgent(pack, preloaded.block if preloaded else None)
    except ValueError:
        logger.warning("no memory this session: the memory block was rejected")
        return ConciergeAgent(pack)


async def _journal(store: Store, thread_id: str, session_id: str, kind: JournalType, payload: dict[str, Any]) -> None:
    """One journal row, off the loop. A failure is logged by type and never raised: the session goes on."""
    try:
        await asyncio.to_thread(store.journal, thread_id, session_id, kind, payload)
    except ThreadMissing:
        logger.info("not journaling %s: the visitor's memory was erased", kind)
    except _STORE_ERRORS as exc:
        logger.warning("could not journal %s (%s)", kind, type(exc).__name__)


def _track[T](tasks: set[asyncio.Task[Any]], coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
    """A background task kept in `tasks` until it is done (on_shutdown waits for what is left)."""
    task = asyncio.create_task(coro)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task


async def start_session(ctx: JobContext, store: Store | None, settings: Settings) -> Started:
    """Preload (concurrent with ctx.connect()) → ConciergeAgent → session.start → the greeting, then
    session_started in the background. The shutdown callback journals session_ended and closes the store."""
    info = parse_dispatch(ctx.job.metadata)  # the entrypoint validated it; pure and cheap
    session_id = uuid.uuid4().hex
    began = time.monotonic()
    tasks: set[asyncio.Task[Any]] = set()
    preloaded: Preloaded | None = None

    async def on_shutdown(reason: str) -> None:  # a plain async def: add_shutdown_callback reads its __code__
        # One ordered callback: the job runs its shutdown callbacks concurrently, so a separate close could
        # close the store under the session_ended write.
        if store is None:
            return
        try:
            for result in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(result, BaseException):  # a late preload's error, already logged on time otherwise
                    logger.warning("a background store task failed (%s)", type(result).__name__)
            if preloaded is not None:
                ended = {"reason": reason, "duration_s": round(time.monotonic() - began, 1)}
                await _journal(store, preloaded.thread_id, session_id, "session_ended", ended)
        finally:
            await asyncio.to_thread(store.close)

    ctx.add_shutdown_callback(on_shutdown)  # first, so a failed connect or session.start still closes the store
    # Spec §4.0: the store reads overlap the room connection (connect is idempotent; session.start's is a no-op).
    # The preload is a tracked task, so a failed connect or a missed deadline still leaves it for on_shutdown.
    preloading = _track(tasks, preload(store, info.visitor_id, session_id)) if store is not None else None
    _, preloaded = await asyncio.gather(ctx.connect(), _preload_or_none(preloading))

    session = build_session(ctx, settings)
    await session.start(
        agent=_agent_or_memoryless(load_pack(), preloaded),
        **room_start_kwargs(ctx, info, settings, ChannelTags()),
    )
    greeting = session.generate_reply(instructions=greeting_instructions(preloaded))

    if store is not None and preloaded is not None:
        started = {"visits": preloaded.visits, "preload_ms": preloaded.ms, "returning": preloaded.block is not None}
        _track(tasks, _journal(store, preloaded.thread_id, session_id, "session_started", started))
    return Started(session, preloaded, session_id, greeting, tasks)

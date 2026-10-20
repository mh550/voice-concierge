"""The worker entry point: `python -m concierge.worker start` (scripts/run-worker.sh wraps it).

Explicit dispatch as `concierge` (spec §6). Providers need keys, so they're built only inside the entrypoint, never
at import; importing this module needs no LIVEKIT_*,
ANTHROPIC_API_KEY or OPENROUTER_API_KEY.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from pathlib import Path

from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, JobRequest, cli
from livekit.agents.voice.agent_session import RecordingOptions
from livekit.agents.voice.room_io import RoomOptions, TextInputOptions
from livekit.plugins import silero
from pydantic import ValidationError

from concierge.agent import ConciergeAgent
from concierge.config import Settings, build_llm, build_stt, build_tts
from concierge.dispatch import DispatchError, parse_dispatch
from concierge.knowledge import load_pack
from concierge.preload import Preloaded, preload
from concierge.store import Store, StoreError
from concierge.text_input import ChannelTags, make_text_input_cb

logger = logging.getLogger("concierge.worker")

# D9: the preload runs while the room is already connected and RoomIO's lk.chat and pre-connect audio handlers
# aren't registered yet (session.start registers them), so it gets a short deadline. A normal one takes < 1 ms.
PRELOAD_TIMEOUT_S = 1.0


def recording_options(settings: Settings | None = None) -> RecordingOptions:
    """B11: no visitor audio at LiveKit unless CONCIERGE_RECORD_AUDIO=1; transcripts, traces and logs stay on
    (unset keys default to True in `_resolve_recording_options`), with redaction requested."""
    s = settings or Settings()
    return {"audio": s.record_audio, "redaction": True}


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()  # D7: VAD-only turn detection; the model ships in the wheel


async def on_request(req: JobRequest) -> None:
    await req.accept()  # C6-04 adds the kill switch (reject under CONCIERGE_ENABLED=0 or the off file)


def _open_store(path: Path) -> Store:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return Store(path)


async def _open_or_none(path: Path) -> Store | None:
    """The store, opened off the loop; None (a session without memory) when it can't open. Only the error type is
    logged: a message can quote a path or visitor data."""
    try:
        return await asyncio.to_thread(_open_store, path)
    except (StoreError, sqlite3.Error, OSError) as exc:
        logger.warning("no memory this session: the store did not open (%s)", type(exc).__name__)
        return None


async def _preload_or_none(store: Store | None, visitor_id: str, session_id: str) -> Preloaded | None:
    if store is None:
        return None
    try:
        return await asyncio.wait_for(preload(store, visitor_id, session_id), PRELOAD_TIMEOUT_S)
    except (StoreError, sqlite3.Error, ValidationError, TimeoutError) as exc:
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


server = AgentServer(shutdown_process_timeout=30, setup_fnc=prewarm)


@server.rtc_session(agent_name="concierge", on_request=on_request)
async def entrypoint(ctx: JobContext) -> None:
    try:
        info = parse_dispatch(ctx.job.metadata)
    except DispatchError as exc:
        logger.warning("ending job %s: %s", ctx.job.id, exc)
        ctx.shutdown(reason="bad dispatch metadata")
        return

    settings = Settings()
    store = await _open_or_none(settings.db_path)

    async def close_store() -> None:  # a plain async def: add_shutdown_callback reads its __code__
        if store is not None:
            await asyncio.to_thread(store.close)

    ctx.add_shutdown_callback(close_store)  # first, so a failed connect still closes the store
    # Spec §4.0: the store reads overlap the room connection (connect is idempotent; session.start's is a no-op).
    _, preloaded = await asyncio.gather(ctx.connect(), _preload_or_none(store, info.visitor_id, uuid.uuid4().hex))

    channels = ChannelTags()
    session = AgentSession(
        llm=build_llm("conversation", settings),
        stt=build_stt(settings),
        tts=build_tts(settings),
        vad=ctx.proc.userdata["vad"],
        # D7. Interruptions by VAD too: with no mode, dev/console mode builds the hosted adaptive detector.
        turn_handling={"turn_detection": "vad", "interruption": {"mode": "vad"}},
    )
    await session.start(
        agent=_agent_or_memoryless(load_pack(), preloaded),
        room=ctx.room,
        room_options=RoomOptions(
            participant_identity=f"visitor-{info.visitor_id}",
            text_input=TextInputOptions(
                text_input_cb=make_text_input_cb(channels.on_text, on_dropped=channels.on_dropped),
            ),
        ),
        record=recording_options(settings),
    )


if __name__ == "__main__":
    cli.run_app(server)

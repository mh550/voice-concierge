"""The worker entry point: `python -m concierge.worker start` (scripts/run-worker.sh wraps it).

Explicit dispatch as `concierge` (spec §6). Providers need keys, so they're built only inside the entrypoint, never
at import; importing this module needs no LIVEKIT_*,
ANTHROPIC_API_KEY or OPENROUTER_API_KEY.
"""

from __future__ import annotations

import logging

from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, JobRequest, cli
from livekit.agents.voice.agent_session import RecordingOptions
from livekit.agents.voice.room_io import RoomOptions, TextInputOptions
from livekit.plugins import silero

from concierge.agent import ConciergeAgent
from concierge.config import Settings, build_llm, build_stt, build_tts
from concierge.dispatch import DispatchError, parse_dispatch
from concierge.knowledge import load_pack
from concierge.text_input import ChannelTags, make_text_input_cb

logger = logging.getLogger("concierge.worker")


def recording_options(settings: Settings | None = None) -> RecordingOptions:
    """B11: no visitor audio at LiveKit unless CONCIERGE_RECORD_AUDIO=1; transcripts, traces and logs stay on
    (unset keys default to True in `_resolve_recording_options`), with redaction requested."""
    s = settings or Settings()
    return {"audio": s.record_audio, "redaction": True}


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()  # D7: VAD-only turn detection; the model ships in the wheel


async def on_request(req: JobRequest) -> None:
    await req.accept()  # C6-04 adds the kill switch (reject under CONCIERGE_ENABLED=0 or the off file)


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
        agent=ConciergeAgent(load_pack()),
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

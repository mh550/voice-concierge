"""One visitor session: preload, agent, `session.start`, greeting, and the journaled start and end (spec §4.3;
plan C3 "The preload sequence", "Session start and end").

Every store call runs in a thread (the store blocks up to 5 s), and none sits between the preload and the greeting:
`session_started` is written by a background task after the greeting is queued, and the page gets the visitor's
memory (`concierge.memory`, spec §6) after `session.start` and after every merge, and can call the two §6 RPCs. The
abuse limits (B7, plan C6 Part 5): the day's session count runs ahead of the preload, so a visitor over the cap is told
so and ended without their memory being loaded; every other session ends after `session_max_s`. At the end (plan C5
"The shutdown sequence"): the final extraction, then the visit summary, unless the visitor was erased.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from livekit.agents import AgentSession, JobContext, llm
from livekit.agents.voice import SpeechHandle
from livekit.agents.voice.room_io import RoomOptions, TextInputOptions

from concierge.agent import ConciergeAgent, agent_or_memoryless
from concierge.compactor import Compactor
from concierge.config import Settings, build_llm, build_stt, build_tts, recording_options
from concierge.contract import METRICS_TOPIC
from concierge.dispatch import DispatchInfo, parse_dispatch
from concierge.erasure_hooks import add_erase_hook
from concierge.greeting import greeting_instructions
from concierge.knowledge import load_pack
from concierge.limits import (
    DAILY_CAP_LINE,
    over_daily_cap,
    preload_unless_capped,
    say_and_end,
    start_session_timer,
    was_capped,
)
from concierge.memory_writer import MemoryWriter
from concierge.merge import MergeResult
from concierge.metrics import TurnMetricsCollector
from concierge.preload import Preloaded, preload, preload_or_none
from concierge.publish import MemoryPublisher, publish
from concierge.rpc import current_memory, serve_rpcs
from concierge.session_end import journal_row, write_summary
from concierge.store import Store
from concierge.tasks import track
from concierge.text_input import ChannelTags, make_text_input_cb

logger = logging.getLogger("concierge.session")

# D9: the preload runs while the room is already connected and RoomIO's lk.chat and pre-connect audio handlers
# aren't registered yet (session.start registers them), so it gets a short deadline. A normal one takes < 1 ms.
PRELOAD_TIMEOUT_S = 1.0
EXTRACTION_DEBOUNCE_S = 2.0  # spec §4.4: a run starts 2 s after the first user turn it covers
# The shutdown's own deadline (plan C5 "Timing"): the flush (15 s), the summary (5 s) and a busy wait (5 s) fit, and
# it leaves the worker's shutdown_process_timeout=30 room for the session close before the callbacks. A second
# summary attempt (another session stored one during the first) only runs in what is left of it.
SHUTDOWN_WORK_S = 25.0


@dataclass
class Started:
    """What start_session set going; `greeting` is the first reply's handle (not awaited by start_session)."""

    session: AgentSession
    preloaded: Preloaded | None
    session_id: str
    greeting: SpeechHandle | None  # None: over the daily cap, no greeting
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    writer: MemoryWriter | None = None  # None: no memory this session (no store, or the preload failed)
    compactor: Compactor | None = None
    publisher: MemoryPublisher | None = None
    collector: TurnMetricsCollector | None = None
    timer: asyncio.Task[None] | None = None  # the session_max_s limit; cancelled first at shutdown


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


async def start_session(ctx: JobContext, store: Store | None, settings: Settings) -> Started:
    """Preload (concurrent with ctx.connect()) → ConciergeAgent → session.start → the greeting, then
    session_started in the background. With memory, a MemoryWriter sees every conversation item; a Compactor keeps
    the in-call context short either way. The shutdown callback cancels the compaction, runs the final extraction
    and the visit summary (unless erased), journals session_ended and closes the store."""
    info = parse_dispatch(ctx.job.metadata)  # the entrypoint validated it; pure and cheap
    session_id = uuid.uuid4().hex
    began = time.monotonic()
    tasks: set[asyncio.Task[Any]] = set()
    preloaded: Preloaded | None = None
    writer: MemoryWriter | None = None
    compactor: Compactor | None = None
    publisher: MemoryPublisher | None = None
    collector: TurnMetricsCollector | None = None
    timer: asyncio.Task[None] | None = None

    async def on_shutdown(reason: str) -> None:  # a plain async def: add_shutdown_callback reads its __code__
        # One ordered callback: the job runs its shutdown callbacks concurrently, so a separate close could
        # close the store under the session_ended write.
        summarizer: list[llm.LLM] = []  # built only when a summary runs; closed in the finally

        def build_summarizer() -> llm.LLM:
            summarizer.append(build_llm("summarizer", settings))
            return summarizer[-1]

        if timer is not None:  # first: a sleeping 10-minute task would hold the shutdown up
            timer.cancel()
        if collector is not None:  # first: the room is disconnected before the callbacks run (plan C6)
            collector.stop_publishing()
        if publisher is not None:
            await publisher.aclose()
        try:
            async with asyncio.timeout(SHUTDOWN_WORK_S):
                await asyncio.gather(*tasks, return_exceptions=True)  # errors are logged by track's callback
                if compactor is not None:  # first: no compaction overlaps the final extraction or the summary
                    await compactor.aclose()
                if writer is not None:
                    await writer.flush()  # the final extraction; nothing when erased
                    # Checked after the flush too: forget_me can land during it. No visitor turn: nothing new.
                    if not writer.erased and preloaded is not None and any(t.role == "user" for t in writer.history):
                        await write_summary(writer, build_summarizer)
                if preloaded is not None and not (writer is not None and writer.erased):
                    ended = {"reason": reason, "duration_s": round(time.monotonic() - began, 1)}
                    # On the writer's thread: after a cancelled run's last store call (review M7).
                    await journal_row(store, preloaded.thread_id, session_id, "session_ended", ended, writer)
        except TimeoutError:
            logger.warning("the shutdown work missed its %.0f s deadline; the rest was skipped", SHUTDOWN_WORK_S)
        finally:
            for closing in (collector, compactor, writer, *summarizer):  # the collector waits ≤ 5 s for its writes
                if closing is None:
                    continue
                try:
                    await closing.aclose()  # the writer waits for its store thread: before store.close
                except Exception as exc:  # e.g. an LLM's close: the store still closes
                    logger.warning("closing %s failed (%s)", type(closing).__name__, type(exc).__name__)
            if store is not None:
                await asyncio.to_thread(store.close)

    ctx.add_shutdown_callback(on_shutdown)  # first, so a failed connect or session.start still closes the store
    # Spec §4.0: the store reads overlap the room connection (connect is idempotent; session.start's is a no-op).
    # The preload is a tracked task, so a failed connect or a missed deadline still leaves it for on_shutdown.
    # B7: the count comes first, and the preload waits for it, so a capped session never loads the memory.
    counting = preloading = None
    if store is not None:
        counting = track(tasks, over_daily_cap(store, info.visitor_id, settings.sessions_per_day), log=logger)
        loading = functools.partial(preload, store, info.visitor_id, session_id)
        preloading = track(tasks, preload_unless_capped(counting, loading), log=logger)
    _, preloaded = await asyncio.gather(ctx.connect(), preload_or_none(preloading, PRELOAD_TIMEOUT_S))
    # The count is done unless the preload missed its deadline (the preload waits for it). A late count is awaited
    # after session.start instead, so RoomIO's lk.chat and pre-connect audio handlers aren't held up (D9, review I3).
    late_count = counting if counting is not None and not counting.done() else None
    capped = late_count is None and await was_capped(counting)

    def stop_timer() -> None:  # "Forget me": the 10-minute line can't follow the goodbye
        if timer is not None:
            timer.cancel()

    session = build_session(ctx, settings)
    channels = ChannelTags()
    # What concierge.memory and get_memory carry now: on the writer's thread, in order with its writes.
    publisher = MemoryPublisher(ctx.room, lambda: current_memory(store, writer, info.visitor_id))
    rpcs = functools.partial(  # after connect: local_participant exists
        serve_rpcs, ctx.room, visitor_id=info.visitor_id, store=store, publisher=publisher, session=session,
        end=ctx.shutdown, tasks=tasks, preloading=preloading, stop_timer=stop_timer,
    )
    if capped:  # memoryless, no greeting; the RPCs still answer (a capped visitor can still press "Forget me")
        rpcs(writer=None)
        await session.start(agent=ConciergeAgent(load_pack()), **room_start_kwargs(ctx, info, settings, channels))
        track(tasks, say_and_end(session, DAILY_CAP_LINE, ctx.shutdown, "daily cap"), log=logger)
        return Started(session, None, session_id, None, tasks, publisher=publisher)

    def on_merged(result: MergeResult) -> None:
        if collector is not None:
            collector.note_extraction(result.extraction_ms)  # on the next turn's concierge.metrics
        publisher.schedule()  # a fresh concierge.memory after every merge

    if store is not None and preloaded is not None:  # no thread, no writer: nothing is ever scheduled
        extractor = functools.partial(build_llm, "extractor", settings)
        writer = MemoryWriter(
            store, preloaded.thread_id, session_id, extractor, EXTRACTION_DEBOUNCE_S, channels=channels,
            on_merged=on_merged,
        )
        session.on("conversation_item_added", writer.on_item_added)  # before start: the greeting is seen too
    agent = agent_or_memoryless(load_pack(), preloaded.block if preloaded else None, writer)
    # Compaction is about the context budget, not the store: it runs without memory too (then nothing is journaled).
    compactor = Compactor(
        agent, session, functools.partial(build_llm, "summarizer", settings),
        journal=functools.partial(journal_row, store, writer.thread_id, session_id, writer=writer) if writer else None,
        erased=(lambda: writer.erased) if writer else (lambda: False),
    )
    if writer is not None:
        add_erase_hook(writer, compactor.cancel)  # "Forget me" cancels the compaction too (spec §4.2)
    session.on("conversation_item_added", compactor.on_item_added)  # after the writer's
    session.on("agent_state_changed", compactor.on_state_changed)  # the apply point, never the turn hook
    # B9: anonymous per-turn numbers, with or without memory; the conversation LLM's calls bring the tokens.
    collector = TurnMetricsCollector(
        store, session_id, functools.partial(publish, ctx.room, METRICS_TOPIC),
        preload_ms=preloaded.ms if preloaded else None, compactions=lambda: compactor.applied,
    )
    session.on("conversation_item_added", collector.on_item_added)
    session.on("agent_state_changed", collector.on_state_changed)
    if isinstance(session.llm, llm.LLM):
        session.llm.on("metrics_collected", collector.on_llm_metrics)
    rpcs(writer=writer)
    await session.start(agent=agent, **room_start_kwargs(ctx, info, settings, channels))
    if writer is not None and writer.erased:  # "Forget me" during start: it says goodbye and ends (review A-M1)
        return Started(session, None, session_id, None, tasks, writer, compactor, publisher, collector)
    if late_count is not None and await was_capped(late_count):  # no memory was loaded: the preload waits for it
        if preloading is not None:
            preloading.cancel()  # a count that timed out may still come back under the cap: no preload then
        track(tasks, say_and_end(session, DAILY_CAP_LINE, ctx.shutdown, "daily cap"), log=logger)
        return Started(session, None, session_id, None, tasks, writer, compactor, publisher, collector)
    greeting = session.generate_reply(instructions=greeting_instructions(preloaded))
    publisher.schedule()  # after the greeting is queued: the read waits behind the writer's thread, not the reply
    timer = start_session_timer(session, settings.session_max_s, ctx.shutdown)  # B7: 10 minutes, then one line

    if store is not None and preloaded is not None:
        started = {"visits": preloaded.visits, "preload_ms": preloaded.ms, "returning": preloaded.block is not None}
        track(tasks, journal_row(store, preloaded.thread_id, session_id, "session_started", started), log=logger)
    return Started(session, preloaded, session_id, greeting, tasks, writer, compactor, publisher, collector, timer)

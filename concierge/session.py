"""One visitor session: preload, agent, `session.start`, greeting, and the journaled start and end (spec §4.3;
plan C3 "The preload sequence", "Session start and end").

Every store call runs in a thread (the store blocks up to 5 s), and none sits between the preload and the greeting:
`session_started` is written by a background task after the greeting is queued, and the page gets the visitor's
memory (`concierge.memory`, spec §6) after `session.start` and after every merge, and can call the two §6 RPCs. The
abuse limits (B7, plan C6 Part 5): the day's session count runs ahead of the preload, so a visitor over the cap is told
so and ended without their memory being loaded; every other session ends after `session_max_s`, or 20 s after the
visitor's page leaves (D16). Every end goes through `session_end.end_session`: the final extraction, the visit summary
(unless erased) and the last `concierge.memory`, while the room is still connected, then `ctx.shutdown`.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any

from livekit.agents import AgentSession, JobContext, llm
from livekit.agents.voice import SpeechHandle
from livekit.agents.voice.room_io import RoomOptions, TextInputOptions

from concierge.agent import ConciergeAgent, agent_or_memoryless
from concierge.compactor import Compactor
from concierge.config import Settings, build_llm, build_stt, build_tts, recording_options
from concierge.contract import METRICS_TOPIC, MemoryPayload, empty_memory_payload
from concierge.departure import DEPARTURE_GRACE_S, JOIN_GRACE_S, DepartureWatcher
from concierge.dispatch import DispatchInfo, parse_dispatch
from concierge.erasure_hooks import add_erase_hook
from concierge.events import EventRing
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
from concierge.memory_view import AgentView, current_memory
from concierge.memory_writer import MemoryWriter
from concierge.merge import MergeResult
from concierge.metrics import TurnMetricsCollector
from concierge.preload import Preloaded, preload, preload_or_none
from concierge.publish import MemoryPublisher, publish
from concierge.rpc import serve_rpcs
from concierge.session_end import Closing, begin_end, end_session, shut_down
from concierge.store import Store, now_ms
from concierge.summary_step import journal_row, session_started
from concierge.tasks import track
from concierge.text_input import ChannelTags, make_text_input_cb
from concierge.usher import Usher, allowlist_from_pack

logger = logging.getLogger("concierge.session")

# D9: the preload runs while the room is already connected and RoomIO's lk.chat and pre-connect audio handlers
# aren't registered yet (session.start registers them), so it gets a short deadline. A normal one takes < 1 ms.
PRELOAD_TIMEOUT_S = 1.0
EXTRACTION_DEBOUNCE_S = 2.0  # spec §4.4: a run starts 2 s after the first user turn it covers


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
    closing: Closing | None = None  # what every end runs (session_end.end_session)
    events: EventRing | None = None  # this session's memory events (V2-04); None without memory


def room_start_kwargs(ctx: JobContext, info: DispatchInfo, settings: Settings, channels: ChannelTags) -> dict[str, Any]:
    """The room half of session.start. A seam: tests drive a real AgentSession without a room (fake_job_context's
    room never connects, and RoomIO can't start on it)."""
    return {
        "room": ctx.room,
        "room_options": RoomOptions(
            participant_identity=f"visitor-{info.visitor_id}",
            close_on_disconnect=False,  # the DepartureWatcher ends the session, after its grace (plan V1 (d))
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
    the in-call context short either way. The visitor leaving, the 10-minute cap and the daily cap end through
    `end_session` (the closing work, then ctx.shutdown); the shutdown callback runs it if no end did, then closes
    everything, the store last."""
    info = parse_dispatch(ctx.job.metadata)  # the entrypoint validated it; pure and cheap
    started_ms = now_ms()  # the visit's episode starts here
    closing = Closing(
        end=lambda reason: ctx.shutdown(reason), store=store, session_id=uuid.uuid4().hex, visitor_id=info.visitor_id,
        began=time.monotonic(), tasks=set(), make_summarizer=lambda: build_llm("summarizer", settings),
    )
    session_id, tasks = closing.session_id, closing.tasks
    writer: MemoryWriter | None = None
    compactor: Compactor | None = None
    collector: TurnMetricsCollector | None = None
    ring: EventRing | None = None  # with the writer: this session's memory events (V2-04)
    view: AgentView | None = None  # once the agent exists: what the body says about it (V2-05)

    async def on_shutdown(reason: str) -> None:  # a plain async def: add_shutdown_callback reads its __code__
        await shut_down(closing, reason)

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
    closing.preloaded = preloaded
    # V1: the visitor's page leaving ends the session once the grace (D16) runs out; the capped session too.
    def left() -> Awaitable[None]:  # visitor_left carries the grace that ran out (the join grace or the departure's)
        return end_session(closing, "visitor left", left_grace_s=watcher.waited_s)

    watcher = closing.watcher = DepartureWatcher(
        ctx.room, f"visitor-{info.visitor_id}", left, DEPARTURE_GRACE_S, JOIN_GRACE_S
    )
    watcher.start()
    # The count is done unless the preload missed its deadline (the preload waits for it). A late count is awaited
    # after session.start instead, so RoomIO's lk.chat and pre-connect audio handlers aren't held up (D9, review I3).
    late_count = counting if counting is not None and not counting.done() else None
    capped = late_count is None and await was_capped(counting)

    end = functools.partial(begin_end, closing)  # every end but a departure: the closing work, then ctx.shutdown
    session = closing.session = build_session(ctx, settings)
    channels = ChannelTags()
    async def memory() -> MemoryPayload:  # concierge.memory and get_memory: one build path (V2-05)
        if publisher.closed:  # "Forget me" sent the empty body last (or the room is gone): get_memory says the same
            return empty_memory_payload()
        return await current_memory(store, writer, info.visitor_id, events=ring, agent=view)

    publisher = closing.publisher = MemoryPublisher(ctx.room, memory)
    rpcs = functools.partial(  # after connect: local_participant exists
        serve_rpcs, ctx.room, visitor_id=info.visitor_id, store=store, publisher=publisher, session=session,
        end=end, tasks=tasks, preloading=preloading, stop_timer=closing.stop,  # "Forget me": no cap line, one end
        memory=memory,
    )
    if capped:  # memoryless, no greeting; the RPCs still answer (a capped visitor can still press "Forget me")
        rpcs(writer=None)
        view = AgentView(ConciergeAgent(load_pack()))
        await session.start(agent=view.agent, **room_start_kwargs(ctx, info, settings, channels))
        track(tasks, say_and_end(session, DAILY_CAP_LINE, end, "daily cap"), log=logger)
        return Started(session, None, session_id, None, tasks, publisher=publisher, closing=closing)

    def on_merged(result: MergeResult) -> None:  # the writer's background run, never a turn handler
        if collector is not None:
            collector.note_extraction(result.extraction_ms)  # on the next turn's concierge.metrics
        if ring is not None:
            try:
                ring.note_merge(result)  # before the send, so it carries the lines
            except Exception as exc:  # a line never costs the send
                logger.warning("the merge's events weren't noted (%s)", type(exc).__name__)
        publisher.schedule()  # a fresh concierge.memory after every merge

    if store is not None and preloaded is not None:  # no thread, no writer: nothing is ever scheduled
        extractor = functools.partial(build_llm, "extractor", settings)
        writer = closing.writer = MemoryWriter(
            store, preloaded.thread_id, session_id, extractor, EXTRACTION_DEBOUNCE_S, channels=channels,
            on_merged=on_merged,
        )
        session.on("conversation_item_added", writer.on_item_added)  # before start: the greeting is seen too
        ring = EventRing()
        add_erase_hook(writer, ring.clear)  # "Forget me" empties it with the rest of the pending work
    journal = functools.partial(journal_row, store, writer.thread_id, session_id, writer=writer) if writer else None
    pack = load_pack()
    usher = Usher(ctx.room, allowlist_from_pack(pack), publish, journal, time.monotonic, tasks=tasks)  # V6
    agent = agent_or_memoryless(
        pack, preloaded.block if preloaded else None, writer, events=ring, on_changed=publisher.schedule,
        usher=usher,
    )
    # Compaction is about the context budget, not the store: it runs without memory too (then nothing is journaled).
    compactor = closing.compactor = Compactor(
        agent, session, functools.partial(build_llm, "summarizer", settings), journal=journal,
        erased=(lambda: writer.erased) if writer else (lambda: False), on_compacted=publisher.schedule,
    )
    if writer is not None:
        add_erase_hook(writer, compactor.cancel)  # "Forget me" cancels the compaction too (spec §4.2)
    session.on("conversation_item_added", compactor.on_item_added)  # after the writer's
    session.on("agent_state_changed", compactor.on_state_changed)  # the apply point, never the turn hook
    # B9: anonymous per-turn numbers, with or without memory; the conversation LLM's calls bring the tokens.
    collector = closing.collector = TurnMetricsCollector(
        store, session_id, functools.partial(publish, ctx.room, METRICS_TOPIC),
        preload_ms=preloaded.ms if preloaded else None, compactions=lambda: compactor.applied,
    )
    session.on("conversation_item_added", collector.on_item_added)
    session.on("agent_state_changed", collector.on_state_changed)
    if isinstance(session.llm, llm.LLM):
        session.llm.on("metrics_collected", collector.on_llm_metrics)
    view = AgentView(agent, compactor, collector)
    rpcs(writer=writer)

    def started(loaded: Preloaded | None = None, greeting: SpeechHandle | None = None) -> Started:
        """Without a greeting (the cap, or an end during the start) the preload isn't reported either."""
        return Started(session, loaded, session_id, greeting, tasks, writer, compactor, publisher, collector,
                       closing.timer, closing, ring)

    await session.start(agent=agent, **room_start_kwargs(ctx, info, settings, channels))
    # An end that began during the start ("Forget me" says goodbye and ends, review A-M1; the visitor gone, V1-03) or
    # during the late count runs alone: no cap line, no greeting, no timer, no session_started after session_ended.
    if not closing.stopped and late_count is not None and await was_capped(late_count):  # the preload waits for it
        if preloading is not None:
            preloading.cancel()  # a count that timed out may still come back under the cap: no preload then
        if not closing.stopped:
            track(tasks, say_and_end(session, DAILY_CAP_LINE, end, "daily cap"), log=logger)
        return started()
    if closing.stopped:
        return started()
    greeting = session.generate_reply(instructions=greeting_instructions(preloaded))
    if writer is not None and preloaded is not None:  # created first: its begin_visit is queued ahead of the start read
        row = {"visits": preloaded.visits, "preload_ms": preloaded.ms, "returning": preloaded.block is not None}
        track(tasks, session_started(writer, preloaded.visits, started_ms, row), log=logger)
    publisher.schedule()  # after the greeting is queued: the read waits behind the writer's thread, not the reply
    closing.timer = start_session_timer(session, settings.session_max_s, end)  # B7: 10 minutes, one line
    return started(preloaded, greeting)

"""In-call compaction, the session half (spec §4.8; plan C5 "The Compactor"): one background task at a time builds
a compacted context from a snapshot; it is applied only when the agent goes back to `listening`, never in
`on_user_turn_completed` or a conversation_item_added handler (a test reads the source).

`on_item_added` and `on_state_changed` are plain defs: they read the context and at most start a task. The task never
touches the agent; `_apply` rebases the ready context onto the live one and calls `Agent.update_chat_ctx` with no
await before it, so no item the session appends can fall in between. `session.history` and the journal keep every
turn: only the agent's in-call context gets shorter. Erasure wins: `cancel` stops the work and disables the
Compactor, so the visitor's words never reach the summarizer again after "Forget me".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from livekit.agents import Agent, AgentSession, llm
from livekit.agents.voice.events import AgentStateChangedEvent, ConversationItemAddedEvent

from concierge.compaction import (
    KEEP_TURNS,
    compact_or_fallback,
    estimate_ctx_tokens,
    fallback_truncate,
    is_turn,
    needs_compaction,
    rebase,
)
from concierge.models import Journal, JournalType
from concierge.tasks import track

logger = logging.getLogger("concierge.compactor")


@dataclass(frozen=True)
class Compacted:
    """A compacted context waiting for the next `listening`, with what the rebase needs."""

    ctx: llm.ChatContext
    snapshot_ids: frozenset[str]
    folded_ids: frozenset[str]
    fallback: bool
    ms: int


class Compactor:
    def __init__(
        self,
        agent: Agent,
        session: AgentSession,
        llm_factory: Callable[[], llm.LLM],
        *,
        journal: Journal | None = None,
        erased: Callable[[], bool] = lambda: False,
        on_compacted: Callable[[], None] | None = None,
    ) -> None:
        self.ready: Compacted | None = None
        self.applied = 0  # how many compactions were applied (C6's metrics read "compacted" from it)
        self.disabled = False
        self._agent = agent
        self._session = session
        self._llm_factory = llm_factory
        self._llm: llm.LLM | None = None
        self._journal = journal
        self._erased = erased
        self._on_compacted = on_compacted  # after each apply: the session's publisher.schedule (V2-05)
        self._task: asyncio.Task[None] | None = None
        self._applying: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()  # its own: the shutdown's gather never waits on a compaction
        # After an attempt that folded nothing (a failing provider over 7-12 turns, or 6 long turns), the next one
        # waits for this many turns in the context, so a stuck trigger doesn't call the summarizer on every turn.
        self._idle_until_turns = 0

    @property
    def stopped(self) -> bool:
        return self.disabled or self._erased()

    # --- the handlers: plain defs, no await ----------------------------------------------------------------------

    def on_item_added(self, ev: ConversationItemAddedEvent) -> None:
        """The trigger: a new turn past the threshold starts one compaction, unless one is running or ready."""
        try:
            if is_turn(ev.item):
                self._maybe_start()
        except Exception as exc:  # compaction never breaks a turn
            logger.warning("could not check the context for compaction (%s)", type(exc).__name__)

    def on_state_changed(self, ev: AgentStateChangedEvent) -> None:
        """The apply point: back to `listening` with a compacted context ready."""
        if ev.new_state == "listening" and self.ready is not None and self._applying is None and not self.stopped:
            self._applying = track(self._tasks, self._apply(), log=logger)

    def _maybe_start(self) -> None:
        if self.stopped or self._task is not None or self.ready is not None:
            return
        current = self._agent.chat_ctx
        if sum(map(is_turn, current.items)) >= self._idle_until_turns and needs_compaction(current):
            self._task = track(self._tasks, self._compact(), log=logger)

    # --- background ----------------------------------------------------------------------------------------------

    async def _compact(self) -> None:
        try:
            # The snapshot is taken when the task first runs: items added in the same loop iteration are in it.
            snapshot = llm.ChatContext(list(self._agent.chat_ctx.items))
            began = time.perf_counter()
            try:
                if self._llm is None:
                    self._llm = self._llm_factory()
                ctx, error = await compact_or_fallback(self._llm, snapshot)
            except Exception as exc:  # the provider can't be built (no key)
                ctx, error = fallback_truncate(snapshot), type(exc).__name__
            if self.stopped:
                return
            if error is not None:
                logger.warning("compaction fell back to truncation (%s)", error)
                await self._write("error", {"stage": "compaction", "type": error})
            snapshot_ids = frozenset(it.id for it in snapshot.items)
            folded = snapshot_ids - {it.id for it in ctx.items}
            if not folded:  # a fallback with nothing to drop is not worth an apply
                self._idle_until_turns = sum(map(is_turn, snapshot.items)) + KEEP_TURNS
            elif not self.stopped:
                ms = round((time.perf_counter() - began) * 1000)
                self.ready = Compacted(ctx, snapshot_ids, frozenset(folded), error is not None, ms)
        finally:
            self._task = None

    async def _apply(self) -> None:
        ready = self.ready
        try:
            # Re-checked here: the state may have moved on, and a preemptive reply may be running on the old context.
            if ready is None or self.stopped:
                return
            if self._session.agent_state != "listening" or self._session.user_state == "speaking":
                return  # left ready for the next listening
            before = self._agent.chat_ctx
            new = rebase(ready.ctx, ready.snapshot_ids, ready.folded_ids, before)
            if new is None:  # something else rewrote the context
                self.ready = None
                return
            counts = {"items_before": len(before.items), "tokens_before": estimate_ctx_tokens(before)}
            await self._agent.update_chat_ctx(new)  # no await before it: the rebase is current
            self.ready = None
            self.applied += 1
            self._idle_until_turns = 0
            after = self._agent.chat_ctx
            counts |= {"items_after": len(after.items), "tokens_after": estimate_ctx_tokens(after)}
        finally:
            self._applying = None
        self._notify()
        await self._write("compacted", {**counts, "fallback": ready.fallback, "ms": ready.ms})
        self._maybe_start()  # turns added while compacting may need another one

    def _notify(self) -> None:
        if self._on_compacted is not None:
            try:
                self._on_compacted()
            except Exception as exc:  # a failed send never costs the compaction
                logger.warning("the compaction wasn't published (%s)", type(exc).__name__)

    async def _write(self, kind: JournalType, payload: dict[str, Any]) -> None:
        if self._journal is not None and not self.stopped:
            await self._journal(kind, payload)

    # --- erasure and shutdown ------------------------------------------------------------------------------------

    def cancel(self) -> None:
        """Erasure ("Forget me"): cancel the running work, drop what is ready, start nothing again."""
        self.disabled = True
        self.ready = None
        for task in list(self._tasks):
            task.cancel()

    async def aclose(self) -> None:
        """Shutdown: cancel, wait for the tasks, close the summarizer LLM. Before the final extraction."""
        self.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._llm is not None:
            closing, self._llm = self._llm, None  # idempotent: the shutdown's finally calls it again
            await closing.aclose()

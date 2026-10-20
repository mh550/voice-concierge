"""The background memory writer (spec §4.4 "Hot path vs background writes"; plan C4 "The scheduler").

`conversation_item_added` → `on_item_added` (sync) → for a user turn, `schedule()` → a debounce timer → one run per
thread at a time: journal the new turns, read the valid facts, `extract`, `merge` (its batch carries
`extraction_ran`), then `on_merged`. Nothing on the turn path awaits any of it: the handler builds a Turn and at
most starts a task. Store calls run on the writer's own one-thread executor, so its writes stay in order and
`aclose` can wait for the one in flight before the store closes. Erasure wins: `cancel_all` sets `erased` first,
so a timer or run that wakes later does nothing, and the store's fence fails a write after `forget_me`.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from livekit.agents import llm
from livekit.agents.voice.events import ConversationItemAddedEvent

from concierge.extractor import WINDOW_MAX_TURNS, extract, extraction_window
from concierge.forget_match import was_forgotten
from concierge.merge import MergeResult, merge
from concierge.models import Channel, SlotName
from concierge.store import Store, StoreError, ThreadMissing
from concierge.tasks import track
from concierge.text_input import ChannelTags
from concierge.turns import Turn, journal_note, turn_from_message

logger = logging.getLogger("concierge.memory_writer")

# The final extraction's share of the shutdown (plan C5 "Timing"): with the 5 s summary and a 5 s busy wait it fits
# session.SHUTDOWN_WORK_S (25), inside the worker's shutdown_process_timeout=30.
FLUSH_TIMEOUT_S = 15.0


class MemoryWriter:
    def __init__(
        self,
        store: Store,
        thread_id: str,
        session_id: str,
        llm_factory: Callable[[], llm.LLM],
        debounce_s: float = 2.0,
        *,
        channels: ChannelTags | None = None,
        on_merged: Callable[[MergeResult], None] | None = None,
    ) -> None:
        self.store = store
        self.thread_id = thread_id
        self.session_id = session_id
        self.erased = False
        self.history: list[Turn] = []  # this session's turns, in order
        self.last_user_turn: Turn | None = None  # what remember/forget tag their write with
        # (slot, key, len(history) when asked) for each value the forget tool deleted this session
        self.forgotten: list[tuple[SlotName, str, int]] = []
        self.forget_requests: list[tuple[str, int]] = []  # (about, len(history) when asked)
        self._closed = False
        self._llm_factory = llm_factory
        self._llm: llm.LLM | None = None
        self._debounce_s = debounce_s
        self._channels = channels
        self._on_merged = on_merged
        self._journaled = 0  # history[:_journaled] is in the journal
        self._extracted = 0  # history[:_extracted] went through a successful run
        self._timer: asyncio.Task[None] | None = None
        self._run: asyncio.Task[None] | None = None
        self._again = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="concierge-memory")

    # --- the turn path: plain defs, no await, no store or LLM call --------------------------------------------

    def on_item_added(self, ev: ConversationItemAddedEvent) -> None:
        """The session's conversation_item_added handler (both doors: spec §4.10)."""
        try:
            self.note_item(ev.item)
        except Exception as exc:  # memory never breaks a turn; only the type: the text is the visitor's
            logger.warning("could not note a conversation item (%s)", type(exc).__name__)

    def note_item(self, item: llm.ChatItem) -> None:
        if self.erased or not isinstance(item, llm.ChatMessage) or item.role not in ("user", "assistant"):
            return
        channel: Channel = "voice"
        if item.role == "user" and self._channels is not None:
            channel = self._channels.channel_of(item.text_content or "")  # consumes the tag, on the unstripped text
        turn = turn_from_message(item, channel)
        if turn is None:
            return
        self.history.append(turn)
        if turn.role == "user":
            self.last_user_turn = turn
            self.schedule()

    def schedule(self) -> None:
        """Start the debounce timer, unless one is pending (it will see the new turns) or a run is in flight
        (then exactly one follow-up run is queued)."""
        if self.erased or self._closed:
            return
        if self._run is not None:
            self._again = True
        elif self._timer is None:
            self._timer = track(self._tasks, self._debounced(), log=logger)

    # --- background -----------------------------------------------------------------------------------------

    async def call[T](self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:  # noqa: ANN401
        """`fn(*args, **kwargs)` on the writer's store thread (the tools use it too, in order with the runs)."""
        if self._closed:
            raise StoreError("the memory writer is closed")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))

    async def _debounced(self) -> None:
        await asyncio.sleep(self._debounce_s)
        self._timer = None
        if self.erased:
            return
        self._run = asyncio.current_task()
        try:
            await self._run_once()
        finally:
            self._run = None  # first, so the schedule() below starts a timer instead of queueing again
            if self._again:
                self._again = False
                self.schedule()  # nothing when erased or closed

    async def _run_once(self) -> None:
        end = len(self.history)
        new = self.history[self._journaled:end]
        window = extraction_window(self.history[:end], self._extracted)
        try:
            if new:
                await self.call(self.store.apply_fact_ops, self.thread_id, [journal_note(t) for t in new],
                                session_id=self.session_id)
                self._journaled = end
            if not any(t.role == "user" for t in self.history[self._extracted:end]):
                self._extracted = end  # agent turns only: journaled, nothing to extract
                return
            result = await self._extract_and_merge(window, end)
        except ThreadMissing:
            self.erased = True  # forget_me ran: stop quietly
            return
        except Exception as exc:  # an LLM error, a refusal, a timeout, a store error: retried with the next run
            logger.warning("extraction failed (%s)", type(exc).__name__)
            await self._journal_error(type(exc).__name__)
            return
        if self._on_merged is not None:
            try:
                self._on_merged(result)
            except Exception as exc:
                logger.warning("the on_merged callback failed (%s)", type(exc).__name__)

    async def _extract_and_merge(self, window: list[Turn], end: int) -> MergeResult:
        if self._llm is None:
            self._llm = self._llm_factory()
        facts = await self.call(self.store.valid_facts, self.thread_id)
        extraction = await extract(self._llm, window, facts)
        positions = {t.turn_id: i for i, t in enumerate(self.history)}
        ops = [op for op in extraction.ops
               if not was_forgotten(op, positions, self.forgotten, self.forget_requests)]
        meta = {
            "ms": extraction.ms,
            "prompt_tokens": extraction.prompt_tokens,
            "dropped": len(extraction.dropped),
            "tool_called": extraction.tool_called,
            "window_dropped": max(0, end - self._extracted - WINDOW_MAX_TURNS),
            "forgotten": len(extraction.ops) - len(ops),
        }
        known = {t.turn_id for t in window if t.role == "user"}
        result = await self.call(merge, self.store, self.thread_id, ops, known, self.session_id, turns=window,
                                 extraction=meta)
        self._extracted = end
        return result

    def note_forget(self, about: str) -> int:
        """A forget request (the tool calls it before deleting): extracted values it covers, from turns before it,
        are never added, even when nothing was stored yet."""
        self.forget_requests.append((about, len(self.history)))
        return len(self.history)

    async def _journal_error(self, kind: str) -> None:
        try:
            await self.call(self.store.journal, self.thread_id, self.session_id, "error",
                            {"stage": "extraction", "type": kind})
        except Exception as exc:  # the store is failing too, or the visitor was erased
            logger.warning("could not journal the extraction error (%s)", type(exc).__name__)

    async def flush(self, timeout_s: float = FLUSH_TIMEOUT_S) -> None:
        """The shutdown callback's final extraction: skip the pending timer, wait for the run in flight, then run
        once more over what is left. Bounded by `timeout_s` (on the deadline the run is cancelled); nothing when
        erased."""
        if self.erased:
            return
        try:
            await asyncio.wait_for(self._drain(), timeout_s)
        except TimeoutError:
            logger.warning("the final extraction missed its %.0f s deadline", timeout_s)
            await self._cancel_pending()  # else its merge could land after the summary's write

    async def _cancel_pending(self) -> None:
        """Cancel the timer and the run in flight (no follow-up) and wait for them. A store call already on the
        thread still finishes there, ahead of any later call."""
        self._again = False
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._timer = None
        self._run = None

    async def _drain(self) -> None:
        while not self.erased and not self._closed:
            if self._timer is not None:
                self._timer.cancel()
                await asyncio.wait({self._timer})  # not `await`: that would swallow a cancel aimed at flush itself
                self._timer = None
            if self._run is not None:
                await asyncio.wait({self._run})
                continue
            self._again = False
            if len(self.history) <= min(self._journaled, self._extracted):
                return
            before = self._extracted
            # A tracked task, so cancel_all reaches it; as `_run`, a turn noted meanwhile waits for the next loop.
            self._run = track(self._tasks, self._run_once(), log=logger)
            try:
                await asyncio.wait({self._run})
            finally:
                self._run = None
            if self._extracted == before:
                return  # it failed (its turns may be journaled): no retry loop at shutdown

    def cancel_all(self) -> None:
        """Erasure: nothing pending runs and nothing new is scheduled. `erased` is set first."""
        self.erased = True
        for task in list(self._tasks):
            task.cancel()

    async def aclose(self) -> None:
        """Cancel what is left, wait for the store thread's last call, close the extractor LLM. Before store.close."""
        self._closed = True  # first: a cancelled run's finally can't start a new timer
        while self._tasks:
            await self._cancel_pending()
        await asyncio.to_thread(self._executor.shutdown, True)
        if self._llm is not None:
            await self._llm.aclose()


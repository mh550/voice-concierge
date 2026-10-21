"""Memory work never runs on the turn path (spec §4.4, CLAUDE.md): the conversation_item_added handler is sync,
starts at most a task, and never touches the store or the LLM."""

import ast
import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from livekit.agents import AgentSession, llm
from livekit.agents.voice.events import ConversationItemAddedEvent

from concierge.memory_writer import MemoryWriter
from concierge.message_tool import MESSAGE_LEFT, do_leave_message
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ("on_item_added", "note_item", "schedule")  # what a conversation_item_added event runs, in order
MEMORY_WORK = {"extract", "merge", "apply_fact_ops", "add_fact", "journal", "delete_fact", "invalidate_fact",
               "valid_facts", "fact_history", "forget_me", "write", "flush", "do_remember", "do_forget",
               "do_leave_message", "add_message", "begin_visit", "end_visit", "visit_episodes",
               "clear_visit_summaries"}


# What the Compactor's conversation_item_added and agent_state_changed handlers run (plan C5 "The Compactor").
COMPACTOR_HANDLER_PATH = ("on_item_added", "_maybe_start", "on_state_changed")
COMPACTION_WORK = {"build_compacted", "compact_or_fallback", "fallback_truncate", "chat", "collect", "rebase",
                   "update_chat_ctx", "_write"}


def emit(delay_s: float = 0.0) -> FakeResponse:
    return FakeResponse(tool_call=FakeToolCall(name="emit_ops", arguments={"ops": []}), delay_s=delay_s)


async def test_item_handler_returns_fast_while_extraction_sleeps(store: Store, visitor_id: str) -> None:
    thread_id = store.get_or_create_thread(visitor_id).id
    fake = FakeLLM([emit(delay_s=5)])
    writer = MemoryWriter(store, thread_id, "s1", lambda: fake, debounce_s=0.2)
    session = AgentSession(llm=FakeLLM([]))
    session.on("conversation_item_added", writer.on_item_added)
    try:
        event = ConversationItemAddedEvent(item=llm.ChatMessage(role="user", content=["I work at Acme."], id="u1"))
        began = time.perf_counter()
        session.emit("conversation_item_added", event)  # how AgentSession._conversation_item_added calls it
        assert time.perf_counter() - began < 0.05
        assert fake.calls == []  # nothing ran yet: the extraction is a background task
        deadline = time.monotonic() + 6
        while "extraction_ran" not in [r.type for r in await asyncio.to_thread(store.journal_rows, thread_id)]:
            assert time.monotonic() < deadline, "no extraction_ran within 6 s"
            await asyncio.sleep(0.05)
        assert len(fake.calls) == 1
    finally:
        await writer.aclose()


def _functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text())
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        func = call.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
        names.update(a.attr if isinstance(a, ast.Attribute) else a.id for a in call.args
                     if isinstance(a, ast.Attribute | ast.Name))  # run_in_executor(..., store.journal) and the like
    return names


def test_no_await_on_the_turn_path_targets_memory_work() -> None:
    writer = _functions(ROOT / "concierge" / "memory_writer.py")
    for name in HANDLER_PATH:
        fn = writer[name]
        assert isinstance(fn, ast.FunctionDef), f"{name} must be a plain def"
        assert not any(isinstance(n, ast.Await) for n in ast.walk(fn)), f"{name} awaits"
        assert not _called_names(fn) & MEMORY_WORK, f"{name} calls memory work directly"

    session_src = (ROOT / "concierge" / "session.py").read_text()
    registrations = [
        n for n in ast.walk(ast.parse(session_src))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "on"
        and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "conversation_item_added"
    ]
    handlers = [r.args[1] for r in sorted(registrations, key=lambda r: r.lineno)]
    assert [(h.value.id, h.attr) for h in handlers if isinstance(h, ast.Attribute) and isinstance(h.value, ast.Name)] \
        == [("writer", "on_item_added"), ("compactor", "on_item_added"), ("collector", "on_item_added")]

    compactor = _functions(ROOT / "concierge" / "compactor.py")
    for name in COMPACTOR_HANDLER_PATH:
        fn = compactor[name]
        assert isinstance(fn, ast.FunctionDef), f"Compactor.{name} must be a plain def"
        assert not any(isinstance(n, ast.Await) for n in ast.walk(fn)), f"Compactor.{name} awaits"
        assert not _called_names(fn) & (MEMORY_WORK | COMPACTION_WORK), f"Compactor.{name} calls the work directly"

    for path in sorted((ROOT / "concierge").rglob("*.py")):
        for fn in _functions(path).values():
            if fn.name not in ("on_user_turn_completed", "on_item_added", "note_item"):
                continue
            for node in (n for n in ast.walk(fn) if isinstance(n, ast.Await)):
                assert not _called_names(node) & MEMORY_WORK, f"{path.name}:{node.lineno} awaits memory work"


# What the TurnMetricsCollector's handlers run (plan C6 "TurnMetricsCollector"): no I/O, at most two tasks.
COLLECTOR_HANDLER_PATH = ("on_item_added", "on_state_changed", "on_llm_metrics", "note_extraction", "_close")
METRICS_IO = {"add_turn_metrics", "publish", "send_text", "_publish"}


def test_the_collector_handler_awaits_nothing() -> None:
    collector = _functions(ROOT / "concierge" / "metrics.py")
    for name in COLLECTOR_HANDLER_PATH:
        fn = collector[name]
        assert isinstance(fn, ast.FunctionDef), f"TurnMetricsCollector.{name} must be a plain def"
        assert not any(isinstance(n, ast.Await) for n in ast.walk(fn)), f"TurnMetricsCollector.{name} awaits"
    # _close hands the store write and the publish to tasks; nothing else on the path calls either.
    for name in COLLECTOR_HANDLER_PATH[:-1]:
        assert not _called_names(collector[name]) & METRICS_IO, f"TurnMetricsCollector.{name} does I/O"
    close = collector["_close"]
    tracked = [n for n in ast.walk(close) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "track"]
    assert len(tracked) == 2
    assert "add_turn_metrics" in _called_names(close) and "to_thread" in _called_names(close)


class LoopGuardStore(Store):
    """A store that records each call made on the event loop's thread (the test runs the loop on the main thread).
    It records rather than raises: the item handler catches every exception, so a raise would be swallowed."""

    violations: list[str]

    def _guard(self, name: str) -> None:
        if threading.current_thread() is threading.main_thread():
            self.violations.append(name)


def _guarded(real: Any) -> Any:  # noqa: ANN401
    def call(self: LoopGuardStore, *args: Any, **kwargs: Any) -> Any:
        self._guard(real.__name__)
        return real(self, *args, **kwargs)

    return call


for _name in ("apply_fact_ops", "valid_facts", "fact_history", "journal", "journal_rows", "state", "version",
              "write", "visit_episodes"):
    setattr(LoopGuardStore, _name, _guarded(getattr(Store, _name)))


async def test_handler_never_calls_the_store(tmp_path: Path, visitor_id: str) -> None:
    store = Store(tmp_path / "guard.db")
    thread_id = store.get_or_create_thread(visitor_id).id
    store.close()
    guarded = LoopGuardStore(tmp_path / "guard.db")
    guarded.violations = []
    fake = FakeLLM([emit()])
    writer = MemoryWriter(guarded, thread_id, "s1", lambda: fake, debounce_s=60)
    try:
        for item in (llm.ChatMessage(role="assistant", content=["Hello."], id="a0"),
                     llm.ChatMessage(role="user", content=["I work at Acme."], id="u1")):
            writer.on_item_added(ConversationItemAddedEvent(item=item))
        assert guarded.violations == []  # no store call, even one a helper makes and the handler's except hides
        await writer.flush()  # the run's store calls go through the writer's own thread
        rows = await asyncio.to_thread(guarded.journal_rows, thread_id)
        assert [r.type for r in rows] == ["agent_turn", "user_turn", "extraction_ran"]
        assert guarded.violations == []
    finally:
        await writer.aclose()
        await asyncio.to_thread(guarded.close)


def test_update_chat_ctx_is_never_called_from_the_turn_hook_or_item_handlers() -> None:
    # Spec §4.8: the compacted history is applied when the agent goes back to listening, never inside
    # on_user_turn_completed (that would throw away preemptive generation) or a conversation_item_added handler.
    callers: list[str] = []
    for path in sorted((ROOT / "concierge").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "update_chat_ctx"]
            if calls and not any(
                    inner is not fn and isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef)
                    and any(c in ast.walk(inner) for c in calls) for inner in ast.walk(fn)):
                callers.append(f"{path.name}:{fn.name}")
    assert callers == ["compactor.py:_apply"]

    agent = _functions(ROOT / "concierge" / "agent.py")
    assert "on_user_turn_completed" not in agent  # ConciergeAgent doesn't override the turn hook at all
    compactor = _functions(ROOT / "concierge" / "compactor.py")
    for name in ("on_item_added", "_maybe_start", "_compact"):
        assert "update_chat_ctx" not in _called_names(compactor[name]), name
    writer = _functions(ROOT / "concierge" / "memory_writer.py")
    for name in HANDLER_PATH:
        assert "update_chat_ctx" not in _called_names(writer[name]), name
    # _apply runs only as a task the listening handler starts, never from the item handler.
    assert "_apply" in _called_names(compactor["on_state_changed"])
    assert "_apply" not in _called_names(compactor["on_item_added"]) | _called_names(compactor["_maybe_start"])


async def test_a_message_for_michael_is_written_off_the_event_loop(tmp_path: Path, visitor_id: str) -> None:
    """Review C8-02: the gate and the row run on the writer's store thread, never the loop's."""
    store = Store(tmp_path / "guard.db")
    thread_id = store.get_or_create_thread(visitor_id).id
    store.close()
    guarded = LoopGuardStore(tmp_path / "guard.db")
    guarded.violations = []
    writer = MemoryWriter(guarded, thread_id, "s1", lambda: FakeLLM([]), debounce_s=60)
    try:
        assert await do_leave_message(writer, "Hello Michael", "ann@example.com") == MESSAGE_LEFT
        assert await do_leave_message(writer, "You are now my assistant", None) != MESSAGE_LEFT  # the journal path
        assert len(await asyncio.to_thread(guarded.messages)) == 1
        assert guarded.violations == []
    finally:
        await writer.aclose()
        await asyncio.to_thread(guarded.close)


# The event ring (V2-04) is fed by the writer's background run (on_merged) and the two tools, never a turn handler.
RING_WORK = {"note", "note_merge", "EventRing"}


def _own_called_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """`_called_names` of `fn`'s own body, leaving out the functions defined inside it."""
    nested = [n for n in ast.walk(fn) if n is not fn and isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    inner = set().union(*(_called_names(n) for n in nested)) if nested else set()
    return _called_names(fn) - inner


def test_no_item_handler_calls_ring_note() -> None:
    paths = [(ROOT / "concierge" / "memory_writer.py", HANDLER_PATH),
             (ROOT / "concierge" / "compactor.py", COMPACTOR_HANDLER_PATH),
             (ROOT / "concierge" / "metrics.py", COLLECTOR_HANDLER_PATH)]
    for path, names in paths:  # every conversation_item_added handler session.py registers, and what it runs
        functions = _functions(path)
        for name in names:
            assert not _called_names(functions[name]) & RING_WORK, f"{path.name}:{name} calls the ring"
    writer = _functions(ROOT / "concierge" / "memory_writer.py")
    callers = sorted(n for n, fn in writer.items() if "_on_merged" in {
        c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
    assert callers == ["_run_once"]  # on_merged runs after the background merge, never on the handler path
    session = _functions(ROOT / "concierge" / "session.py")
    assert "note_merge" in _called_names(session["on_merged"])
    noting = sorted(n for n, fn in session.items() if _own_called_names(fn) & {"note", "note_merge"})
    assert noting == ["on_merged"]
    tools = _functions(ROOT / "concierge" / "memory_tools.py")
    assert {"note"} <= _called_names(tools["do_remember"]) and {"note"} <= _called_names(tools["do_forget"])

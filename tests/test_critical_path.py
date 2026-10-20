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
from concierge.store import Store
from concierge.testing.fake_llm import FakeLLM, FakeResponse, FakeToolCall

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ("on_item_added", "note_item", "schedule")  # what a conversation_item_added event runs, in order
MEMORY_WORK = {"extract", "merge", "apply_fact_ops", "add_fact", "journal", "delete_fact", "invalidate_fact",
               "valid_facts", "fact_history", "forget_me", "write", "flush", "do_remember", "do_forget"}


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
    assert len(registrations) == 1
    handler = registrations[0].args[1]
    assert isinstance(handler, ast.Attribute) and handler.attr == "on_item_added"

    for path in sorted((ROOT / "concierge").rglob("*.py")):
        for fn in _functions(path).values():
            if fn.name not in ("on_user_turn_completed", "on_item_added", "note_item"):
                continue
            for node in (n for n in ast.walk(fn) if isinstance(n, ast.Await)):
                assert not _called_names(node) & MEMORY_WORK, f"{path.name}:{node.lineno} awaits memory work"


class LoopGuardStore(Store):
    """A store that raises when called on the event loop's thread (the test runs the loop on the main thread)."""

    def _guard(self) -> None:
        if threading.current_thread() is threading.main_thread():
            raise AssertionError("a store call ran on the event loop")


def _guarded(real: Any) -> Any:  # noqa: ANN401
    def call(self: LoopGuardStore, *args: Any, **kwargs: Any) -> Any:
        self._guard()
        return real(self, *args, **kwargs)

    return call


for _name in ("apply_fact_ops", "valid_facts", "fact_history", "journal", "journal_rows", "state", "version",
              "write"):
    setattr(LoopGuardStore, _name, _guarded(getattr(Store, _name)))


async def test_handler_never_calls_the_store(tmp_path: Path, visitor_id: str) -> None:
    store = Store(tmp_path / "guard.db")
    thread_id = store.get_or_create_thread(visitor_id).id
    store.close()
    guarded = LoopGuardStore(tmp_path / "guard.db")
    fake = FakeLLM([emit()])
    writer = MemoryWriter(guarded, thread_id, "s1", lambda: fake, debounce_s=60)
    try:
        for item in (llm.ChatMessage(role="assistant", content=["Hello."], id="a0"),
                     llm.ChatMessage(role="user", content=["I work at Acme."], id="u1")):
            writer.on_item_added(ConversationItemAddedEvent(item=item))  # would raise on a store call
        await writer.flush()  # the run's store calls go through the writer's own thread
        rows = await asyncio.to_thread(guarded.journal_rows, thread_id)
        assert [r.type for r in rows] == ["agent_turn", "user_turn", "extraction_ran"]
    finally:
        await writer.aclose()
        await asyncio.to_thread(guarded.close)

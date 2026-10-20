"""What "Forget me" runs on the session side (spec §4.2 "Erasure wins over pending work"; C6 wires the page's request
here): cancel the pending memory work first (the extraction, and through the erase hooks the compaction), then erase.
"""

from __future__ import annotations

from collections.abc import Callable
from weakref import WeakKeyDictionary, WeakMethod

from concierge.memory_writer import MemoryWriter

# Weak both ways: the hook's object (the Compactor) holds the writer, so a strong value would keep its own key alive.
_hooks: WeakKeyDictionary[MemoryWriter, list[WeakMethod[Callable[[], None]]]] = WeakKeyDictionary()


def add_erase_hook(writer: MemoryWriter, hook: Callable[[], None]) -> None:
    """`hook()` (a bound method: the Compactor's `cancel`) runs right after `writer.cancel_all()` when the visitor is
    forgotten. Held weakly: the session keeps the Compactor alive."""
    _hooks.setdefault(writer, []).append(WeakMethod(hook))


def cancel_pending(writer: MemoryWriter) -> None:
    """Every pending piece of memory work for this session: `erased` first, then the hooks. No await."""
    writer.cancel_all()
    for ref in _hooks.pop(writer, ()):
        if (hook := ref()) is not None:
            hook()


async def forget_visitor(writer: MemoryWriter, visitor_id: str) -> bool:
    """Cancel the pending work, then erase, after any store call already in flight. False when the visitor had no
    thread."""
    cancel_pending(writer)
    return await writer.call(writer.store.forget_me, visitor_id)

"""What "Forget me" runs on the session side (spec §4.2 "Erasure wins over pending work"; C6 wires the page's request
here): cancel the pending memory work first, then erase.
"""

from __future__ import annotations

from concierge.memory_writer import MemoryWriter


async def forget_visitor(writer: MemoryWriter, visitor_id: str) -> bool:
    """Cancel the pending work, then erase, after any store call already in flight. False when the visitor had no
    thread."""
    writer.cancel_all()
    return await writer.call(writer.store.forget_me, visitor_id)

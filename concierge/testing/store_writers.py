"""Child-process targets for the multi-process store tests (spawn pickles them by module name, so they live in an
importable package rather than in tests/)."""

from __future__ import annotations

from multiprocessing.synchronize import Barrier

from concierge.store import Store


def open_and_touch(db: str, visitor_id: str, barrier: Barrier) -> None:
    """Open a (possibly brand-new) store file at the same moment as the other children, then write to it."""
    barrier.wait(timeout=30)
    with Store(db) as store:
        thread = store.get_or_create_thread(visitor_id)
        store.journal(thread.id, "a" * 32, "session_started", {})

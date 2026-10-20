"""Child-process targets for the multi-process store tests (spawn pickles them by module name, so they live in an
importable package rather than in tests/)."""

from __future__ import annotations

from multiprocessing.synchronize import Barrier

from concierge.models import AddFact
from concierge.store import Store


def open_and_touch(db: str, visitor_id: str, barrier: Barrier) -> None:
    """Open a (possibly brand-new) store file at the same moment as the other children, then write to it."""
    barrier.wait(timeout=30)
    with Store(db) as store:
        thread = store.get_or_create_thread(visitor_id)
        store.journal(thread.id, "a" * 32, "session_started", {})


def write_facts(db: str, thread_id: str, prefix: str, n: int, barrier: Barrier) -> None:
    """Add n `interests` facts "<prefix> <i>", one apply_fact_ops call each, racing the other children."""
    with Store(db) as store:
        barrier.wait(timeout=30)
        for i in range(n):
            op = AddFact(slot="interests", value=f"{prefix} {i}", source="user_said", channel="text", turn_id=f"t{i}")
            store.apply_fact_ops(thread_id, [op])

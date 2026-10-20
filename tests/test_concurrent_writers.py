import multiprocessing

from concierge.store import Store
from concierge.testing.store_writers import write_facts


def test_two_processes_writing_one_thread_both_land(tmp_path, visitor_id) -> None:
    # Two processes, one thread, 20 one-op apply_fact_ops calls each: the fence makes every write land once.
    db = str(tmp_path / "memory.db")
    with Store(db) as store:
        thread = store.get_or_create_thread(visitor_id)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    procs = [ctx.Process(target=write_facts, args=(db, thread.id, prefix, 20, barrier)) for prefix in ("a", "b")]
    try:
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
    finally:
        for p in procs:
            if p.is_alive():  # a hung child would otherwise block pytest's exit
                p.terminate()
    assert [p.exitcode for p in procs] == [0, 0]  # a child's exception exits 1
    with Store(db) as store:
        valid = store.valid_facts(thread.id)
        assert len(valid) == 40
        assert sorted(f.value for f in valid) == sorted(f"{p} {i}" for p in "ab" for i in range(20))
        assert store.version(thread.id) == 40

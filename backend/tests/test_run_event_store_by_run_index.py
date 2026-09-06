"""Regression tests for MemoryRunEventStore's run-keyed event/message index.

``list_events`` and ``list_messages_by_run`` are served from per-run
projections so a single run's reads cost O(events-in-run) instead of
re-scanning O(events-in-thread). These tests pin the indexed implementation to
the exact semantics of a brute-force full-thread scan -- including interleaved
trace events (non-contiguous message seqs), both cursors supplied at once, and
index upkeep after ``delete_by_run`` -- so the optimization can never silently
drift from the reference behavior.
"""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


def _ref_messages_by_run(records, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None):
    """Brute-force reference: the pre-index full-thread scan it replaced."""
    filtered = [e for e in records if e["thread_id"] == thread_id and e["run_id"] == run_id and e["category"] == "message"]
    if before_seq is not None:
        filtered = [e for e in filtered if e["seq"] < before_seq]
    if after_seq is not None:
        filtered = [e for e in filtered if e["seq"] > after_seq]
    if after_seq is not None:
        return filtered[:limit]
    return filtered[-limit:] if len(filtered) > limit else filtered


def _ref_events(records, thread_id, run_id, *, event_types=None, limit=500):
    filtered = [e for e in records if e["thread_id"] == thread_id and e["run_id"] == run_id]
    if event_types is not None:
        filtered = [e for e in filtered if e["event_type"] in event_types]
    return filtered[:limit]


async def _seed(store):
    """Two runs interleaved within one thread; messages and traces mixed so
    each run's message seqs are non-contiguous (the bisect must handle gaps)."""
    plan = [
        ("run-a", "message"),
        ("run-a", "trace"),
        ("run-b", "message"),
        ("run-a", "message"),
        ("run-b", "trace"),
        ("run-b", "message"),
        ("run-a", "trace"),
        ("run-a", "message"),
        ("run-b", "message"),
        ("run-a", "message"),
        ("run-b", "message"),
        ("run-a", "message"),
    ]
    records = []
    for i, (run_id, category) in enumerate(plan):
        rec = await store.put(thread_id="t1", run_id=run_id, event_type=f"e{i}", category=category, content=str(i))
        records.append(rec)
    return records


@pytest.mark.anyio
async def test_list_messages_by_run_matches_reference_across_cursors():
    store = MemoryRunEventStore()
    records = await _seed(store)
    seqs = [r["seq"] for r in records]
    cursors = [None, 0, *seqs, max(seqs) + 1]
    for run_id in ("run-a", "run-b", "run-missing"):
        for limit in (1, 2, 3, 50):
            for before_seq in cursors:
                for after_seq in cursors:
                    got = await store.list_messages_by_run("t1", run_id, limit=limit, before_seq=before_seq, after_seq=after_seq)
                    want = _ref_messages_by_run(records, "t1", run_id, limit=limit, before_seq=before_seq, after_seq=after_seq)
                    assert got == want, (run_id, limit, before_seq, after_seq)


@pytest.mark.anyio
async def test_list_events_matches_reference_with_filters():
    store = MemoryRunEventStore()
    records = await _seed(store)
    all_types = sorted({r["event_type"] for r in records})
    for run_id in ("run-a", "run-b", "run-missing"):
        assert await store.list_events("t1", run_id) == _ref_events(records, "t1", run_id)
        assert await store.list_events("t1", run_id, limit=2) == _ref_events(records, "t1", run_id, limit=2)
        for et in all_types:
            assert await store.list_events("t1", run_id, event_types=[et]) == _ref_events(records, "t1", run_id, event_types=[et])


@pytest.mark.anyio
async def test_run_keyed_index_partitions_every_event():
    """Every stored event is filed under exactly its (thread, run), each run's
    list is seq-ordered, and the union reconstructs the flat event log."""
    store = MemoryRunEventStore()
    records = await _seed(store)
    indexed = [e for run_events in store._events_by_run["t1"].values() for e in run_events]
    assert sorted(e["seq"] for e in indexed) == sorted(r["seq"] for r in records)
    for run_id, run_events in store._events_by_run["t1"].items():
        assert all(e["run_id"] == run_id for e in run_events)
        assert [e["seq"] for e in run_events] == sorted(e["seq"] for e in run_events)
    for run_id, run_msgs in store._messages_by_run["t1"].items():
        assert all(e["run_id"] == run_id and e["category"] == "message" for e in run_msgs)


@pytest.mark.anyio
async def test_run_index_stays_in_lockstep_after_delete_by_run():
    store = MemoryRunEventStore()
    await _seed(store)
    removed = await store.delete_by_run("t1", "run-a")
    assert removed == 7  # run-a: 5 messages + 2 traces

    # The deleted run vanishes from both per-run reads.
    assert await store.list_events("t1", "run-a") == []
    assert await store.list_messages_by_run("t1", "run-a") == []
    assert "run-a" not in store._events_by_run.get("t1", {})
    assert "run-a" not in store._messages_by_run.get("t1", {})

    # The surviving run is untouched, and the thread-wide projection agrees.
    msgs_b = await store.list_messages_by_run("t1", "run-b")
    assert len(msgs_b) == 4
    assert all(m["run_id"] == "run-b" for m in msgs_b)
    assert all(m["run_id"] == "run-b" for m in await store.list_messages("t1"))


@pytest.mark.anyio
async def test_delete_by_thread_clears_run_indexes():
    store = MemoryRunEventStore()
    await _seed(store)
    await store.delete_by_thread("t1")
    assert "t1" not in store._events_by_run
    assert "t1" not in store._messages_by_run
    assert await store.list_events("t1", "run-a") == []
    assert await store.list_messages_by_run("t1", "run-b") == []

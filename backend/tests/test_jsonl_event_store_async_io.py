"""Concurrency-safety tests for JsonlRunEventStore async I/O hardening (#2816).

Verifies:
- write-lock serialises concurrent puts within the same thread_id
- put_batch keeps monotonic seq even under concurrent callers
- seq recovery from disk on fresh store init
- DB put_batch rejects mixed-thread batches
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(base_dir: Path) -> JsonlRunEventStore:
    return JsonlRunEventStore(base_dir=base_dir)


# ---------------------------------------------------------------------------
# Write-lock: per-thread lock exists and is reused
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_write_lock_returns_asyncio_lock():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        lock = store._get_write_lock("t1")
        assert isinstance(lock, asyncio.Lock)


@pytest.mark.anyio
async def test_get_write_lock_same_thread_reuses_lock():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        lock_a = store._get_write_lock("t1")
        lock_b = store._get_write_lock("t1")
        assert lock_a is lock_b


@pytest.mark.anyio
async def test_get_write_lock_different_threads_get_different_locks():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        lock_a = store._get_write_lock("t1")
        lock_b = store._get_write_lock("t2")
        assert lock_a is not lock_b


# ---------------------------------------------------------------------------
# Seq monotonicity under concurrent puts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_puts_produce_unique_monotonic_seqs():
    """10 concurrent puts on the same thread must yield distinct, monotonic seq values."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        results = await asyncio.gather(*[store.put(thread_id="t1", run_id=f"r{i}", event_type="trace", category="trace", content=f"msg{i}") for i in range(10)])
    seqs = sorted(r["seq"] for r in results)
    assert seqs == list(range(1, 11)), f"Expected 1-10, got {seqs}"


@pytest.mark.anyio
async def test_concurrent_puts_different_threads_independent_seqs():
    """Concurrent puts on different threads keep independent seq counters."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        t1_results, t2_results = await asyncio.gather(
            asyncio.gather(*[store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace") for _ in range(5)]),
            asyncio.gather(*[store.put(thread_id="t2", run_id="r2", event_type="trace", category="trace") for _ in range(5)]),
        )
    t1_seqs = sorted(r["seq"] for r in t1_results)
    t2_seqs = sorted(r["seq"] for r in t2_results)
    assert t1_seqs == [1, 2, 3, 4, 5]
    assert t2_seqs == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# put_batch: assigns monotonic seqs and preserves per-run files
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_batch_seqs_are_monotonic():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        events = [{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace", "content": str(i)} for i in range(5)]
        results = await store.put_batch(events)
    seqs = [r["seq"] for r in results]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 5


@pytest.mark.anyio
async def test_put_batch_writes_mixed_run_ids_to_their_run_files():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "r1-first"},
            {"thread_id": "t1", "run_id": "r2", "event_type": "human_message", "category": "message", "content": "r2-only"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "r1-last"},
        ]
        records = await store.put_batch(events)
        r1_messages = await store.list_messages_by_run("t1", "r1")
        r2_messages = await store.list_messages_by_run("t1", "r2")

    assert [(record["run_id"], record["seq"]) for record in records] == [("r1", 1), ("r2", 2), ("r1", 3)]
    assert [message["content"] for message in r1_messages] == ["r1-first", "r1-last"]
    assert [message["content"] for message in r2_messages] == ["r2-only"]


# ---------------------------------------------------------------------------
# _ensure_seq_loaded: recovers max_seq from disk after fresh store init
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ensure_seq_loaded_recovers_from_disk():
    """A fresh JsonlRunEventStore should pick up the max seq written by a previous instance."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store1 = _make_store(base)
        for i in range(3):
            await store1.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content=str(i))

        store2 = _make_store(base)
        record = await store2.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content="new")
        assert record["seq"] == 4, f"Expected seq=4 after recovery, got {record['seq']}"


# ---------------------------------------------------------------------------
# asyncio.to_thread regression guard
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_offloads_write_via_to_thread():
    """Regression guard: put() must call asyncio.to_thread for _write_record."""
    original = asyncio.to_thread
    calls: list[str] = []

    async def spy(*args, **kwargs):
        calls.append(args[0].__name__ if callable(args[0]) else repr(args[0]))
        return await original(*args, **kwargs)

    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        with patch("asyncio.to_thread", new=spy):
            await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content="x")

    assert "_write_record" in calls, f"Expected asyncio.to_thread(_write_record, ...) — got: {calls}"


# ---------------------------------------------------------------------------
# put_batch failure rollback: a failed append must not leave partial records
# so a caller re-buffering the batch on retry does not produce duplicates.
# Regression for deer-flow PR #4082 (review feedback from willem-bd).
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_batch_failure_rolls_back_no_partial_records(monkeypatch):
    """A failed append is rolled back before the re-buffered batch is retried."""
    import json

    from deerflow.runtime.events.store import jsonl as jsonl_mod

    real_append = jsonl_mod.JsonlRunEventStore._append_records

    def failing_append(self, path, records):
        # Write half the lines, then raise to simulate disk-full mid-batch.
        path.parent.mkdir(parents=True, exist_ok=True)
        mid = len(records) // 2
        partial = "".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in records[:mid])
        with open(path, "a", encoding="utf-8") as f:
            f.write(partial)
        raise OSError("simulated mid-batch write failure")

    monkeypatch.setattr(jsonl_mod.JsonlRunEventStore, "_append_records", failing_append)

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        events = [
            {
                "thread_id": "t1",
                "run_id": "r1",
                "event_type": "trace",
                "category": "trace",
                "content": f"event-{i}",
            }
            for i in range(4)
        ]
        # First attempt — fails after partial output; expect raise. The
        # in-memory seq counter is advanced because reservation happens under
        # the lock, but the partial file contents must be rolled back.
        with pytest.raises(OSError):
            await store.put_batch(events)

        # Retry the full batch with the real append, matching worker.py's
        # re-buffer path. Verify persisted contents below, not only return
        # values, so a duplicate or partial disk write cannot pass unnoticed.
        monkeypatch.setattr(jsonl_mod.JsonlRunEventStore, "_append_records", real_append)
        records = await store.put_batch(events)
        persisted_events = await store.list_events("t1", "r1")

    # The batch succeeded on retry, every event ended up exactly once on disk,
    # and seqs are still strictly monotonic.
    assert len(records) == 4, f"Expected 4 records, got {len(records)}"
    seqs = [r["seq"] for r in records]
    assert seqs == sorted(seqs) and len(set(seqs)) == 4, f"seqs not unique monotonic: {seqs}"
    assert len(persisted_events) == 4
    assert [event["content"] for event in persisted_events] == [f"event-{i}" for i in range(4)]
    assert [event["seq"] for event in persisted_events] == seqs


@pytest.mark.anyio
async def test_mixed_run_batch_failure_restores_all_run_files(monkeypatch):
    """A failed mixed-run append restores prior bytes in every touched file."""
    from deerflow.runtime.events.store import jsonl as jsonl_mod

    real_append = jsonl_mod.JsonlRunEventStore._append_records
    append_calls = 0

    def failing_append(self, path, records):
        nonlocal append_calls
        append_calls += 1
        if append_calls == 2:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write("partial\n")
            raise OSError("simulated second-run write failure")
        real_append(self, path, records)

    monkeypatch.setattr(jsonl_mod.JsonlRunEventStore, "_append_records", failing_append)

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace", content="existing")
        r1_path = store._run_file("t1", "r1")
        r2_path = store._run_file("t1", "r2")
        original_r1 = r1_path.read_bytes()

        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace", "content": "new-r1"},
            {"thread_id": "t1", "run_id": "r2", "event_type": "trace", "category": "trace", "content": "new-r2"},
        ]
        with pytest.raises(OSError, match="second-run"):
            await store.put_batch(events)

        assert r1_path.read_bytes() == original_r1
        assert not r2_path.exists()
        assert [event["content"] for event in await store.list_events("t1", "r1")] == ["existing"]
        assert await store.list_events("t1", "r2") == []


@pytest.mark.anyio
async def test_mixed_run_batch_logs_error_when_rollback_fails(monkeypatch, caplog):
    """A rollback failure must make possible retry duplicates visible to operators."""
    from deerflow.runtime.events.store import jsonl as jsonl_mod

    real_append = jsonl_mod.JsonlRunEventStore._append_records
    real_unlink = Path.unlink
    append_calls = 0

    def failing_append(self, path, records):
        nonlocal append_calls
        append_calls += 1
        if append_calls == 2:
            real_append(self, path, records)
            raise OSError("simulated second-run write failure")
        real_append(self, path, records)

    monkeypatch.setattr(jsonl_mod.JsonlRunEventStore, "_append_records", failing_append)

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        r2_path = store._run_file("t1", "r2")

        def failing_unlink(path, missing_ok=False):
            if path == r2_path:
                raise OSError("simulated rollback failure")
            return real_unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", failing_unlink)
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"},
            {"thread_id": "t1", "run_id": "r2", "event_type": "trace", "category": "trace"},
        ]
        with caplog.at_level(logging.ERROR, logger=jsonl_mod.__name__), pytest.raises(OSError, match="second-run"):
            await store.put_batch(events)

        assert r2_path.exists()

    rollback_errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("duplicate records" in record.getMessage() for record in rollback_errors)


# ---------------------------------------------------------------------------
# Read methods are non-blocking (asyncio.to_thread path exercised)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_messages_reads_written_records():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="world")
        messages = await store.list_messages("t1")
    assert len(messages) == 2
    assert messages[0]["content"] == "hello"
    assert messages[1]["content"] == "world"


@pytest.mark.anyio
async def test_count_messages_accurate_after_concurrent_writes():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await asyncio.gather(*[store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message") for _ in range(7)])
        count = await store.count_messages("t1")
    assert count == 7


# ---------------------------------------------------------------------------
# delete_by_thread and delete_by_run use the write lock
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_by_thread_clears_seq_counter_and_lock():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace")
        await store.delete_by_thread("t1")
        assert "t1" not in store._seq_counters
        assert "t1" not in store._write_locks


@pytest.mark.anyio
async def test_delete_by_run_removes_run_events():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        await store.put(thread_id="t1", run_id="r1", event_type="trace", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="trace", category="trace")
        await store.delete_by_run("t1", "r1")
        events = await store.list_events("t1", "r1")
    assert events == []


# ---------------------------------------------------------------------------
# DB put_batch: rejects mixed-thread batches
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_db_put_batch_rejects_mixed_thread_ids():
    """DbRunEventStore.put_batch must raise ValueError for cross-thread batches."""
    from unittest.mock import MagicMock

    from deerflow.runtime.events.store.db import DbRunEventStore

    mock_sf = MagicMock()
    store = DbRunEventStore(session_factory=mock_sf)

    events = [
        {"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"},
        {"thread_id": "t2", "run_id": "r2", "event_type": "trace", "category": "trace"},
    ]

    with pytest.raises(ValueError, match="same thread"):
        await store.put_batch(events)

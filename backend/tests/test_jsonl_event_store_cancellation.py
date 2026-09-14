"""Disk mutations retain thread ownership after caller cancellation (#5438)."""

from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore


def _event(run_id="r1", content="message"):
    return {"thread_id": "t1", "run_id": run_id, "event_type": "message", "category": "message", "content": content}


class _PausedIO:
    """Pause real filesystem work at a known point, without timing-based races."""

    def __init__(self, operation):
        self.operation = operation
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = threading.Event()

    def __call__(self, *args):
        self.loop.call_soon_threadsafe(self.entered.set)
        try:
            if not self.release.wait(10):
                raise TimeoutError("test did not release paused filesystem operation")
            return self.operation(*args)
        finally:
            self.loop.call_soon_threadsafe(self.finished.set)


async def _checkpoint():
    # Let cancellation delivery and already-ready lock waiters run. I/O completion
    # is controlled by Events, not by elapsed time or a fixed sleep budget.
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["put", "put_if_absent", "put_batch"])
@pytest.mark.parametrize("cancellations", [1, 3])
async def test_cancelled_write_cannot_recreate_deleted_records(tmp_path, monkeypatch, method, cancellations):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**_event(content="baseline"))
    io_method = "_append_record_groups" if method == "put_batch" else "_write_record"
    paused = _PausedIO(getattr(store, io_method))
    monkeypatch.setattr(store, io_method, paused)
    operation = getattr(store, method)
    pending = asyncio.create_task(operation([_event("r2")]) if method == "put_batch" else operation(**_event("r2")))
    deletion = None
    try:
        await asyncio.wait_for(paused.entered.wait(), 5)
        for _ in range(cancellations):
            pending.cancel()
            await _checkpoint()
        deletion = asyncio.create_task(store.delete_by_thread("t1"))
        await _checkpoint()
        assert not pending.done(), "cancellation returned while disk mutation still owned the thread"
        assert not deletion.done(), "deletion overtook the cancelled disk mutation"
        paused.release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert await deletion == 2
        assert await store.count_messages("t1") == 0
        assert "t1" not in store._seq_counters
        assert "t1" not in store._write_locks
    finally:
        paused.release.set()
        await asyncio.gather(pending, *([deletion] if deletion is not None else []), return_exceptions=True)
        await asyncio.wait_for(paused.finished.wait(), 5)


@pytest.mark.anyio
@pytest.mark.parametrize("cancel", [False, True])
async def test_old_batch_rollback_cannot_erase_later_acknowledged_write(tmp_path, monkeypatch, cancel):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**_event(content="baseline"))
    append = store._append_records

    def fail_second_file(path, records):
        raise OSError("injected append failure")

    paused = _PausedIO(fail_second_file)

    def append_with_failure(path, records):
        if path.stem == "r2":
            return paused(path, records)
        return append(path, records)

    monkeypatch.setattr(store, "_append_records", append_with_failure)
    batch = asyncio.create_task(store.put_batch([_event(content="batch-a"), _event("r2", "batch-b")]))
    writer = None
    try:
        await asyncio.wait_for(paused.entered.wait(), 5)
        if cancel:
            batch.cancel()
            await _checkpoint()
            batch.cancel()
            await _checkpoint()
        writer = asyncio.create_task(store.put(**_event(content="acknowledged-later")))
        await _checkpoint()
        assert not writer.done(), "a new writer entered before rollback settled"
        paused.release.set()
        with pytest.raises(asyncio.CancelledError if cancel else OSError) as caught:
            await batch
        if cancel:
            assert isinstance(caught.value.__cause__, OSError)
        saved = await writer
        assert saved["content"] == "acknowledged-later"
        assert [row["content"] for row in await store.list_messages("t1")] == ["baseline", "acknowledged-later"]
        assert await store.list_events("t1", "r2") == []
    finally:
        paused.release.set()
        await asyncio.gather(batch, *([writer] if writer is not None else []), return_exceptions=True)
        await asyncio.wait_for(paused.finished.wait(), 5)


@pytest.mark.anyio
@pytest.mark.parametrize("method,io_method", [("delete_by_thread", "_delete_thread_files"), ("delete_by_run", "_delete_run_file")])
async def test_cancelled_delete_cannot_erase_later_write(tmp_path, monkeypatch, method, io_method):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**_event(content="baseline"))
    paused = _PausedIO(getattr(store, io_method))
    monkeypatch.setattr(store, io_method, paused)
    pending = asyncio.create_task(store.delete_by_thread("t1") if method == "delete_by_thread" else store.delete_by_run("t1", "r1"))
    writer = None
    try:
        await asyncio.wait_for(paused.entered.wait(), 5)
        pending.cancel()
        await _checkpoint()
        pending.cancel()
        await _checkpoint()
        writer = asyncio.create_task(store.put(**_event(content="later")))
        await _checkpoint()
        assert not pending.done()
        assert not writer.done()
        paused.release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        saved = await writer
        assert saved["seq"] == (1 if method == "delete_by_thread" else 2)
        assert [row["content"] for row in await store.list_messages("t1")] == ["later"]
    finally:
        paused.release.set()
        await asyncio.gather(pending, *([writer] if writer is not None else []), return_exceptions=True)
        await asyncio.wait_for(paused.finished.wait(), 5)


@pytest.mark.anyio
async def test_cancellation_while_waiting_for_lock_never_starts_write(tmp_path):
    store = JsonlRunEventStore(tmp_path)
    async with store._get_write_lock("t1"):
        pending = asyncio.create_task(store.put(**_event()))
        await _checkpoint()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert await store.count_messages("t1") == 0
    assert not list(tmp_path.rglob("*.jsonl"))


@pytest.mark.anyio
async def test_cancelled_idempotent_write_is_visible_to_retry_and_other_threads_progress(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)
    write = store._write_record
    paused = _PausedIO(write)

    def pause_first_thread(record):
        return paused(record) if record["thread_id"] == "t1" else write(record)

    monkeypatch.setattr(store, "_write_record", pause_first_thread)
    pending = asyncio.create_task(store.put_if_absent(**_event()))
    retry = None
    try:
        await asyncio.wait_for(paused.entered.wait(), 5)
        pending.cancel()
        await _checkpoint()
        other = await asyncio.wait_for(store.put(**{**_event(), "thread_id": "t2"}), 5)
        assert other["seq"] == 1
        retry = asyncio.create_task(store.put_if_absent(**_event()))
        await _checkpoint()
        assert not retry.done()
        paused.release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        record, inserted = await retry
        assert not inserted
        assert record["seq"] == 1
        assert await store.count_messages("t1") == 1
    finally:
        paused.release.set()
        await asyncio.gather(pending, *([retry] if retry is not None else []), return_exceptions=True)
        await asyncio.wait_for(paused.finished.wait(), 5)

"""Real stores must distinguish retryable rejection from uncertain commits."""

import pytest

from deerflow.runtime.events.store.base import RunEventStoreNotCommittedError
from deerflow.runtime.events.store.jsonl import JsonlRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.worker import _SubagentEventBuffer


def event(thread="t1", run="r1"):
    return dict(thread_id=thread, run_id=run, event_type="subagent.step", category="trace", content="step")


@pytest.mark.asyncio
async def test_jsonl_rollback_allows_retry_without_duplicates(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)
    append = store._append_records

    def fail_after_append(path, records):
        append(path, records)
        if path.stem == "r2":
            raise OSError("append failed")

    monkeypatch.setattr(store, "_append_records", fail_after_append)
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put_batch([event(), event(run="r2")])
    assert await store.list_events("t1", "r1") == []
    assert await store.list_events("t1", "r2") == []
    monkeypatch.setattr(store, "_append_records", append)
    await store.put_batch([event(), event(run="r2")])
    assert len(await store.list_events("t1", "r1")) == 1
    assert len(await store.list_events("t1", "r2")) == 1


@pytest.mark.asyncio
async def test_jsonl_previous_thread_commit_is_not_retryable(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)
    append = store._append_records

    def fail_second_thread(path, records):
        if records[0]["thread_id"] == "t2":
            raise OSError("second thread rejected")
        append(path, records)

    monkeypatch.setattr(store, "_append_records", fail_second_thread)
    with pytest.raises(Exception) as caught:
        await store.put_batch([event(), event(thread="t2")])
    assert not isinstance(caught.value, RunEventStoreNotCommittedError)
    assert len(await store.list_events("t1", "r1")) == 1


@pytest.mark.asyncio
async def test_jsonl_failed_rollback_remains_ambiguous(tmp_path, monkeypatch):
    from pathlib import Path

    store = JsonlRunEventStore(tmp_path)
    append = store._append_records

    def fail_after_append(path, records):
        append(path, records)
        raise OSError("append acknowledgement lost")

    def fail_unlink(self, *args, **kwargs):
        raise OSError("rollback failed")

    monkeypatch.setattr(store, "_append_records", fail_after_append)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(OSError, match="acknowledgement lost"):
        await store.put_batch([event()])
    assert len(await store.list_events("t1", "r1")) == 1


@pytest.mark.asyncio
async def test_db_checkout_failure_can_retry(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
    from deerflow.runtime.events.store.db import DbRunEventStore

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: RunEventRow.__table__.create(c))
        await connection.run_sync(lambda c: RunEventThreadSeqRow.__table__.create(c))
    store = DbRunEventStore(async_sessionmaker(engine, expire_on_commit=False))
    original = store._max_seq_for_thread

    async def fail_checkout(*args):
        raise ConnectionError("checkout failed before write")

    try:
        monkeypatch.setattr(store, "_max_seq_for_thread", fail_checkout)
        with pytest.raises(RunEventStoreNotCommittedError):
            await store.put_batch([event()])
        monkeypatch.setattr(store, "_max_seq_for_thread", original)
        await store.put_batch([event()])
        assert len(await store.list_events("t1", "r1", user_id=None)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_db_lost_commit_acknowledgement_remains_ambiguous(tmp_path):
    from sqlalchemy import event as sa_event
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session

    from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
    from deerflow.runtime.events.store.db import DbRunEventStore

    class LostAckSession(Session):
        pass

    @sa_event.listens_for(LostAckSession, "after_commit")
    def lose_ack(session):
        raise OSError("commit acknowledgement lost")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: RunEventRow.__table__.create(c))
        await connection.run_sync(lambda c: RunEventThreadSeqRow.__table__.create(c))
    store = DbRunEventStore(async_sessionmaker(engine, class_=AsyncSession, sync_session_class=LostAckSession, expire_on_commit=False))
    try:
        with pytest.raises(OSError, match="acknowledgement lost"):
            await store.put_batch([event()])
        assert len(await store.list_events("t1", "r1", user_id=None)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_jsonl_preparation_failure_is_retryable(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)

    async def fail_load(thread_id):
        raise OSError("read denied before append")

    monkeypatch.setattr(store, "_ensure_seq_loaded", fail_load)
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put_batch([event()])
    assert await store.list_events("t1", "r1") == []


@pytest.mark.asyncio
async def test_repeated_rejection_is_bounded_and_reported(caplog):
    class RejectStore(MemoryRunEventStore):
        calls = 0

        async def put_batch(self, events):
            self.calls += 1
            raise RunEventStoreNotCommittedError("rejected")

    store = RejectStore()
    buffer = _SubagentEventBuffer(store, "thread", "run")
    for index in range(1000):
        await buffer.add({"type": "task_running", "task_id": "child", "message_index": index, "message": {"type": "ai", "content": "step"}})
    await buffer.flush()
    assert store.calls == 3
    assert buffer._pending == []
    buffer.log_summary()
    assert "unconfirmed=27" in caplog.text
    assert "skipped=973" in caplog.text
    assert "child" in caplog.text

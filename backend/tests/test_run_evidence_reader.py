from __future__ import annotations

import asyncio

import pytest
from deerflow_extension_api import InvalidRunEvidenceCursor

from deerflow.extensions.run_evidence import StoreRunEvidenceReader
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore


async def _put_run(store: MemoryRunStore, run_id: str, thread_id: str, *, user_id: str = "user-1") -> None:
    await store.put(run_id, thread_id=thread_id, user_id=user_id)


@pytest.mark.asyncio
async def test_changed_run_cursor_pages_without_loss_and_replays_updates():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    reader = StoreRunEvidenceReader(runs, events, user_id="user-1")
    await _put_run(runs, "run-a", "thread-a")
    await _put_run(runs, "run-b", "thread-b")

    first = await reader.list_changed_runs(cursor=None, limit=1)
    assert [item.run_id for item in first.items] == ["run-a"]
    assert first.has_more is True
    assert first.next_cursor

    await runs.update_status("run-a", "running")
    second = await reader.list_changed_runs(cursor=first.next_cursor, limit=10)
    assert [item.run_id for item in second.items] == ["run-b", "run-a"]
    assert second.has_more is False


@pytest.mark.asyncio
async def test_changed_run_reader_is_bound_to_one_user():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    await _put_run(runs, "mine", "thread-1", user_id="user-1")
    await _put_run(runs, "theirs", "thread-2", user_id="user-2")

    page = await StoreRunEvidenceReader(runs, events, user_id="user-1").list_changed_runs(cursor=None, limit=10)
    assert [item.run_id for item in page.items] == ["mine"]


@pytest.mark.asyncio
async def test_event_pages_resume_and_status_is_authoritative():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    await _put_run(runs, "run-a", "thread-a")
    await runs.update_status("run-a", "error", error="failed")
    for index in range(3):
        await events.put(
            thread_id="thread-a",
            run_id="run-a",
            event_type="test.event",
            category="trace",
            content={"index": index},
        )

    reader = StoreRunEvidenceReader(runs, events, user_id="user-1")
    first = await reader.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=2)
    assert [item.content for item in first.items] == [{"index": 0}, {"index": 1}]
    assert first.has_more is True
    second = await reader.list_run_events(
        thread_id="thread-a",
        run_id="run-a",
        after_seq=first.next_after_seq,
        limit=2,
    )
    assert [item.content for item in second.items] == [{"index": 2}]
    assert second.has_more is False

    status = await reader.get_run_status(thread_id="thread-a", run_id="run-a")
    assert status is not None
    assert status.status == "error"
    assert status.error == "failed"


@pytest.mark.asyncio
async def test_reader_hides_runs_outside_scope_and_rejects_cursor_from_another_scope():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    await _put_run(runs, "run-a", "thread-a", user_id="user-1")
    first = await StoreRunEvidenceReader(runs, events, user_id="user-1").list_changed_runs(cursor=None, limit=1)

    other = StoreRunEvidenceReader(runs, events, user_id="user-2")
    with pytest.raises(InvalidRunEvidenceCursor, match="cursor scope"):
        await other.list_changed_runs(cursor=first.next_cursor, limit=1)
    assert await other.get_run_status(thread_id="thread-a", run_id="run-a") is None
    assert (await other.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=10)).items == ()


@pytest.mark.asyncio
async def test_sql_changed_run_cursor_survives_repository_restart(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    url = f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        repo = RunRepository(get_session_factory())
        await repo.put("run-a", thread_id="thread-a", user_id="user-1")
        reader = StoreRunEvidenceReader(repo, MemoryRunEventStore(), user_id="user-1")
        first = await reader.list_changed_runs(cursor=None, limit=1)
        await repo.put("run-b", thread_id="thread-b", user_id="user-1")
        cursor = first.next_cursor
    finally:
        await close_engine()

    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        restarted = StoreRunEvidenceReader(
            RunRepository(get_session_factory()),
            MemoryRunEventStore(),
            user_id="user-1",
        )
        page = await restarted.list_changed_runs(cursor=cursor, limit=10)
        assert [item.run_id for item in page.items] == ["run-b"]
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_sql_change_positions_are_unique_across_concurrent_threads(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repositories = [RunRepository(factory) for _ in range(12)]
        await asyncio.gather(
            *(
                repository.put(
                    f"run-{index:02d}",
                    thread_id=f"thread-{index:02d}",
                    user_id="user-1",
                )
                for index, repository in enumerate(repositories)
            )
        )

        rows = await repositories[0].list_changed(
            after_change_seq=-1,
            after_run_id="",
            user_id="user-1",
            limit=20,
        )
        positions = [row["change_seq"] for row in rows]
        assert len(rows) == 12
        assert positions == sorted(positions)
        assert len(set(positions)) == len(positions)
    finally:
        await engine.dispose()

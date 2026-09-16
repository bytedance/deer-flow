from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
@pytest.mark.parametrize("event_backend", ["memory", "jsonl", "db"])
async def test_event_views_detach_nested_payloads_from_store(tmp_path, event_backend):
    engine = None
    runs = MemoryRunStore()
    if event_backend == "memory":
        events = MemoryRunEventStore()
    elif event_backend == "jsonl":
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        events = JsonlRunEventStore(tmp_path / "events")
    else:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.runtime.events.store.db import DbRunEventStore

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        events = DbRunEventStore(async_sessionmaker(engine, expire_on_commit=False))

    await _put_run(runs, "run-a", "thread-a")
    try:
        await events.put(
            thread_id="thread-a",
            run_id="run-a",
            event_type="test.event",
            category="trace",
            content={"text": ["original"]},
            metadata={"custom": {"value": "original"}},
        )

        reader = StoreRunEvidenceReader(runs, events, user_id=None)
        page = await reader.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=10)
        page.items[0].content["text"][0] = "changed"
        page.items[0].metadata["custom"]["value"] = "changed"

        reread = await reader.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=10)
        stored = await events.list_events("thread-a", "run-a", user_id=None)
        assert reread.items[0].content == {"text": ["original"]}
        assert reread.items[0].metadata["custom"] == {"value": "original"}
        assert stored[0]["content"] == {"text": ["original"]}
        assert stored[0]["metadata"]["custom"] == {"value": "original"}
    finally:
        if engine is not None:
            await engine.dispose()


@pytest.mark.asyncio
async def test_db_event_reads_use_reader_scope_not_ambient_user(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository
    from deerflow.runtime import user_context
    from deerflow.runtime.events.store.db import DbRunEventStore

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scoped-events.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        runs = RunRepository(factory)
        events = DbRunEventStore(factory)
        await runs.put("run-a", thread_id="thread-a", user_id="alice")

        alice_token = user_context.set_current_user(SimpleNamespace(id="alice"))
        try:
            await events.put(
                thread_id="thread-a",
                run_id="run-a",
                event_type="test.event",
                category="trace",
                content={"owner": "alice"},
            )
        finally:
            user_context.reset_current_user(alice_token)

        for ambient_user in (None, SimpleNamespace(id="bob")):
            ambient_token = user_context._current_user.set(ambient_user)
            try:
                for reader_user in (None, "alice"):
                    reader = StoreRunEvidenceReader(runs, events, user_id=reader_user)
                    page = await reader.list_run_events(
                        thread_id="thread-a",
                        run_id="run-a",
                        after_seq=None,
                        limit=10,
                    )
                    assert [item.content for item in page.items] == [{"owner": "alice"}]
            finally:
                user_context._current_user.reset(ambient_token)
    finally:
        await engine.dispose()


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
async def test_memory_progress_updates_do_not_advance_changed_run_cursor():
    runs = MemoryRunStore()
    reader = StoreRunEvidenceReader(runs, MemoryRunEventStore(), user_id="user-1")
    await _put_run(runs, "run-a", "thread-a")
    await runs.start_run("run-a")
    before_progress = await reader.list_changed_runs(cursor=None, limit=10)

    await runs.update_run_progress("run-a", total_tokens=10, last_ai_message="working")

    after_progress = await reader.list_changed_runs(cursor=before_progress.next_cursor, limit=10)
    assert after_progress.items == ()
    assert after_progress.next_cursor == before_progress.next_cursor


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
async def test_sql_progress_updates_do_not_advance_changed_run_cursor(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'progress.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        await repo.put("run-a", thread_id="thread-a", user_id="user-1")
        await repo.start_run("run-a")
        reader = StoreRunEvidenceReader(repo, MemoryRunEventStore(), user_id="user-1")
        before_progress = await reader.list_changed_runs(cursor=None, limit=10)

        await repo.update_run_progress("run-a", total_tokens=10, last_ai_message="working")

        after_progress = await reader.list_changed_runs(cursor=before_progress.next_cursor, limit=10)
        assert after_progress.items == ()
        assert after_progress.next_cursor == before_progress.next_cursor
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_atomic_interrupt_allocates_before_run_lock_and_shares_position(tmp_path):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'atomic.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        await repo.put(
            "run-old",
            thread_id="thread-a",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-1",
        )
        statements: list[str] = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        new_run, claimed = await repo.create_thread_operation_atomic(
            "run-new",
            thread_id="thread-a",
            user_id="user-1",
            owner_worker_id="worker-1",
            lease_expires_at=None,
            multitask_strategy="interrupt",
        )

        assert [run["run_id"] for run in claimed] == ["run-old"]
        assert claimed[0]["change_seq"] == new_run["change_seq"]
        clock_update = next(index for index, statement in enumerate(statements) if statement.startswith("update run_change_clock"))
        run_lock_query = next(index for index, statement in enumerate(statements) if statement.startswith("select runs."))
        assert clock_update < run_lock_query
    finally:
        await engine.dispose()


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

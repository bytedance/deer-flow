"""Run snapshot replacement must move its thread-index membership atomically."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore

USER = "replacement-owner"
CREATED = "2026-01-01T00:00:00+00:00"


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunStore()
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.sqlite'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


async def put(store, run_id="moved", thread="old"):
    await store.put(run_id, thread_id=thread, user_id=USER, status="success", created_at=CREATED, metadata={"replay_kind": "edit", "regenerate_from_run_id": "source"})


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["list", "many", "at-time", "edit", "regenerate", "usage"])
async def test_replaced_snapshot_belongs_only_to_its_current_thread(store, query):
    await put(store)
    await put(store, thread="new")

    async def read(thread):
        if query == "list":
            return {row["run_id"] for row in await store.list_by_thread(thread, user_id=USER)}
        if query == "many":
            return set(await store.get_many_by_thread(thread, {"moved"}, user_id=USER))
        if query == "at-time":
            return {row["run_id"] for row in await store.list_by_thread_created_at(thread, user_id=USER, created_at=CREATED)}
        if query == "edit":
            return {row["run_id"] for row in await store.list_edit_regenerate_runs(thread, user_id=USER)}
        if query == "regenerate":
            return await store.list_successful_regenerate_sources(thread, user_id=USER)
        return (await store.aggregate_tokens_by_thread(thread, user_id=USER))["total_runs"]

    assert await read("old") == (0 if query == "usage" else set())
    assert await read("new") == (1 if query == "usage" else {"source"} if query == "regenerate" else {"moved"})


@pytest.mark.asyncio
async def test_run_manager_hydration_does_not_return_a_reassigned_snapshot(store):
    await put(store)
    await put(store, thread="new")
    manager = RunManager(store=store)
    assert await manager.list_by_thread("old", user_id=USER) == []
    rows = await manager.list_by_thread("new", user_id=USER)
    assert [(row.run_id, row.thread_id) for row in rows] == [("moved", "new")]


@pytest.mark.asyncio
async def test_deleting_old_thread_keeps_reassigned_run_and_new_thread_neighbors(store):
    await put(store)
    await put(store, run_id="old-neighbor")
    await put(store, run_id="new-neighbor", thread="new")
    await put(store, thread="new")

    removed = await store.delete_by_thread("old", user_id=USER)
    assert await store.get("moved", user_id=USER) is not None
    assert removed == 1
    assert await store.list_by_thread("old", user_id=USER) == []
    assert {row["run_id"] for row in await store.list_by_thread("new", user_id=USER)} == {"moved", "new-neighbor"}
    assert await store.delete_by_thread("new", user_id=USER) == 2
    assert await store.get("moved", user_id=USER) is None


@pytest.mark.asyncio
async def test_repeated_replacements_release_empty_thread_buckets():
    store = MemoryRunStore()
    for index in range(16):
        await put(store, thread=f"thread-{index}")
    for index in range(15):
        assert await store.list_by_thread(f"thread-{index}", user_id=USER) == []
    assert set(store._runs_by_thread) == {"thread-15"}
    await store.delete("moved")
    assert store._runs_by_thread == {}


@pytest.mark.asyncio
async def test_same_thread_retry_preserves_index_order():
    store = MemoryRunStore()
    for run in ["first", "second", "third"]:
        await put(store, run_id=run)
    await put(store, run_id="first")
    assert list(store._runs_by_thread["old"]) == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_failed_replacement_keeps_prior_row_and_index():
    store = MemoryRunStore()
    await put(store)
    before = dict(await store.get("moved"))

    class BadCopy:
        def __deepcopy__(self, memo):
            raise ValueError("snapshot copy failed")

    with pytest.raises(ValueError, match="snapshot copy failed"):
        await store.put("moved", thread_id="new", user_id=USER, goal_verdict={"verdict": BadCopy()})
    assert await store.get("moved") == before
    assert [row["run_id"] for row in await store.list_by_thread("old", user_id=USER)] == ["moved"]
    assert set(store._runs_by_thread) == {"old"}

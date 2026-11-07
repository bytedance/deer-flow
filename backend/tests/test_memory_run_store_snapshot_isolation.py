"""Memory-backed run records obey the same snapshot ownership as SQL rows."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.runtime import RunManager
from deerflow.runtime.runs.store.base import RunIdempotencyConflict
from deerflow.runtime.runs.store.memory import MemoryRunStore

USER = "snapshot-owner"
CREATED = "2026-01-01T00:00:00+00:00"
QUERIES = ["get", "thread", "changed", "many", "at-time", "edit", "pending", "inflight", "expired"]


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


async def put(store):
    await store.put(
        "run",
        thread_id="thread",
        user_id=USER,
        created_at=CREATED,
        metadata={"replay_kind": "edit", "regenerate_from_run_id": "source", "tags": ["original"]},
        kwargs={"input": {"messages": ["original"]}},
    )


async def read(store, query):
    if query == "get":
        return await store.get("run", user_id=USER)
    if query == "thread":
        return (await store.list_by_thread("thread", user_id=USER))[0]
    if query == "changed":
        return (await store.list_changed(after_change_seq=0, after_run_id="", user_id=USER))[0]
    if query == "many":
        return (await store.get_many_by_thread("thread", {"run"}, user_id=USER))["run"]
    if query == "at-time":
        return (await store.list_by_thread_created_at("thread", user_id=USER, created_at=CREATED))[0]
    if query == "edit":
        return (await store.list_edit_regenerate_runs("thread", user_id=USER))[0]
    if query == "pending":
        return (await store.list_pending())[0]
    if query == "inflight":
        return (await store.list_inflight())[0]
    return (await store.list_inflight_with_expired_lease())[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", QUERIES)
async def test_query_result_mutation_cannot_rewrite_the_stored_run(store, query):
    await put(store)
    before = await store.get("run", user_id=USER)
    sequence = before["change_seq"]
    row = await read(store, query)
    row["metadata"]["tags"].append("reader-edit")
    row["kwargs"]["input"]["messages"].clear()
    row.update(status="success", thread_id="other-thread", user_id="other-owner")

    current = await store.get("run", user_id=USER)
    assert current is not None
    assert current["status"] == "pending"
    assert current["thread_id"] == "thread"
    assert current["metadata"]["tags"] == ["original"]
    assert current["kwargs"]["input"]["messages"] == ["original"]
    assert current["change_seq"] == sequence
    assert await store.get("run", user_id="other-owner") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("query", QUERIES)
async def test_query_result_keeps_its_observed_status_after_a_store_update(store, query):
    await put(store)
    row = await read(store, query)
    assert await store.start_run("run")
    assert row["status"] == "pending"
    assert (await store.get("run", user_id=USER))["status"] == "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["put", "admit"])
async def test_writes_do_not_retain_caller_metadata_or_kwargs(store, operation):
    metadata = {"tags": ["original"]}
    kwargs = {"input": {"messages": ["original"]}}
    arguments = dict(thread_id="thread", user_id=USER, metadata=metadata, kwargs=kwargs)
    if operation == "put":
        await store.put("run", **arguments)
    else:
        await store.create_thread_operation_atomic("run", owner_worker_id="worker", lease_expires_at=None, **arguments)
    metadata["tags"].clear()
    kwargs["input"]["messages"].append("writer-edit")
    row = await store.get("run", user_id=USER)
    assert row["metadata"] == {"tags": ["original"]}
    assert row["kwargs"] == {"input": {"messages": ["original"]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["progress", "completion"])
async def test_token_usage_updates_do_not_retain_the_callers_nested_counters(store, operation):
    await put(store)
    await store.start_run("run")
    usage = {"model": {"total_tokens": 7}}
    if operation == "progress":
        await store.update_run_progress("run", total_tokens=7, token_usage_by_model=usage)
    else:
        await store.update_run_completion("run", status="success", total_tokens=7, token_usage_by_model=usage)
    usage["model"]["total_tokens"] = 999
    aggregate = await store.aggregate_tokens_by_thread("thread", user_id=USER, include_active=True)
    assert aggregate["by_model"]["model"]["tokens"] == 7
    assert aggregate["total_tokens"] == 7


@pytest.mark.asyncio
async def test_idempotency_conflict_exposes_a_snapshot_not_the_stored_row(store):
    arguments = dict(thread_id="thread", user_id=USER, owner_worker_id="worker", lease_expires_at=None, idempotency_key="key", metadata={"tags": ["original"]})
    await store.create_thread_operation_atomic("run", **arguments)
    with pytest.raises(RunIdempotencyConflict) as error:
        await store.create_thread_operation_atomic("retry", **arguments)
    error.value.existing["metadata"]["tags"].clear()
    error.value.existing["status"] = "success"
    row = await store.get("run", user_id=USER)
    assert row["metadata"]["tags"] == ["original"]
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_run_manager_hydrates_independent_store_only_records(store):
    await put(store)
    manager = RunManager(store=store)
    try:
        record = await manager.get("run", user_id=USER)
        assert record.store_only
        record.metadata["tags"].clear()
        record.kwargs["input"]["messages"].append("reader-edit")
        fresh = await manager.get("run", user_id=USER)
        assert fresh.metadata["tags"] == ["original"]
        assert fresh.kwargs["input"]["messages"] == ["original"]
    finally:
        await manager.shutdown()


class _Uncopyable:
    def __deepcopy__(self, memo):
        raise ValueError("payload copy failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["metadata", "kwargs"])
async def test_failed_admission_copy_keeps_the_existing_run_and_change_cursor(field):
    store = MemoryRunStore()
    await put(store)
    before = await store.get("run", user_id=USER)
    with pytest.raises(ValueError, match="payload copy failed"):
        await store.create_thread_operation_atomic(
            "replacement",
            thread_id="thread",
            user_id=USER,
            owner_worker_id="worker",
            lease_expires_at=None,
            multitask_strategy="interrupt",
            **{field: {"bad": _Uncopyable()}},
        )
    assert await store.get("run", user_id=USER) == before
    assert await store.get("replacement", user_id=USER) is None
    assert await store.list_changed(after_change_seq=before["change_seq"], after_run_id="run", user_id=USER) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["progress", "completion"])
async def test_failed_usage_copy_does_not_partially_update_a_run(operation):
    store = MemoryRunStore()
    await put(store)
    await store.start_run("run")
    before = await store.get("run", user_id=USER)
    with pytest.raises(ValueError, match="payload copy failed"):
        if operation == "progress":
            await store.update_run_progress("run", total_tokens=7, token_usage_by_model={"bad": _Uncopyable()})
        else:
            await store.update_run_completion("run", status="success", total_tokens=7, token_usage_by_model={"bad": _Uncopyable()})
    assert await store.get("run", user_id=USER) == before

"""Native batch dependencies use committed outcomes without occupying worker slots."""

import os
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.schema import DropSchema

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repo(tmp_path, request):
    config = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        config = DatabaseConfig(backend="postgres", postgres_url=uri, postgres_schema="native_batch_" + uuid4().hex)
    await init_engine_from_config(config)
    try:
        yield SubagentBatchRepository(get_session_factory())
    finally:
        if config.backend == "postgres":
            async with get_engine().begin() as connection:
                await connection.execute(DropSchema(config.postgres_schema, cascade=True))
        await close_engine()


async def create(repo, items, **overrides):
    values = dict(
        batch_id="batch",
        user_id="owner",
        thread_id="thread",
        run_id="run",
        tool_call_id="call",
        submission_key="run:call",
        title="Compare source files",
        subagent_type="general-purpose",
        items=items,
        max_live_items=3,
        max_running_items=3,
        max_attempts=1,
        execution_spec={},
    )
    return await repo.create_batch(**(values | overrides))


async def claim(repo, *, now=None, limit=3):
    return await repo.claim_items(now=now or datetime.now(UTC), lease_owner="worker", lease_seconds=120, limit=limit)


async def finish(repo, item, *, succeeded=True, stop_reason=None, **overrides):
    values = dict(
        lease_owner="worker",
        succeeded=succeeded,
        result="A useful result" if succeeded else None,
        result_preview="A useful result" if succeeded else None,
        result_truncated=False,
        error=None if succeeded else "Source unavailable",
        stop_reason=stop_reason,
        token_usage=None,
        model_name="local-test",
        completed_at=datetime.now(UTC),
    )
    return await repo.finalize_item(item["id"], **(values | overrides))


@pytest.mark.asyncio
async def test_ready_dependency_starts_before_unrelated_item_finishes_and_survives_reopen(repo):
    await create(
        repo,
        [
            {"key": "d", "prompt": "Combine A and B", "depends_on": ["a", "b"]},
            {"key": "a", "prompt": "Read sales"},
            {"key": "b", "prompt": "Read risks"},
            {"key": "c", "prompt": "Wait for independent appendix"},
        ],
    )
    running = {item["item_key"]: item for item in await claim(repo)}
    assert set(running) == {"a", "b", "c"}
    await finish(repo, running["a"])
    assert await claim(repo) == []
    await finish(repo, running["b"])
    reopened = SubagentBatchRepository(get_session_factory())
    ready = await claim(reopened)
    assert [item["item_key"] for item in ready] == ["d"]
    rows = await reopened.list_items("batch", user_id="owner")
    assert next(item for item in rows if item["item_key"] == "c")["status"] == "leased"
    assert next(item for item in rows if item["item_key"] == "d")["attempt"] == 1


@pytest.mark.asyncio
async def test_failed_prerequisite_blocks_descendants_but_keeps_independent_work(repo):
    await create(
        repo,
        [
            {"key": "a", "prompt": "Missing source"},
            {"key": "d", "prompt": "Requires A", "depends_on": ["a"]},
            {"key": "e", "prompt": "Requires D", "depends_on": ["d"]},
            {"key": "c", "prompt": "Independent work"},
        ],
    )
    running = {item["item_key"]: item for item in await claim(repo)}
    assert set(running) == {"a", "c"}
    await finish(repo, running["a"], succeeded=False)
    assert await claim(repo) == []
    await finish(repo, running["c"])
    batch = await repo.get_batch("batch", user_id="owner")
    assert batch["counts"]["failed"] == 3
    assert batch["counts"]["succeeded"] == 1
    rows = await repo.list_items("batch", user_id="owner")
    assert all(item["attempt"] == 0 for item in rows if item["item_key"] in {"d", "e"})


@pytest.mark.asyncio
@pytest.mark.parametrize("dependencies", [["missing"], ["a"], ["b"]])
async def test_invalid_dependencies_are_rejected_before_any_batch_is_saved(repo, dependencies):
    items = [{"key": "a", "prompt": "A", "depends_on": dependencies}, {"key": "b", "prompt": "B", "depends_on": ["a"]}]
    with pytest.raises(ValueError):
        await create(repo, items)
    assert await repo.get_batch("batch", user_id="owner") is None


@pytest.mark.asyncio
async def test_cancelled_batch_does_not_release_waiting_dependencies(repo):
    await create(
        repo,
        [
            {"key": "done", "prompt": "Already has a result"},
            {"key": "failed", "prompt": "Source unavailable"},
            {"key": "running", "prompt": "Worker started"},
            {"key": "leased", "prompt": "Worker claimed"},
            {"key": "queued", "prompt": "Ready for a worker"},
            {"key": "waiting", "prompt": "Wait for the running item", "depends_on": ["running"]},
        ],
        max_live_items=5,
        max_running_items=4,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    claimed = {item["item_key"]: item for item in await claim(repo, now=now, limit=4)}
    artifact = {"path": "reports/done.md"}
    assert await finish(repo, claimed["done"], result_artifact=artifact, completed_at=now)
    assert await finish(repo, claimed["failed"], succeeded=False, completed_at=now)
    running = claimed["running"]
    assert await repo.mark_item_running(running["id"], lease_owner="worker", now=now)
    await create(repo, [{"key": "unrelated", "prompt": "Another batch"}], batch_id="other", submission_key="run:other")

    before = {item["item_key"]: item for item in await repo.list_items("batch", user_id="owner", include_result=True)}
    assert {key: item["status"] for key, item in before.items()} == {
        "done": "succeeded",
        "failed": "failed",
        "running": "running",
        "leased": "leased",
        "queued": "queued",
        "waiting": "pending",
    }
    assert before["done"]["result"] == "A useful result"
    assert before["done"]["result_artifact"] == artifact
    assert before["failed"]["error"] == "Source unavailable"
    other_before = await repo.get_batch("other", user_id="owner")
    other_items_before = await repo.list_items("other", user_id="owner", include_result=True)

    assert await repo.cancel_batch("missing", user_id="owner") is None
    assert await repo.cancel_batch("batch", user_id="other-owner") is None

    statements = []
    engine = get_engine().sync_engine

    def capture(_connection, _cursor, statement, _parameters, _context, executemany):
        statements.append((" ".join(statement.lower().split()), executemany))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        cancelled = await repo.cancel_batch("batch", user_id="owner")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    item_table = SubagentBatchItemRow.__tablename__
    assert [many for sql, many in statements if sql.startswith(f"update {item_table} ")] == [False]
    item_reads = [sql.split(" from ", 1)[0] for sql, _ in statements if re.search(rf"\bfrom {item_table}\b", sql)]
    assert all(re.fullmatch(rf"select {item_table}\.status, count\(\*\)( as \w+)?", columns) for columns in item_reads), item_reads

    assert cancelled["status"] == "cancelled"
    assert cancelled["counts"] == {"pending": 0, "queued": 0, "leased": 0, "running": 0, "succeeded": 1, "failed": 1, "cancelled": 4}
    assert not await finish(repo, running, result="Late result", result_artifact={"path": "reports/late.md"})
    assert await repo.renew_item_lease(running["id"], lease_owner="worker", lease_seconds=120, now=now + timedelta(seconds=1)) == {"valid": False, "cancel_requested": True}

    after = {item["item_key"]: item for item in await repo.list_items("batch", user_id="owner", include_result=True)}
    assert after["done"] == before["done"]
    assert after["failed"] == before["failed"]
    assert await repo.get_batch("batch", user_id="owner") == cancelled
    assert await repo.get_batch("other", user_id="owner") == other_before
    assert await repo.list_items("other", user_id="owner", include_result=True) == other_items_before

    async with get_session_factory()() as session:
        rows = await session.scalars(select(SubagentBatchItemRow).where(SubagentBatchItemRow.batch_id == "batch"))
        persisted = {row.item_key: row for row in rows}
    cancel_time = datetime.fromisoformat(cancelled["completed_at"])
    for key in ("running", "leased", "queued", "waiting"):
        row = persisted[key]
        assert row.status == "cancelled"
        assert row.error == "Cancelled by user"
        assert row.cancel_requested_at is not None
        assert row.cancel_requested_at == row.updated_at == row.completed_at
        assert row.cancel_requested_at.replace(tzinfo=UTC) == cancel_time
        assert row.lease_owner is None and row.lease_expires_at is None
        assert row.result is None and row.result_artifact is None

    assert await repo.cancel_batch("batch", user_id="owner") is not None
    assert {item["item_key"]: item for item in await repo.list_items("batch", user_id="owner", include_result=True)} == after
    assert [item["batch_id"] for item in await claim(repo)] == ["other"]


@pytest.mark.asyncio
async def test_batch_cancel_rolls_back_after_item_update(repo):
    await create(repo, [{"key": "a", "prompt": "A"}], continuation={"prompt": "Summarize"})
    now = datetime(2026, 1, 1, tzinfo=UTC)
    item = (await claim(repo, now=now))[0]
    batch_before = await repo.get_batch("batch", user_id="owner")
    assert batch_before["continuation_status"] == "pending"
    items_before = await repo.list_items("batch", user_id="owner", include_result=True)

    engine = get_engine().sync_engine
    updated_rows = []
    error = RuntimeError("Cancel interrupted after item update")
    item_table = SubagentBatchItemRow.__tablename__

    def fail_after_item_update(_connection, cursor, statement, _parameters, _context, _executemany):
        if statement.lower().startswith(f"update {item_table} "):
            updated_rows.append(cursor.rowcount)
            raise error

    event.listen(engine, "after_cursor_execute", fail_after_item_update)
    try:
        with pytest.raises(RuntimeError) as exc:
            await repo.cancel_batch("batch", user_id="owner")
    finally:
        event.remove(engine, "after_cursor_execute", fail_after_item_update)

    assert exc.value is error
    assert updated_rows == [1]
    reopened = SubagentBatchRepository(get_session_factory())
    assert await reopened.get_batch("batch", user_id="owner") == batch_before
    assert await reopened.list_items("batch", user_id="owner", include_result=True) == items_before
    async with get_session_factory()() as session:
        persisted = await session.get(SubagentBatchItemRow, item["id"])
    assert persisted is not None
    assert persisted.cancel_requested_at is None
    assert persisted.lease_owner == "worker"
    assert persisted.lease_expires_at is not None
    assert persisted.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(seconds=120)


@pytest.mark.asyncio
async def test_capped_attempt_can_retry_before_releasing_its_dependent(repo):
    await create(repo, [{"key": "a", "prompt": "A"}, {"key": "b", "prompt": "Use A", "depends_on": ["a"]}], max_attempts=3)
    first = (await claim(repo))[0]
    await finish(repo, first, succeeded=False, stop_reason="turn_capped", error="No usable partial result")
    retry = (await claim(repo))[0]
    assert retry["item_key"] == "a" and retry["attempt"] == 2
    await finish(repo, retry)
    ready = await claim(repo)
    assert [item["item_key"] for item in ready] == ["b"]
    assert ready[0]["attempt"] == 1

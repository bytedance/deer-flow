"""Native batch dependencies use committed outcomes without occupying worker slots."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.schema import DropSchema

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository


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


async def claim(repo):
    return await repo.claim_items(now=datetime.now(UTC), lease_owner="worker", lease_seconds=120, limit=3)


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
    await create(repo, [{"key": "a", "prompt": "A"}, {"key": "b", "prompt": "B", "depends_on": ["a"]}])
    running = await claim(repo)
    assert len(running) == 1
    await repo.cancel_batch("batch", user_id="owner")
    await finish(repo, running[0])
    assert await claim(repo) == []
    assert (await repo.get_batch("batch", user_id="owner"))["status"] == "cancelled"


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

"""Exercise real SQL task transitions on both supported databases."""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.coordination.model import TaskStatus
from deerflow.persistence.coordination.sql import CoordinationTaskRepository, TaskConflict, TaskNotFound
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def database(tmp_path, request):
    backend = request.param
    schema = ""
    if backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'coord.db'}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = f"coord_test_{uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield engine, backend, schema
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest_asyncio.fixture
async def repo(database):
    engine, backend, schema = database
    await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema)
    return CoordinationTaskRepository(async_sessionmaker(engine))


async def _finish(repo, task, *, covered_input_seq=None):
    return await repo.finish(
        "alice",
        task["id"],
        expected_revision=task["revision"],
        execution_epoch=task["execution_epoch"],
        covered_input_seq=task["latest_input_seq"] if covered_input_seq is None else covered_input_seq,
        outcome=TaskStatus.SUCCEEDED,
        result_ref="result-1",
    )


@pytest.mark.asyncio
async def test_concurrent_replay_and_owner_isolation(repo):
    async with asyncio.TaskGroup() as group:
        submissions = [group.create_task(repo.create("alice", request_id="message", objective="Review")) for _ in range(4)]
    (task_id,) = {job.result()["id"] for job in submissions}
    bob = await repo.create("bob", request_id="message", objective="Review")
    assert bob["id"] != task_id
    with pytest.raises(TaskConflict, match="different task data"):
        await repo.create("alice", request_id="message", objective="Other work")
    with pytest.raises(TaskNotFound):
        await repo.get("bob", task_id)
    with pytest.raises(TaskNotFound):
        await repo.append_input("bob", task_id, request_id="msg", content="wrong owner")

    async with asyncio.TaskGroup() as group:
        repeats = [group.create_task(repo.append_input("alice", task_id, request_id="one", content="Check storage")) for _ in range(3)]
        other = group.create_task(repo.append_input("alice", task_id, request_id="two", content="Check logs"))
    (sequence,) = {job.result()["sequence"] for job in repeats}
    assert {sequence, other.result()["sequence"]} == {1, 2}
    assert [item["sequence"] for item in await repo.list_inputs("alice", task_id, after=1)] == [2]
    assert await repo.list_inputs("bob", task_id) == []
    with pytest.raises(TaskConflict, match="different input"):
        await repo.append_input("alice", task_id, request_id="one", content="mutated replay")


@pytest.mark.asyncio
async def test_dependencies_release_in_order_and_completion_covers_current_input(repo):
    root = await repo.create("alice", request_id="root", project_id="project", objective="Release")
    first = await repo.create("alice", request_id="a", parent_id=root["id"], objective="Research")
    second = await repo.create("alice", request_id="b", parent_id=root["id"], depends_on=[first["id"]], objective="Review")
    assert first["project_id"] == second["project_id"] == "project"
    with pytest.raises(TaskConflict, match="Dependencies"):
        await repo.create("alice", request_id="bad", depends_on=[first["id"]], objective="Foreign scope")
    with pytest.raises(TaskConflict, match="Parent task has not started"):
        await repo.start("alice", first["id"], expected_revision=0)
    root = await repo.get("alice", root["id"])
    root = await repo.start("alice", root["id"], expected_revision=root["revision"])
    with pytest.raises(TaskConflict, match="dependencies"):
        await repo.start("alice", second["id"], expected_revision=0)
    with pytest.raises(TaskConflict, match="Child tasks"):
        await _finish(repo, root)
    started = await repo.start("alice", first["id"], expected_revision=0)
    await repo.append_input("alice", first["id"], request_id="new", content="Check another file")
    with pytest.raises(TaskConflict, match="revision changed"):
        await _finish(repo, started)
    latest = await repo.get("alice", first["id"])
    with pytest.raises(TaskConflict, match="current task inputs"):
        await _finish(repo, latest, covered_input_seq=0)
    assert (await _finish(repo, latest))["status"] == TaskStatus.SUCCEEDED
    assert (await repo.start("alice", second["id"], expected_revision=0))["status"] == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_tree_fences_running_work_and_leaves_external_dependency(repo):
    prerequisite = await repo.create("alice", request_id="pre", objective="Shared work")
    prerequisite = await repo.start("alice", prerequisite["id"], expected_revision=0)
    await _finish(repo, prerequisite)
    root = await repo.create("alice", request_id="root", objective="Check release", depends_on=[prerequisite["id"]])
    child = await repo.create("alice", request_id="child", parent_id=root["id"], objective="Review")
    nested = await repo.create("alice", request_id="nested", parent_id=child["id"], objective="Test")
    root = await repo.get("alice", root["id"])
    root = await repo.start("alice", root["id"], expected_revision=root["revision"])
    child = await repo.get("alice", child["id"])
    await repo.start("alice", child["id"], expected_revision=child["revision"])
    nested = await repo.start("alice", nested["id"], expected_revision=0)
    cancelling = await repo.request_cancel("alice", root["id"], expected_revision=root["revision"])
    assert cancelling["execution_epoch"] == 1
    assert (await repo.request_cancel("alice", root["id"], expected_revision=root["revision"])) == cancelling
    assert (await repo.get("alice", nested["id"]))["status"] == TaskStatus.CANCELLING
    with pytest.raises(TaskConflict, match="no longer accepts"):
        await _finish(repo, nested)
    with pytest.raises(TaskConflict, match="closed to new input"):
        await repo.append_input("alice", nested["id"], request_id="late", content="Do more")
    with pytest.raises(TaskConflict, match="Parent task is closed"):
        await repo.create("alice", request_id="late-child", parent_id=child["id"], objective="New work")
    with pytest.raises(TaskConflict, match="Cancellation no longer"):
        await repo.confirm_cancel("alice", root["id"], execution_epoch=0)
    await repo.confirm_cancel("alice", root["id"], execution_epoch=1)
    for task in (root, child, nested):
        assert (await repo.get("alice", task["id"]))["status"] == TaskStatus.CANCELLED
    assert (await repo.get("alice", prerequisite["id"]))["status"] == TaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_cancel_and_followup_in_separate_transactions(repo):
    task = await repo.create("alice", request_id="root", objective="Check versions")
    task_id = task["id"]

    async def append():
        try:
            return await repo.append_input("alice", task_id, request_id="one", content="Also check dependencies")
        except TaskConflict:
            return None

    async def cancel():
        try:
            return await repo.request_cancel("alice", task_id, expected_revision=0)
        except TaskConflict:
            return None

    appended, cancelled = await asyncio.gather(append(), cancel())
    assert (appended is None) != (cancelled is None)
    current = await repo.get("alice", task_id)
    assert current["revision"] == 1
    assert current["latest_input_seq"] == int(appended is not None)
    assert current["execution_epoch"] == int(cancelled is not None)


@pytest.mark.asyncio
async def test_coordination_migration_matches_model_and_downgrades(database):
    engine, _, schema = database
    config = bootstrap._get_alembic_config(engine, postgres_schema=schema)
    await asyncio.to_thread(command.upgrade, config, "0055_thread_shares")
    await asyncio.to_thread(command.upgrade, config, "0056_coordination_task_state")
    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(
                sync,
                opts={"compare_type": True, "include_object": lambda _, name, kind, *_args: kind != "table" or name in {"coord_tasks", "coord_inputs"}},
            )
            return compare_metadata(context, Base.metadata)

        assert await conn.run_sync(diff) == []
    repo = CoordinationTaskRepository(async_sessionmaker(engine))
    task = await repo.create("alice", request_id="root", objective="Test the upgraded schema")
    await repo.append_input("alice", task["id"], request_id="update", content="Record an input")
    await asyncio.to_thread(command.downgrade, config, "0055_thread_shares")
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    assert "threads_meta" in tables
    assert not {"coord_tasks", "coord_inputs"} & tables
    await asyncio.to_thread(command.upgrade, config, "0056_coordination_task_state")
    assert (await repo.create("alice", request_id="root", objective="After re-upgrade"))["status"] == TaskStatus.QUEUED

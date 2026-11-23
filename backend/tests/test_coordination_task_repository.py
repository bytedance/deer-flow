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
    assert await repo.replay_input("alice", task_id, request_id="one", content="Check storage") == repeats[0].result()
    with pytest.raises(TaskNotFound):
        await repo.replay_input("bob", task_id, request_id="one", content="Check storage")
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
    previous = "0059_coordination_grants"
    revision = "0060_coordination_run_settings"
    await asyncio.to_thread(command.upgrade, config, "0055_thread_shares")
    await asyncio.to_thread(command.upgrade, config, previous)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO coord_tasks (id, owner_id, request_id, root_id, depends_on, objective, status, revision, execution_epoch, latest_input_seq, created_at, updated_at) "
                "VALUES ('legacy', 'alice', 'root', 'legacy', '[]', 'Test the upgraded schema', 'queued', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    repo = CoordinationTaskRepository(async_sessionmaker(engine))
    await asyncio.to_thread(command.upgrade, config, revision)
    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(
                sync,
                opts={"compare_type": True, "include_object": lambda _, name, kind, *_args: kind != "table" or name in {"coord_tasks", "coord_inputs", "coord_assignments", "coord_executions", "coord_artifacts", "coord_task_grants"}},
            )
            return compare_metadata(context, Base.metadata)

        assert await conn.run_sync(diff) == []
    task = await repo.get("alice", "legacy")
    assert task["status"] == TaskStatus.QUEUED
    assert task["run_settings"] is None
    assert await repo.create("alice", request_id="root", objective=task["objective"], run_settings={}) == task
    await repo.append_input("alice", task["id"], request_id="update", content="Record an input")
    settings = {"recursion_limit": 400, "thinking_enabled": False}
    configured = await repo.create("alice", request_id="configured", objective="Review", run_settings=settings)
    assert (await repo.get("alice", configured["id"]))["run_settings"] == settings

    await asyncio.to_thread(command.downgrade, config, previous)
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda sync: {item["name"] for item in inspect(sync).get_columns("coord_tasks")})
        assert "run_settings" not in columns
        assert await conn.scalar(text("SELECT latest_input_seq FROM coord_tasks WHERE id = 'legacy'")) == 1
    await asyncio.to_thread(command.downgrade, config, "0058_mcp_browser_oauth")
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    assert "mcp_oauth_attempts" in tables
    assert "coord_task_grants" not in tables
    await asyncio.to_thread(command.downgrade, config, "0055_thread_shares")
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    assert "threads_meta" in tables
    assert not {"coord_tasks", "coord_inputs", "coord_assignments", "coord_executions", "coord_artifacts", "coord_task_grants"} & tables
    await asyncio.to_thread(command.upgrade, config, revision)
    assert (await repo.create("alice", request_id="root", objective="After re-upgrade"))["status"] == TaskStatus.QUEUED


@pytest.mark.asyncio
async def test_worker_admission_is_atomic_with_cancellation_and_replay(database):
    from deerflow.persistence.coordination.workers import RUN_KEY_PREFIX, CoordinationWorkerRepository
    from deerflow.persistence.run import RunRepository
    from deerflow.runtime.runs.manager import ConflictError

    engine, dialect, schema = database
    await bootstrap.bootstrap_schema(engine, backend=dialect, postgres_schema=schema)
    sessions = async_sessionmaker(engine)
    workers = CoordinationWorkerRepository(sessions)
    runs = RunRepository(sessions)
    task = await workers.create("alice", request_id="dispatch", objective="Review")
    await workers.append_input("alice", task["id"], request_id="input:follow-up", content="Check the result")
    first, retry = await asyncio.gather(*(workers.prepare("alice", task["id"], "lead_agent") for _ in range(2)))
    assert first == retry
    worker, execution, project = first
    assert project is None
    kwargs = dict(thread_id=worker["thread_id"], owner_worker_id="gateway", user_id="alice", lease_expires_at=None)
    key = RUN_KEY_PREFIX + execution["id"]
    with pytest.raises(ConflictError):
        await runs.create_thread_operation_atomic("unmanaged", **kwargs, idempotency_key="client-key")
    with pytest.raises(TaskNotFound):
        await workers.view("bob", task["id"])
    with pytest.raises(TaskNotFound):
        await workers.list_artifacts("bob", task["id"], limit=1, offset=0)
    with pytest.raises(TaskNotFound):
        await workers.list_worker_inputs("bob", task["id"], after=0, limit=1)
    (pending,) = await workers.list_worker_inputs("alice", task["id"], after=0, limit=1)
    assert (pending["source"], pending["status"], pending["run_id"]) == ("task_api", "pending", None)
    assert await workers.list_artifacts("alice", task["id"], limit=1, offset=0) == []
    current = await workers.get("alice", task["id"])
    admitted, cancelled = await asyncio.gather(
        runs.create_thread_operation_atomic("native", **kwargs, idempotency_key=key),
        workers.request_cancel("alice", task["id"], expected_revision=current["revision"]),
        return_exceptions=True,
    )
    assert cancelled["status"] == TaskStatus.CANCELLING
    with pytest.raises(TaskConflict, match="different worker"):
        await workers.prepare("alice", task["id"], "other_agent")
    stopped = await workers.cancellations("alice", task["id"])
    (receipt,) = await workers.list_worker_inputs("alice", task["id"], after=0, limit=1)
    if isinstance(admitted, ConflictError):
        assert stopped == [] and await runs.get("native", user_id="alice") is None
        assert (receipt["status"], receipt["run_id"]) == ("not_admitted", None)
    else:
        assert not isinstance(admitted, BaseException) and stopped == [(worker["thread_id"], "native")]
        assert (await workers.view("alice", task["id"]))["execution"]["run_id"] == "native"
        assert (receipt["status"], receipt["run_id"]) == ("admitted", "native")
    with pytest.raises(ConflictError):
        await runs.create_thread_operation_atomic("late", **kwargs, idempotency_key=RUN_KEY_PREFIX + uuid4().hex)


@pytest.mark.asyncio
async def test_worker_admission_rechecks_grant_generation_and_session_version(database):
    from time import time

    from deerflow.persistence.coordination.workers import RUN_GRANT_METADATA, RUN_KEY_PREFIX, CoordinationWorkerRepository
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.runtime.runs.manager import ConflictError

    engine, dialect, schema = database
    await bootstrap.bootstrap_schema(engine, backend=dialect, postgres_schema=schema)
    sessions = async_sessionmaker(engine)
    workers, runs = CoordinationWorkerRepository(sessions), RunRepository(sessions)
    async with sessions.begin() as session:
        session.add(UserRow(id="alice", email="alice@example.com"))
    task = await workers.create("alice", request_id="grant", objective="Review")
    grant = {"id": "old", "authority": {"token_version": 0, "source": "session", "permissions": ["runs:create"]}, "channel": None, "expires_at": time() + 100}
    worker, execution, _ = await workers.prepare("alice", task["id"], "lead_agent", initial_grant=grant)
    kwargs = dict(thread_id=worker["thread_id"], user_id="alice", owner_worker_id="worker", lease_expires_at=None, idempotency_key=RUN_KEY_PREFIX + execution["id"])
    async with sessions.begin() as session:
        (await session.get(UserRow, "alice")).token_version = 1
    with pytest.raises(ConflictError, match="authorization"):
        await runs.create_thread_operation_atomic("stale-session", **kwargs, metadata={RUN_GRANT_METADATA: "old"})
    await workers.set_grant("alice", task["id"], {**grant, "id": "new", "authority": {**grant["authority"], "token_version": 1}})
    with pytest.raises(ConflictError, match="authorization"):
        await runs.create_thread_operation_atomic("stale-grant", **kwargs, metadata={RUN_GRANT_METADATA: "old"})
    await runs.create_thread_operation_atomic("authorized", **kwargs, metadata={RUN_GRANT_METADATA: "new"})
    assert (await workers.view("alice", task["id"]))["execution"]["run_id"] == "authorized"
    await workers.append_input("alice", task["id"], request_id="input:next", content="Check the report")
    await workers.settle("alice", task["id"], execution["id"], "authorized", "success", [])
    _, followup, _ = await workers.prepare("alice", task["id"])
    assert followup["turn"] == 2 and followup["run_id"] is None
    assert await workers.prepare("alice", task["id"], "lead_agent") is None
    assert (await workers.prepare("alice", task["id"]))[1] == followup

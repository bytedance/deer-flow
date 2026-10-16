"""Native MCP metadata authority; remote IO is deterministic, not an auth stub."""

import asyncio
from contextvars import Context
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_native_mcp_retains_scope_after_run_and_selection_change(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from app.mcp_tasks.service import McpTaskService
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskSnapshot, TaskStatus, TaskSubmission, TaskSubmitRequest
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import RunManager, RunStatus

    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            workspaces = WorkspaceRepository(sf)
            service = WorkspaceService(workspaces)
            personal = await workspaces.provision_personal("owner")
            team = await workspaces.create_team("owner", "MCP scope", "mcp-scope-main")
            original = await service.resolve_context("owner", team["id"])
            other = await service.resolve_context("owner", personal["id"])
            token = set_current_workspace(original)
            try:
                parent = await ThreadMetaRepository(sf).create("mcp-main", user_id="owner")
                runs = RunManager(store=RunRepository(sf, workspace_required=True), worker_id="mcp-source")
                run = await runs.create_or_reject(parent["thread_id"], user_id="owner")
                await runs.try_start(run.run_id)
                request = TaskSubmitRequest(
                    user_id="owner",
                    thread_id=run.thread_id,
                    thread_incarnation=run.thread_incarnation,
                    run_id=run.run_id,
                    tool_call_id="call-1",
                    server_name="deterministic",
                    task_name="report",
                    arguments={},
                    workspace_context=run.workspace_context,
                    source_worker_id=run.owner_worker_id,
                )
                observed = []

                class RemoteIO:
                    async def submit(self, request):
                        observed.append(("submit", request.workspace_context, get_current_workspace()))
                        return TaskSubmission(remote_task_id="remote-report", snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED))

                    async def get_status(self, reference):
                        observed.append(("status", reference.workspace_context, get_current_workspace()))
                        return TaskSnapshot(status=TaskStatus.COMPLETED, result={"report": "deterministic output"})

                    async def cancel(self, reference):
                        observed.append(("cancel", reference.workspace_context, get_current_workspace()))
                        return TaskSnapshot(status=TaskStatus.CANCELLED)

                registry = McpTaskDriverRegistry()
                registry.register("deterministic", RemoteIO())
                repository = McpTaskRepository(sf, workspace_required=True)
                tasks = McpTaskService(repository=repository, drivers=registry, poll_interval_seconds=1, lease_seconds=120, max_concurrent_polls=1)
                now = datetime.now(UTC)
                created = await tasks.submit(driver_name="deterministic", request=request, now=now)
                async with sf() as session:
                    row = await session.get(McpTaskRow, created["id"])
                    assert row.workspace_id == original.workspace_id and row.workspace_context_json == asdict(original)
                    assert row.run_id == run.run_id and row.thread_incarnation == parent["incarnation"]
                await runs.set_status_if_not_cancelled(run.run_id, RunStatus.success)
                set_current_workspace(other)
                await tasks.run_once(now=now + timedelta(seconds=30))
                assert observed == [("submit", original, original), ("status", original, original)]
                assert get_current_workspace() == other, "background task scope leaked into caller"
                async with sf() as session:
                    row = await session.get(McpTaskRow, created["id"])
                    assert row.workspace_id == original.workspace_id and row.workspace_context_json == asdict(original)
                    assert row.status == "completed" and row.result == {"report": "deterministic output"}
                    assert row.run_id == run.run_id and row.thread_incarnation == parent["incarnation"]
                    assert await session.scalar(sa.select(sa.func.count()).select_from(McpTaskRow).where(McpTaskRow.run_id == run.run_id)) == 1
            finally:
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _in_workspace_case(database_engine, body):
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import RunManager

    with database_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if database_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(database_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            workspaces = WorkspaceRepository(sf)
            service = WorkspaceService(workspaces)
            personal = await workspaces.provision_personal("owner")
            team = await workspaces.create_team("owner", "MCP boundaries", "mcp-boundaries")
            original = await service.resolve_context("owner", team["id"])
            other = await service.resolve_context("owner", personal["id"])
            token = set_current_workspace(original)
            try:
                await body(SimpleNamespace(sf=sf, service=service, team=team, original=original, other=other, runs=RunManager(store=RunRepository(sf, workspace_required=True), worker_id="mcp-boundary-source")))
            finally:
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _source_request(case, name):
    from deerflow.authz.workspace import set_current_workspace
    from deerflow.mcp.tasks import TaskSubmitRequest
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    context = await case.service.resolve_context("owner", case.team["id"])
    set_current_workspace(context)
    parent = await ThreadMetaRepository(case.sf).create(name, user_id="owner")
    run = await case.runs.create_or_reject(name, user_id="owner")
    await case.runs.try_start(run.run_id)
    return TaskSubmitRequest(
        user_id="owner",
        thread_id=name,
        thread_incarnation=parent["incarnation"],
        run_id=run.run_id,
        tool_call_id="call-" + name,
        server_name="deterministic",
        task_name="report",
        arguments={},
        workspace_context=context,
        source_worker_id=run.owner_worker_id,
    )


def _task_service(case, driver):
    from app.mcp_tasks.service import McpTaskService
    from deerflow.mcp.tasks import McpTaskDriverRegistry
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository

    registry = McpTaskDriverRegistry()
    registry.register("deterministic", driver)
    repository = McpTaskRepository(case.sf, workspace_required=True)
    return McpTaskService(repository=repository, drivers=registry, poll_interval_seconds=1, lease_seconds=120, max_concurrent_polls=2), repository


def test_mcp_submission_refuses_lost_source_and_compensates_staged_io(native_engine):  # noqa: F811
    from deerflow.authz.workspace import get_current_workspace
    from deerflow.mcp.tasks import TaskSnapshot, TaskStatus, TaskSubmission
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied

    async def scenario(case):
        for phase in ("before-policy", "before-nonce", "before-owner", "before-cancel", "during-policy", "during-owner"):
            request = await _source_request(case, phase)
            calls = []

            async def withdraw():
                async with case.sf() as session:
                    if phase.endswith("policy"):
                        await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": request.workspace_context.workspace_id})
                    elif phase.endswith("nonce"):
                        await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": "b" * 32, "id": request.thread_id})
                    elif phase.endswith("owner"):
                        await session.execute(sa.text("UPDATE runs SET owner_worker_id='replacement-worker' WHERE run_id=:id"), {"id": request.run_id})
                    else:
                        await session.execute(sa.text("UPDATE runs SET cancel_action='interrupt' WHERE run_id=:id"), {"id": request.run_id})
                    await session.commit()

            class RemoteIO:
                async def submit(self, submitted):
                    calls.append(("submit", submitted.workspace_context, get_current_workspace()))
                    if phase.startswith("during"):
                        await withdraw()
                    return TaskSubmission(remote_task_id="remote-" + phase, snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED))

                async def cancel(self, reference):
                    calls.append(("cancel", reference.workspace_context, get_current_workspace()))
                    return TaskSnapshot(status=TaskStatus.CANCELLED)

            tasks, _ = _task_service(case, RemoteIO())
            if phase.startswith("before"):
                await withdraw()
            with pytest.raises(WorkspaceAccessDenied):
                await tasks.submit(driver_name="deterministic", request=request)
            assert calls == ([] if phase.startswith("before") else [("submit", request.workspace_context, request.workspace_context), ("cancel", request.workspace_context, request.workspace_context)])
            async with case.sf() as session:
                assert await session.scalar(sa.select(sa.func.count()).select_from(McpTaskRow).where(McpTaskRow.run_id == request.run_id)) == 0

    _in_workspace_case(native_engine, scenario)


def test_mcp_foreign_reads_and_revoked_poll_never_publish_result(native_engine):  # noqa: F811
    from deerflow.authz.workspace import get_current_workspace, set_current_workspace
    from deerflow.mcp.tasks import TaskSnapshot, TaskStatus, TaskSubmission
    from deerflow.persistence.mcp_tasks.model import McpTaskRow

    async def scenario(case):
        for phase in ("before-poll", "during-poll"):
            request = await _source_request(case, phase)
            observed = []

            async def withdraw():
                async with case.sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": request.workspace_context.workspace_id})
                    await session.commit()

            class RemoteIO:
                async def submit(self, submitted):
                    return TaskSubmission(remote_task_id="remote-" + phase, snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED))

                async def get_status(self, reference):
                    observed.append((reference.workspace_context, get_current_workspace()))
                    if phase == "during-poll":
                        await withdraw()
                    return TaskSnapshot(status=TaskStatus.COMPLETED, result={"private": "must-not-publish"})

            tasks, repository = _task_service(case, RemoteIO())
            now = datetime.now(UTC)
            created = await tasks.submit(driver_name="deterministic", request=request, now=now)
            set_current_workspace(case.other)
            assert await repository.get(created["id"], user_id="owner", thread_id=request.thread_id, thread_incarnation=request.thread_incarnation) is None
            assert await repository.list_by_run(request.run_id, user_id="owner", thread_id=request.thread_id, thread_incarnation=request.thread_incarnation) == []
            assert await repository.list_by_thread(request.thread_id, user_id="owner", thread_incarnation=request.thread_incarnation, limit=1) == [], "foreign MCP task leaked through limited thread projection"
            if phase == "before-poll":
                await withdraw()
            await tasks.run_once(now=now + timedelta(seconds=30))
            assert observed == ([] if phase == "before-poll" else [(request.workspace_context, request.workspace_context)])
            assert get_current_workspace() == case.other
            async with case.sf() as session:
                row = await session.get(McpTaskRow, created["id"])
                assert row.status == "submitted" and row.result is None and row.completed_at is None
                assert row.workspace_context_json == asdict(request.workspace_context) and row.workspace_id == request.workspace_context.workspace_id
                assert row.run_id == request.run_id and row.thread_incarnation == request.thread_incarnation
        async with case.sf() as session:
            session.add(
                McpTaskRow(
                    id="unattributed-task",
                    user_id="owner",
                    thread_id="legacy-unbound",
                    run_id=None,
                    server_name="deterministic",
                    driver_name="deterministic",
                    remote_task_id="legacy-remote",
                    task_name="legacy",
                    status="submitted",
                    next_poll_at=datetime.now(UTC) - timedelta(seconds=1),
                    event_version=1,
                    notification_status="pending",
                )
            )
            await session.commit()
        before_calls = list(observed)
        await asyncio.create_task(tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=30)), context=Context())
        assert observed == before_calls, "mandatory workspace worker called an unattributed legacy task"
        assert await repository.claim_notification_work(now=datetime.now(UTC), lease_owner="test", lease_seconds=120, limit=10, tracking_degraded_after_errors=3) == []
        assert await repository.claim_cancel_requests(now=datetime.now(UTC), lease_owner="test", lease_seconds=120, limit=10) == []
        async with case.sf() as session:
            legacy = await session.get(McpTaskRow, "unattributed-task")
            assert legacy.lease_owner is None and legacy.notification_lease_owner is None and legacy.result is None

    _in_workspace_case(native_engine, scenario)


def test_mcp_identity_migration_preserves_history_without_creating_authority(native_engine):  # noqa: F811
    from alembic import command

    from deerflow.persistence import bootstrap
    from deerflow.persistence.mcp_tasks.model import McpTaskRow

    columns = "id,user_id,thread_id,run_id,remote_task_id,status,workspace_id,lease_owner,lease_token,CAST(driver_data AS TEXT),CAST(result AS TEXT)"
    with native_engine.begin() as conn:
        conn.execute(
            sa.insert(McpTaskRow).values(
                id="old-mcp",
                user_id="owner",
                thread_id="thread",
                run_id="run",
                thread_incarnation="epoch",
                server_name="server",
                driver_name="ordinary",
                remote_task_id="old-remote",
                task_name="report",
                status="working",
                lease_owner="old-worker",
                lease_token="old-token",
                driver_data={"status_tool": "status"},
                result={"existing": "preserved"},
            )
        )
        before = conn.execute(sa.text("SELECT " + columns + " FROM mcp_tasks ORDER BY id")).all()
        conn.execute(sa.text("ALTER TABLE mcp_tasks DROP COLUMN workspace_context_json"))
        conn.execute(sa.text("UPDATE alembic_version SET version_num='0039_run_workspace_identity'"))
        assert "workspace_context_json" not in {c["name"] for c in sa.inspect(conn).get_columns("mcp_tasks")}
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def configuration():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            return bootstrap._get_alembic_config(engine)
        finally:
            await engine.dispose()

    cfg = asyncio.run(configuration())
    for _ in range(2):
        bootstrap._upgrade(cfg, "head")
        with native_engine.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0040_mcp_workspace_identity"
            assert conn.execute(sa.text("SELECT " + columns + " FROM mcp_tasks ORDER BY id")).all() == before
            column = next(c for c in sa.inspect(conn).get_columns("mcp_tasks") if c["name"] == "workspace_context_json")
            assert column["nullable"] and isinstance(column["type"], sa.JSON)
            assert conn.execute(sa.text("SELECT COUNT(*) FROM mcp_tasks WHERE workspace_context_json IS NOT NULL")).scalar_one() == 0
    with pytest.raises(RuntimeError, match="matched backup"):
        command.downgrade(cfg, "0039_run_workspace_identity")
    with native_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0040_mcp_workspace_identity"
        assert conn.execute(sa.text("SELECT " + columns + " FROM mcp_tasks ORDER BY id")).all() == before
        if native_engine.dialect.name == "postgresql":
            assert conn.execute(sa.text("SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()")).scalar_one() == 0

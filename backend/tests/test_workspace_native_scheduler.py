"""One PostgreSQL Scheduler occurrence through native C admission and completion.

The graph is deterministic and uses no sandbox. This verifies original identity,
queue/launch/completion and origin history, not IM or physical B execution.
"""

import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
@pytest.mark.parametrize("boundary", ["normal", "queued_member", "launch_lease"])
def test_scoped_scheduler_occurrence_keeps_original_workspace(native_engine, executor_engine, monkeypatch, tmp_path, boundary):  # noqa: F811
    from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost, install_native_dispatch
    from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import SCHEMA_REVISION, upgrade_schema
    from fastapi import FastAPI
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from sqlalchemy import select, text, update

    from app.gateway import deps, services
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.scheduler.service import ScheduledTaskService
    from deerflow.agents.thread_state import ThreadState
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config import paths as paths_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import Paths
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.scheduled_task_events.model import ScheduledTaskEventRow
    from deerflow.persistence.scheduled_task_events.sql import ScheduledTaskEventRepository
    from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
    from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
    from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    assert native_engine.dialect.name == executor_engine.dialect.name == "postgresql"
    upgrade_schema(executor_engine)
    ledger = JobStore(executor_engine.url.render_as_string(hide_password=False))

    def ledger_snapshot():
        with ledger.engine.connect() as connection:
            return deepcopy([dict(row) for row in connection.execute(text("SELECT * FROM ecs_execution_jobs ORDER BY id")).mappings()])

    initial_jobs = ledger_snapshot()
    owner_user_id = "11111111-1111-4111-8111-111111111111"
    configuration = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    monkeypatch.setattr(services, "get_app_config", lambda: configuration)
    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "owned-files"))

    async def scenario(case):
        async def native_snapshot(session, row_type):
            table = row_type.__table__
            rows = (await session.execute(select(*table.c).order_by(*table.primary_key.columns))).mappings().all()
            return deepcopy([dict(row) for row in rows])

        async with case.sf() as session:
            initial_runs = await native_snapshot(session, RunRow)
            initial_events = await native_snapshot(session, ScheduledTaskEventRow)
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        origin = await threads.create("native-scheduler-origin", user_id=owner_user_id)
        run_store = RunRepository(case.sf, workspace_required=True)
        # Use the existing create API for RED: a real bound create must not
        # silently persist a NULL workspace. No new keyword can fail first.
        initial_repo = ScheduledTaskRepository(case.sf, run_repository=run_store)
        now = datetime.now(UTC)
        created = await initial_repo.create(
            task_id="native-scheduler-research",
            user_id=owner_user_id,
            thread_id=None,
            origin_thread_id=origin["thread_id"],
            context_mode="fresh_thread_per_run",
            assistant_id=None,
            title="Follow up private research",
            prompt="Deliver the private research update",
            schedule_type="once",
            schedule_spec={"run_at": now.isoformat()},
            timezone="UTC",
            next_run_at=now,
        )
        async with case.sf() as session:
            stored = await session.get(ScheduledTaskRow, created["id"])
            assert stored.workspace_id == case.original.workspace_id, "Bound Scheduler create lost its original workspace"
            assert stored.workspace_context_json == asdict(case.original)
            assert stored.origin_thread_incarnation == origin["incarnation"]
        tasks = ScheduledTaskRepository(case.sf, run_repository=run_store, workspace_required=True)
        occurrences = ScheduledTaskRunRepository(case.sf, run_repository=run_store, workspace_required=True)
        history = ScheduledTaskEventRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120)
        central = RunManager(run_store, worker_id="scheduler-central", run_ownership_config=ownership)
        receiver = RunManager(run_store, worker_id="scheduler-worker", run_ownership_config=ownership)
        user_repo = SQLiteUserRepository(case.sf)
        monkeypatch.setattr(deps, "_cached_repo", user_repo)
        monkeypatch.setattr(deps, "_cached_local_provider", LocalAuthProvider(user_repo))
        principal_token = set_current_user(await deps.get_local_provider().get_user(owner_user_id))
        saver = MemorySaver()
        central_app, worker_app = FastAPI(), FastAPI()
        events = DbRunEventStore(case.sf, workspace_required=True)
        for app, manager in ((central_app, central), (worker_app, receiver)):
            app.state.run_manager, app.state.run_store = manager, run_store
            app.state.thread_store = threads
            app.state.mcp_task_repo = McpTaskRepository(case.sf, workspace_required=True)
            app.state.stream_bridge, app.state.checkpointer, app.state.store = MemoryStreamBridge(), saver, None
            app.state.run_event_store = events
            app.state.project_repo = ProjectRepository(case.sf, workspace_required=True)
            app.state.project_document_repo = ProjectDocumentRepository(case.sf, workspace_required=True)
            app.state.scheduled_task_repo, app.state.scheduled_task_run_repo, app.state.scheduled_task_event_repo = tasks, occurrences, history
        node = Node(cpu_millis=4000, memory_mib=8192, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report"}, kinds={"C"})
        pool = Scheduling(ledger, nodes={"worker": node})
        secret = "native-scheduler-offline-fixture-32-bytes"
        config = {"artifact_root": str(tmp_path / "scheduler-pool"), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}
        dispatcher = NativeDispatchHost(central_app, pool, config, {"worker": secret})
        central_app.state.native_run_admission_host = dispatcher
        install_native_dispatch(central_app, dispatcher)
        host = NativeWorkerHost.__new__(NativeWorkerHost)
        host.app, host.secret, host.adoption_lock, host.config = worker_app, secret, asyncio.Lock(), {"node_id": "worker"}
        host.executions, host.stop_tasks, host.sandbox_captures = {}, {}, {}

        async def request_worker(operation, **values):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=central_app), base_url="http://native-scheduler-fixture") as client:
                response = await client.post(
                    f"/api/native-workers/worker/{operation}",
                    headers={"Authorization": "Bearer " + secret},
                    json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": dispatcher.mount_id, "owner": "scheduler-owner", **values},
                )
                response.raise_for_status()
                return response.json()

        host.request = request_worker
        worker_app.state.native_run_admission_host = host

        async def launch(**kwargs):
            return await services.launch_scheduled_thread_run(app=central_app, **kwargs)

        foreground = ScheduledTaskService(
            task_repo=tasks, task_run_repo=occurrences, launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, multi_instance=True, dispatch_enabled=False, own_stop_available=False
        )
        control = ScheduledTaskService(task_repo=tasks, task_run_repo=occurrences, launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, multi_instance=True, own_stop_available=False)
        for app in (central_app, worker_app):
            app.state.scheduled_task_service = foreground
        ctx = RunContext(checkpointer=saver, thread_store=threads, event_store=events, app_config=configuration, on_run_completed=control.handle_run_completion)
        monkeypatch.setattr(services, "get_run_context", lambda request: ctx)
        executed = []

        async def respond(state, config):
            assert get_current_workspace() == case.original
            executed.append(config["configurable"]["thread_id"])
            return {"messages": [AIMessage(content="The private research update is complete")]}

        builder = StateGraph(ThreadState, context_schema=dict)
        builder.add_node("answer", respond)
        builder.add_edge(START, "answer")
        builder.add_edge("answer", END)
        graph = builder.compile(checkpointer=saver)
        monkeypatch.setattr(services, "resolve_agent_factory", lambda assistant_id: lambda **kwargs: graph)
        lease_injections = []
        admission_errors = []
        original_create = run_store.create_thread_operation_atomic

        async def change_lease_before_atomic_create(*args, **kwargs):
            receipt = kwargs.get("scheduled_admission")
            assert receipt is not None
            assert not lease_injections, "Repeat drain replayed the stale launch"
            successor_expiry = datetime.now(UTC) + timedelta(seconds=300)
            async with case.sf() as session, session.begin():
                occurrence = await session.get(ScheduledTaskRunRow, receipt.occurrence_id)
                assert occurrence.status == "launching" and occurrence.run_id is None
                assert occurrence.lease_owner == receipt.lease_owner and occurrence.attempt_count == receipt.attempt_count
                occurrence.lease_owner = "scheduler-successor"
                occurrence.attempt_count = receipt.attempt_count + 1
                occurrence.lease_expires_at = successor_expiry
            lease_injections.append((receipt.occurrence_id, receipt.attempt_count + 1, successor_expiry))
            try:
                # The real launcher preflight has completed; keep the original
                # SQL admission and its permission/lease checks intact.
                return await original_create(*args, **kwargs)
            except Exception as exc:
                admission_errors.append((type(exc), str(exc)[:160]))
                raise

        if boundary == "launch_lease":
            monkeypatch.setattr(run_store, "create_thread_operation_atomic", change_lease_before_atomic_create)
        adopted = None
        selected = None
        try:
            await foreground.start()
            due = await tasks.claim_due_tasks(now=now, lease_owner=foreground._lease_owner, lease_seconds=120, limit=1)
            assert len(due) == 1
            queued = await foreground.dispatch_task(due[0], now=now, trigger="scheduled")
            assert queued["outcome"] == "queued"
            async with case.sf() as session:
                occurrence = await session.get(ScheduledTaskRunRow, queued["task_run_id"])
                assert occurrence.status == "queued" and occurrence.workspace_id == case.original.workspace_id
                assert occurrence.workspace_context_json == asdict(case.original)
            if boundary == "queued_member":
                async with case.sf() as session, session.begin():
                    changed = await session.execute(
                        update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == owner_user_id).values(version=WorkspaceMembershipRow.version + 1)
                    )
                    assert changed.rowcount == 1
            selected = set_current_workspace(case.other)
            await control.run_once(now=now)
            if boundary != "normal":
                await control.run_once(now=datetime.now(UTC))
                # Independent SQL checks remain valid after revocation; no
                # business repository read can accidentally restore authority.
                async with case.sf() as session:
                    occurrence = await session.get(ScheduledTaskRunRow, queued["task_run_id"])
                    stored = await session.get(ScheduledTaskRow, created["id"])
                    assert await native_snapshot(session, RunRow) == initial_runs
                    assert await native_snapshot(session, ScheduledTaskEventRow) == initial_events
                    assert occurrence.run_id is None and stored.last_run_id is None and stored.run_count == 0
                    assert occurrence.workspace_context_json == asdict(case.original)
                    assert occurrence.thread_incarnation is not None
                    if boundary == "queued_member":
                        assert occurrence.status == "queued" and occurrence.attempt_count == 0
                        assert not lease_injections and not admission_errors
                    else:
                        assert len(lease_injections) == len(admission_errors) == 1
                        assert admission_errors[0][0] is WorkspaceAccessDenied, admission_errors
                        assert "Scheduler launch lease changed" in admission_errors[0][1], admission_errors
                        occurrence_id, attempt, expiry = lease_injections[0]
                        assert occurrence.id == occurrence_id and occurrence.status == "launching"
                        assert occurrence.lease_owner == "scheduler-successor" and occurrence.attempt_count == attempt
                        assert occurrence.lease_expires_at == expiry and expiry > datetime.now(UTC)

                assert await asyncio.to_thread(ledger_snapshot) == initial_jobs
                assert not executed and not host.executions and not host.sandbox_captures
                assert get_current_workspace() == case.other
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                return
            envelope = (await request_worker("poll"))["claim"]
            assert envelope is not None, "Scheduler did not launch its original native occurrence"
            job = await host.report(envelope["job"], {"start_intent": True})
            adopted = await host.adopt_owned(job, envelope["capability"])
            host.executions[job["id"]] = (job, adopted)
            await host.report(job, {"state": "running"})
            await asyncio.wait_for(adopted.task, timeout=20)
            assert adopted.status.value == "success" and not adopted.workspace_cleanup_uncertain, adopted.error
            await host.stop_owned(job)
            await host.report(job, {"state": "completed", "physical_stopped": True})
            host.executions.pop(job["id"])
            for _ in range(2):
                await control.run_once(now=datetime.now(UTC))
            async with case.sf() as session:
                stored = await session.get(ScheduledTaskRow, created["id"])
                occurrence = await session.get(ScheduledTaskRunRow, queued["task_run_id"])
                run = await session.get(RunRow, adopted.run_id)
                execution_thread = await session.get(ThreadMetaRow, adopted.thread_id)
                origin_events = (await session.scalars(select(ScheduledTaskEventRow).where(ScheduledTaskEventRow.task_id == created["id"]))).all()
                assert stored.status == "completed" and stored.run_count == 1
                assert occurrence.status == "success" and occurrence.run_id == adopted.run_id
                assert occurrence.workspace_context_json == run.workspace_context_json == asdict(case.original)
                assert occurrence.thread_incarnation == run.thread_incarnation == execution_thread.incarnation
                assert execution_thread.workspace_id == case.original.workspace_id and adopted.thread_id != origin["thread_id"]
                assert run.status == "success" and run.user_id == owner_user_id
                assert len(origin_events) == 1 and origin_events[0].event == "task_finished"
                assert origin_events[0].workspace_id == case.original.workspace_id and origin_events[0].thread_id == origin["thread_id"]
                assert origin_events[0].thread_incarnation == origin["incarnation"]
                assert len((await session.scalars(select(RunRow).where(RunRow.workspace_id == case.original.workspace_id))).all()) == 1
            assert executed == [adopted.thread_id]
            assert get_current_workspace() == case.other
            assert (await request_worker("poll"))["claim"] is None
            assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
        finally:
            if adopted is not None and adopted.task is not None and not adopted.task.done():
                adopted.task.cancel()
                try:
                    await adopted.task
                except asyncio.CancelledError:
                    pass
            if selected is not None:
                reset_current_workspace(selected)
            await foreground.stop()
            await control.stop()
            await central.stop_heartbeat()
            await receiver.stop_heartbeat()
            reset_current_user(principal_token)

    try:
        _in_workspace_case(native_engine, scenario, owner_user_id=owner_user_id)
    finally:
        ledger.engine.dispose()

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
    _exercise_scoped_scheduler_occurrence(native_engine, executor_engine, monkeypatch, tmp_path, boundary=boundary)


def _exercise_scoped_scheduler_occurrence(native_engine, executor_engine, monkeypatch, tmp_path, *, boundary="normal", after_completion=None):  # noqa: F811
    from types import SimpleNamespace

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

        model = None
        if after_completion is not None:
            from langchain_core.language_models.chat_models import BaseChatModel
            from langchain_core.outputs import ChatGeneration, ChatResult

            class DeterministicHistoryModel(BaseChatModel):
                @property
                def _llm_type(self):
                    return "deterministic-scheduler-history"

                def _generate(self, *args, **kwargs):
                    raise AssertionError("The native Scheduler main is asynchronous")

                async def _agenerate(self, *args, **kwargs):
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content="The private research update is complete", usage_metadata={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12}))])

            model = DeterministicHistoryModel()

        async def respond(state, config):
            assert get_current_workspace() == case.original
            executed.append(config["configurable"]["thread_id"])
            message = await model.ainvoke(state["messages"], config=config) if model is not None else AIMessage(content="The private research update is complete")
            return {"messages": [message]}

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
            if after_completion is not None:
                await after_completion(
                    SimpleNamespace(
                        case=case, tasks=tasks, occurrences=occurrences, threads=threads, service=foreground, task_id=created["id"], occurrence_id=queued["task_run_id"], record=adopted, origin=origin, configuration=configuration
                    )
                )
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


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduler_http_create_list_detail_use_current_resource_scope(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    from fastapi import FastAPI
    from sqlalchemy import select, update

    import deerflow.config as config_facade
    from app.gateway import deps
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import create_access_token
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.csrf_middleware import CSRFMiddleware
    from app.gateway.routers import scheduled_tasks
    from app.scheduler.service import ScheduledTaskService
    from deerflow.authz.workspace import get_current_workspace
    from deerflow.config import app_config
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
    from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow

    assert native_engine.dialect.name == executor_engine.dialect.name == "postgresql"
    owner = "11111111-1111-4111-8111-111111111111"
    configuration = AppConfig.model_validate(
        {
            "models": [],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "scheduler": {"enabled": True},
            "authorization": {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"routes": {"allow": "*"}}}}}},
        }
    )
    monkeypatch.setattr(config_facade, "get_app_config", lambda: configuration)
    monkeypatch.setattr(app_config, "get_app_config", lambda: configuration)
    monkeypatch.setattr(deps, "get_app_config", lambda: configuration)
    monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="synthetic-scheduler-resource-http-key-64-characters-for-test-only!!"))
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        parent = await threads.create("scheduler-resource-parent", user_id=owner)
        users = SQLiteUserRepository(case.sf)
        monkeypatch.setattr(deps, "_cached_repo", users)
        monkeypatch.setattr(deps, "_cached_local_provider", LocalAuthProvider(repository=users))
        runs = RunRepository(case.sf, workspace_required=True)
        tasks = ScheduledTaskRepository(case.sf, run_repository=runs, workspace_required=True)
        occurrences = ScheduledTaskRunRepository(case.sf, run_repository=runs, workspace_required=True)

        async def no_launch(**kwargs):
            raise AssertionError("Resource requests must not dispatch native execution")

        foreground = ScheduledTaskService(
            task_repo=tasks, task_run_repo=occurrences, launch_run=no_launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, dispatch_enabled=False, multi_instance=True, own_stop_available=False
        )
        app = FastAPI()
        app.state.workspace_service = case.service
        app.state.scheduled_task_repo, app.state.scheduled_task_run_repo = tasks, occurrences
        app.state.scheduled_task_service, app.state.thread_store = foreground, threads
        app.include_router(scheduled_tasks.router)
        app.add_middleware(AuthMiddleware)
        app.add_middleware(CSRFMiddleware)
        await foreground.start()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"Origin": "http://localhost", "X-CSRF-Token": "synthetic-scheduler-csrf"}) as client:
                client.cookies.set("access_token", create_access_token(owner))
                client.cookies.set("csrf_token", "synthetic-scheduler-csrf")
                selected = {"X-Deerflow-Workspace": case.original.workspace_id}
                response = await client.post(
                    "/api/scheduled-tasks",
                    headers=selected,
                    json={
                        "thread_id": parent["thread_id"],
                        "context_mode": "reuse_thread",
                        "title": "Original private follow-up",
                        "prompt": "Prepare the private follow-up",
                        "schedule_type": "once",
                        "schedule_spec": {"run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
                        "timezone": "UTC",
                    },
                )
                assert response.status_code == 200, response.text
                created = response.json()
                task_id = created["id"]
                assert created["active_run_status"] is None and created["automatic_runs_used"] == 0
                async with case.sf() as session:
                    task = await session.get(ScheduledTaskRow, task_id)
                    original_snapshot = dict(task.workspace_context_json)
                    assert original_snapshot == asdict(case.original) and task.thread_incarnation == parent["incarnation"]
                # Use the actual due-claim/foreground path to persist a queued
                # occurrence; no control poller or native Run is started.
                queue_at = datetime.now(UTC) + timedelta(hours=2)
                due = await tasks.claim_due_tasks(now=queue_at, lease_owner=foreground._lease_owner, lease_seconds=120, limit=1)
                assert len(due) == 1 and due[0]["id"] == task_id
                queued = await foreground.dispatch_task(due[0], now=queue_at, trigger="scheduled")
                assert queued["outcome"] == "queued" and queued["run_id"] is None
                for _ in range(2):
                    listed = await client.get("/api/scheduled-tasks", headers=selected)
                    detail = await client.get("/api/scheduled-tasks/" + task_id, headers=selected)
                    assert listed.status_code == detail.status_code == 200
                    assert [item["id"] for item in listed.json()] == [task_id]
                    assert detail.json()["id"] == task_id and detail.json()["automatic_runs_used"] == 0
                    assert detail.json()["active_run_status"] == listed.json()[0]["active_run_status"] == "queued"
                    assert listed.json()[0]["automatic_runs_used"] == 0
                    async with case.sf() as session, session.begin():
                        await session.execute(
                            update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == owner).values(version=WorkspaceMembershipRow.version + 1)
                        )
                other = {"X-Deerflow-Workspace": case.other.workspace_id}
                listed = await client.get("/api/scheduled-tasks", headers=other)
                hidden = await client.get("/api/scheduled-tasks/" + task_id, headers=other)
                assert listed.status_code == 200 and listed.json() == []
                assert hidden.status_code == 404
                assert (await client.get("/api/scheduled-tasks/" + task_id, headers=selected)).status_code == 200
                async with case.sf() as session:
                    stored = await session.get(ScheduledTaskRow, task_id)
                    assert stored.workspace_context_json == original_snapshot and stored.thread_incarnation == parent["incarnation"]
                    assert stored.run_count == 0 and stored.last_run_id is None
                    assert len((await session.scalars(select(ScheduledTaskRow).where(ScheduledTaskRow.workspace_id == case.original.workspace_id))).all()) == 1
                assert get_current_workspace() == case.original
        finally:
            await foreground.stop()

    _in_workspace_case(native_engine, scenario, owner_user_id=owner)


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduler_http_history_and_thread_relations_keep_private_run(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    from fastapi import FastAPI
    from sqlalchemy import update

    import deerflow.config as config_facade
    from app.gateway import deps
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import create_access_token
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.csrf_middleware import CSRFMiddleware
    from app.gateway.routers import scheduled_tasks
    from deerflow.authz.workspace import get_current_workspace
    from deerflow.config import app_config
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow

    async def read_completed(main):
        case = main.case
        owner = case.original.actor_user_id
        configuration = AppConfig.model_validate(
            {**main.configuration.model_dump(), "authorization": {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"routes": {"allow": "*"}}}}}}}
        )
        monkeypatch.setattr(config_facade, "get_app_config", lambda: configuration)
        monkeypatch.setattr(app_config, "get_app_config", lambda: configuration)
        monkeypatch.setattr(deps, "get_app_config", lambda: configuration)
        monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="synthetic-scheduler-history-key-64-characters-for-test-only!!"))
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
        app = FastAPI()
        app.state.workspace_service = case.service
        app.state.thread_store, app.state.scheduled_task_service = main.threads, main.service
        app.state.scheduled_task_repo, app.state.scheduled_task_run_repo = main.tasks, main.occurrences
        app.include_router(scheduled_tasks.router)
        app.add_middleware(AuthMiddleware)
        app.add_middleware(CSRFMiddleware)
        async with case.sf() as session, session.begin():
            run = await session.get(RunRow, main.record.run_id)
            assert run.status == "success" and run.total_tokens == 12
            assert run.last_ai_message == "The private research update is complete"
            # A hidden history row sorts first and precedes the real sequence.
            # Its legacy/foreign private parent must affect neither page nor number.
            session.add(
                ScheduledTaskRunRow(
                    id="hidden-history-row",
                    task_id=main.task_id,
                    occurrence_seq=0,
                    launch_accounted=True,
                    thread_id="thread",
                    thread_incarnation="epoch",
                    run_id="foreign-run",
                    scheduled_for=datetime.now(UTC),
                    trigger="scheduled",
                    status="success",
                    workspace_id=case.original.workspace_id,
                    workspace_context_json=asdict(case.original),
                    created_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        selected = {"X-Deerflow-Workspace": case.original.workspace_id}
        history_path = "/api/scheduled-tasks/" + main.task_id + "/runs?limit=1"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"Origin": "http://localhost", "X-CSRF-Token": "synthetic-history-csrf"}) as client:
            client.cookies.set("access_token", create_access_token(owner))
            client.cookies.set("csrf_token", "synthetic-history-csrf")

            async def read_views():
                response = await client.get(history_path, headers=selected)
                assert response.status_code == 200, response.text
                history = response.json()
                assert len(history) == 1 and history[0]["id"] == main.occurrence_id
                assert history[0]["run_number"] == 1 and history[0]["total_tokens"] == 12
                assert history[0]["summary"] == "The private research update is complete"
                assert (await client.get(history_path + "&offset=1", headers=selected)).json() == []
                for thread_id, relation in ((main.origin["thread_id"], "origin"), (main.record.thread_id, "run")):
                    response = await client.get("/api/threads/" + thread_id + "/scheduled-tasks", headers=selected)
                    assert response.status_code == 200, response.text
                    tasks = response.json()
                    assert len(tasks) == 1 and tasks[0]["id"] == main.task_id and tasks[0]["thread_relation"] == relation
                    assert tasks[0]["automatic_runs_used"] == 1
                    if relation == "run":
                        assert tasks[0]["thread_run"]["run_number"] == 1

            await read_views()
            async with case.sf() as session, session.begin():
                await session.execute(update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == owner).values(version=WorkspaceMembershipRow.version + 1))
            await read_views()
            foreign_saved = None
            try:
                async with case.sf() as session, session.begin():
                    foreign = await session.get(RunRow, "foreign-run")
                    foreign_saved = (foreign.last_ai_message, foreign.total_tokens)
                    # Explicit denied-data sentinel, never a model execution
                    # result. Restore the pre-existing fixture values exactly.
                    foreign.last_ai_message, foreign.total_tokens = "FOREIGN-HISTORY-DENIED-SENTINEL", 987654
                    await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == main.occurrence_id).values(run_id="foreign-run"))
                response = await client.get(history_path, headers=selected)
                assert response.status_code == 200
                history = response.json()
                assert len(history) == 1 and history[0]["id"] == main.occurrence_id
                assert history[0]["summary"] is None and history[0]["total_tokens"] is None
                assert "FOREIGN-HISTORY-DENIED-SENTINEL" not in response.text and "987654" not in response.text
            finally:
                async with case.sf() as session, session.begin():
                    await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == main.occurrence_id).values(run_id=main.record.run_id))
                    if foreign_saved is not None:
                        foreign = await session.get(RunRow, "foreign-run")
                        foreign.last_ai_message, foreign.total_tokens = foreign_saved
            other = {"X-Deerflow-Workspace": case.other.workspace_id}
            assert (await client.get(history_path, headers=other)).status_code == 404
            assert (await client.get("/api/threads/" + main.origin["thread_id"] + "/scheduled-tasks", headers=other)).status_code == 404
            assert (await client.get("/api/threads/" + main.record.thread_id + "/scheduled-tasks", headers=other)).status_code == 404
            await read_views()
        async with case.sf() as session:
            task = await session.get(ScheduledTaskRow, main.task_id)
            occurrence = await session.get(ScheduledTaskRunRow, main.occurrence_id)
            assert task.workspace_context_json == occurrence.workspace_context_json == asdict(case.original)
            assert occurrence.run_id == main.record.run_id and occurrence.status == "success"
            foreign = await session.get(RunRow, "foreign-run")
            assert (foreign.last_ai_message, foreign.total_tokens) == foreign_saved
        assert get_current_workspace() == case.other

    _exercise_scoped_scheduler_occurrence(native_engine, executor_engine, monkeypatch, tmp_path, after_completion=read_completed)


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduler_tool_list_uses_original_native_invocation(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    _exercise_scheduler_tool_list(native_engine, executor_engine, monkeypatch, tmp_path)


def _exercise_scheduler_tool_list(native_engine, executor_engine, monkeypatch, tmp_path, *, remote=False, boundary="normal"):  # noqa: F811
    import json

    from fastapi import FastAPI
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode
    from langgraph.runtime import Runtime as GraphRuntime
    from sqlalchemy import select

    import deerflow.config as config_facade
    from app.gateway import deps, scheduled_task_access, services
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import create_access_token
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.csrf_middleware import CSRFMiddleware
    from app.gateway.routers import scheduled_tasks, thread_runs
    from app.scheduler.service import ScheduledTaskService
    from deerflow.agents.thread_state import ThreadState
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config import app_config
    from deerflow.config import paths as paths_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import Paths
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
    from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.invocation import WorkerInvocationDenied, get_invocation_guard
    from deerflow.scheduler.runtime import SCHEDULER_CAPABILITY_CONTEXT_KEY, is_scheduler_capability, scheduler_tools_enabled
    from deerflow.tools.scheduled_tasks import schedule_task

    assert native_engine.dialect.name == executor_engine.dialect.name == "postgresql"
    owner = "11111111-1111-4111-8111-111111111111"
    configuration = AppConfig.model_validate(
        {
            "models": [],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "memory": {"enabled": False},
            "scheduler": {"enabled": True, "tool_enabled": True},
            "authorization": {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"routes": {"allow": "*"}}}}}},
        }
    )
    for module in (config_facade, app_config, deps, services):
        monkeypatch.setattr(module, "get_app_config", lambda: configuration)
    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "tool-list-files"))
    monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="synthetic-native-scheduler-tool-list-key-64-characters-for-test!!"))
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

    ledger = None
    if remote:
        from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost, install_native_dispatch
        from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
        from ecs_executor.job_store import JobStore
        from ecs_executor.nodes import Node
        from ecs_executor.scheduling import Scheduling
        from ecs_executor.schema import SCHEMA_REVISION, upgrade_schema

        upgrade_schema(executor_engine)
        ledger = JobStore(executor_engine.url.render_as_string(hide_password=False))

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        origin = await threads.create("scheduler-tool-origin", user_id=owner)
        other_token = set_current_workspace(case.other)
        try:
            other_parent = await threads.create("scheduler-tool-other", user_id=owner)
        finally:
            reset_current_workspace(other_token)
        users = SQLiteUserRepository(case.sf)
        monkeypatch.setattr(deps, "_cached_repo", users)
        monkeypatch.setattr(deps, "_cached_local_provider", LocalAuthProvider(repository=users))
        store = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store, worker_id="scheduler-tool-worker", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        tasks = ScheduledTaskRepository(case.sf, run_repository=store, workspace_required=True)
        occurrences = ScheduledTaskRunRepository(case.sf, run_repository=store, workspace_required=True)
        events, saver = DbRunEventStore(case.sf, workspace_required=True), MemorySaver()
        ctx = RunContext(checkpointer=saver, thread_store=threads, event_store=events, app_config=configuration)
        monkeypatch.setattr(services, "get_run_context", lambda request: ctx)

        async def no_scheduled_launch(**kwargs):
            raise AssertionError("The list tool cannot dispatch scheduled work")

        foreground = ScheduledTaskService(
            task_repo=tasks, task_run_repo=occurrences, launch_run=no_scheduled_launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, dispatch_enabled=False, multi_instance=True, own_stop_available=False
        )
        app = FastAPI()
        app.state.workspace_service, app.state.thread_store = case.service, threads
        app.state.run_manager, app.state.run_store = manager, store
        app.state.stream_bridge, app.state.checkpointer, app.state.store = MemoryStreamBridge(), saver, None
        app.state.run_event_store = events
        app.state.mcp_task_repo = McpTaskRepository(case.sf, workspace_required=True)
        app.state.project_repo, app.state.project_document_repo = ProjectRepository(case.sf, workspace_required=True), ProjectDocumentRepository(case.sf, workspace_required=True)
        app.state.scheduled_task_repo, app.state.scheduled_task_run_repo, app.state.scheduled_task_service = tasks, occurrences, foreground
        app.include_router(scheduled_tasks.router)
        app.add_middleware(AuthMiddleware)
        app.add_middleware(CSRFMiddleware)

        app.include_router(thread_runs.router)
        receiver = host = pool = None
        if remote:
            receiver = RunManager(store, worker_id="scheduler-tool-remote", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
            worker_app, control_app = FastAPI(), FastAPI()
            for key in (
                "workspace_service",
                "thread_store",
                "run_store",
                "stream_bridge",
                "checkpointer",
                "store",
                "run_event_store",
                "mcp_task_repo",
                "project_repo",
                "project_document_repo",
                "scheduled_task_repo",
                "scheduled_task_run_repo",
                "scheduled_task_service",
            ):
                setattr(worker_app.state, key, getattr(app.state, key))
            worker_app.state.run_manager = receiver
            node = Node(cpu_millis=4000, memory_mib=8192, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report"}, kinds={"C"})
            pool = Scheduling(ledger, nodes={"worker": node})
            secret = "scheduler-remote-origin-secret-at-least-32-bytes"
            dispatcher = NativeDispatchHost(
                app, pool, {"artifact_root": str(tmp_path / "remote-tool-pool"), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}, {"worker": secret}
            )
            app.state.native_run_admission_host = dispatcher
            # Same trusted native host, separate authenticated worker transport;
            # browser JWT/CSRF never substitutes for the node credential.
            install_native_dispatch(control_app, dispatcher)
            host = NativeWorkerHost.__new__(NativeWorkerHost)
            host.app, host.secret, host.adoption_lock, host.config = worker_app, secret, asyncio.Lock(), {"node_id": "worker"}
            host.executions, host.stop_tasks, host.sandbox_captures = {}, {}, {}

            async def request_worker(operation, **values):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control_app), base_url="http://native-remote-tool-fixture") as client:
                    response = await client.post(
                        f"/api/native-workers/worker/{operation}",
                        headers={"Authorization": "Bearer " + secret},
                        json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": dispatcher.mount_id, "owner": "scheduler-remote-owner", **values},
                    )
                    response.raise_for_status()
                    return response.json()

            host.request = request_worker
            worker_app.state.native_run_admission_host = host

        captured, observed, preparation, runtime_diagnostics = [], [], [], []
        original_prepare = scheduled_task_access.prepare_scheduler_capability

        async def observe_prepare(*args, **kwargs):
            capability = await original_prepare(*args, **kwargs)
            captured.append(capability)
            preparation.append({"present": capability is not None, "source": getattr(args[0].state, "auth_source", None), "mode": kwargs["interaction_policy"].mode.value, "config_enabled": scheduler_tools_enabled(configuration)})
            return capability

        monkeypatch.setattr(scheduled_task_access, "prepare_scheduler_capability", observe_prepare)
        entered, release = asyncio.Event(), asyncio.Event()

        async def emit_list(state, config, runtime: GraphRuntime):
            runtime_diagnostics.append({"enabled": scheduler_tools_enabled(runtime.context.get("app_config")), "capability": is_scheduler_capability(runtime.context.get(SCHEDULER_CAPABILITY_CONTEXT_KEY))})
            guard = get_invocation_guard()
            assert guard is not None and guard.target.workspace_context == case.original
            assert get_current_workspace() == case.original
            entered.set()
            await release.wait()
            return {"messages": [AIMessage(content="", tool_calls=[{"name": "schedule_task", "args": {"action": "list"}, "id": "native-schedule-list", "type": "tool_call"}])]}

        async def observe_result(state, config):
            observed.append(json.loads(state["messages"][-1].content))
            return {"messages": [AIMessage(content="The conversation's schedules were listed")]}

        builder = StateGraph(ThreadState, context_schema=dict)
        builder.add_node("call", emit_list)
        builder.add_node("tools", ToolNode([schedule_task], handle_tool_errors=False))
        builder.add_node("observed", observe_result)
        builder.add_edge(START, "call")
        builder.add_edge("call", "tools")
        builder.add_edge("tools", "observed")
        builder.add_edge("observed", END)
        graph = builder.compile(checkpointer=saver)
        monkeypatch.setattr(services, "resolve_agent_factory", lambda assistant_id: lambda **kwargs: graph)
        record, selected = None, None
        await foreground.start()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"Origin": "http://localhost", "X-CSRF-Token": "synthetic-tool-csrf"}) as client:
                client.cookies.set("access_token", create_access_token(owner))
                client.cookies.set("csrf_token", "synthetic-tool-csrf")
                # Existing conversation task: HTTP page reuse alone does not
                # grant the conversation's origin/occurrence list relationship.
                original_task = await tasks.create(
                    task_id="native-tool-conversation-task",
                    user_id=owner,
                    thread_id=None,
                    origin_thread_id=origin["thread_id"],
                    context_mode="fresh_thread_per_run",
                    assistant_id=None,
                    title="Original tool follow-up",
                    prompt="Private follow-up",
                    schedule_type="once",
                    schedule_spec={"run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
                    timezone="UTC",
                    next_run_at=datetime.now(UTC) + timedelta(hours=1),
                )
                ids = [original_task["id"]]
                response = await client.post(
                    "/api/scheduled-tasks",
                    headers={"X-Deerflow-Workspace": case.other.workspace_id},
                    json={
                        "thread_id": other_parent["thread_id"],
                        "context_mode": "reuse_thread",
                        "title": "Other private tool schedule",
                        "prompt": "Private follow-up",
                        "schedule_type": "once",
                        "schedule_spec": {"run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
                        "timezone": "UTC",
                    },
                )
                assert response.status_code == 200, response.text
                ids.append(response.json()["id"])
                selected = set_current_workspace(case.other)
                request_body = {"input": {"messages": [{"type": "human", "content": "List the schedules for this conversation"}]}}
                if remote:
                    request_body["context"] = {"scheduler_origin": {"source": "pat", "actor_user_id": "client-cannot-select-origin"}}
                    request_body["config"] = {"configurable": {"scheduler_origin": {"version": 1, "source": "internal", "actor_user_id": "client-config-cannot-select-origin"}}}
                if boundary == "permission_ceiling":
                    # Real RBAC at the original Session admission, not a mocked
                    # auth context or a client-provided permission declaration.
                    configuration.authorization = type(configuration.authorization).model_validate(
                        {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"routes": {"allow": ["workspaces:read", "runs:create"]}}}}}}
                    )
                request_headers = {"X-Deerflow-Workspace": case.original.workspace_id, **({"Idempotency-Key": "remote-scheduler-tool-origin"} if remote else {})}
                response = await client.post("/api/threads/" + origin["thread_id"] + "/runs", headers=request_headers, json=request_body)
                assert response.status_code == 200, response.text
                run_id = response.json()["run_id"]
                job = None
                if remote:
                    async with case.sf() as session:
                        pending = await session.get(RunRow, run_id)
                        assert pending.status == "pending"
                        saved_origin = pending.kwargs_json.get("scheduler_origin")
                        assert isinstance(saved_origin, dict), "Remote admission did not durably capture original session eligibility"
                        assert set(saved_origin) == {"version", "source", "actor_user_id", "token_version", "permission_ceiling"}
                        assert saved_origin["version"] == 1 and saved_origin["source"] == "session" and saved_origin["actor_user_id"] == owner
                        assert type(saved_origin["token_version"]) is int and saved_origin["token_version"] == 0
                        assert saved_origin["permission_ceiling"] == sorted(set(saved_origin["permission_ceiling"]))
                        assert ("threads:read" in saved_origin["permission_ceiling"]) == (boundary != "permission_ceiling")
                    if boundary == "token_version":
                        from deerflow.persistence.user.model import UserRow

                        async with case.sf() as session:
                            authoritative_user = await session.get(UserRow, owner)
                            assert authoritative_user.token_version == 0
                            authoritative_user.token_version = 1
                            await session.commit()
                        client.cookies.set("access_token", create_access_token(owner, token_version=1))
                    if boundary == "permission_ceiling":
                        # Replace the real config object exactly as a hot reload
                        # does, so the production RBAC cache sees the new policy.
                        configuration.authorization = type(configuration.authorization).model_validate(
                            {"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"routes": {"allow": "*"}}}}}}
                        )
                        from app.gateway.authz import resolve_route_permissions

                        assert "threads:read" in await resolve_route_permissions(await users.get_user_by_id(owner), is_internal=False)
                    repeated = await client.post("/api/threads/" + origin["thread_id"] + "/runs", headers=request_headers, json=request_body)
                    assert repeated.status_code == 200 and repeated.json()["run_id"] == run_id, repeated.text
                    async with case.sf() as session:
                        assert (await session.get(RunRow, run_id)).kwargs_json["scheduler_origin"] == saved_origin
                    envelope = (await request_worker("poll"))["claim"]
                    assert envelope is not None and envelope["job"]["native"]["kwargs"]["scheduler_origin"] == saved_origin
                    different = await client.post("/api/threads/" + origin["thread_id"] + "/runs", headers={**request_headers, "Idempotency-Key": "different-native-scheduler-work"}, json=request_body)
                    assert different.status_code == 409, different.text
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                    job = await host.report(envelope["job"], {"start_intent": True})
                    record = await host.adopt_owned(job, envelope["capability"])
                    host.executions[job["id"]] = (job, record)
                    await host.report(job, {"state": "running"})
                else:
                    lookup_scope = set_current_workspace(case.original)
                    try:
                        record = await manager.get(run_id, user_id=owner)
                    finally:
                        reset_current_workspace(lookup_scope)
                assert get_current_workspace() == case.other
                assert record is not None and record.task is not None
                await asyncio.wait_for(entered.wait(), timeout=20)
                ui = await client.get("/api/scheduled-tasks", headers={"X-Deerflow-Workspace": case.other.workspace_id})
                assert ui.status_code == 200 and [row["id"] for row in ui.json()] == [ids[1]]
                release.set()
                await asyncio.wait_for(record.task, timeout=20)
                assert record.status.value == "success", record.error
                if remote:
                    assert preparation == [{"present": boundary != "token_version", "source": "internal", "mode": "interactive", "config_enabled": True}]
                    assert record.kwargs["scheduler_origin"] == saved_origin
                    await host.stop_owned(job)
                    await host.report(job, {"state": "completed", "physical_stopped": True})
                    host.executions.pop(job["id"])
                    assert (await request_worker("poll"))["claim"] is None
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                if boundary == "normal":
                    assert len(observed) == 1 and observed[0].get("action") == "list", {"preparation": preparation, "runtime": runtime_diagnostics, "tool_error": [{key: value.get(key) for key in ("code", "error")} for value in observed]}
                    assert [row["id"] for row in observed[0]["tasks"]] == [ids[0]]
                else:
                    expected_code = "scheduler_tools_disabled" if boundary == "token_version" else "permission_denied"
                    assert len(observed) == 1 and observed[0].get("code") == expected_code, observed
                    assert all(value not in json.dumps(observed) for value in (*ids, "Original tool follow-up", "Other private tool schedule"))
                assert "Other private tool schedule" not in json.dumps(observed)
                assert captured and (captured[0] is not None) == (boundary != "token_version")
                assert get_invocation_guard() is None
                if captured[0] is not None:
                    with pytest.raises(WorkerInvocationDenied):
                        await captured[0].manage(action="list", request={})
                assert get_current_workspace() == case.other
                async with case.sf() as session:
                    durable = await session.get(RunRow, run_id)
                    original_task = await session.get(ScheduledTaskRow, ids[0])
                    journal = (await session.scalars(select(RunEventRow).where(RunEventRow.run_id == run_id))).all()
                    assert durable.status == "success" and durable.workspace_context_json == asdict(case.original)
                    assert durable.thread_id == origin["thread_id"] and durable.thread_incarnation == origin["incarnation"]
                    assert original_task.workspace_context_json == asdict(case.original) and original_task.run_count == 0
                    assert journal and all(row.workspace_id == case.original.workspace_id and row.user_id == owner for row in journal)
                    if boundary == "normal":
                        assert any(ids[0] in row.content for row in journal), "The actual tool result was not journaled"
                    else:
                        assert any(expected_code in row.content for row in journal), "The actual tool denial was not journaled"
                        assert not any(value in row.content for row in journal for value in (*ids, "Original tool follow-up", "Other private tool schedule"))
                        assert durable.kwargs_json["scheduler_origin"] == saved_origin
                    assert not any("Other private tool schedule" in row.content for row in journal)
        finally:
            release.set()
            if record is not None and record.task is not None and not record.task.done():
                record.task.cancel()
                try:
                    await record.task
                except asyncio.CancelledError:
                    pass
            if selected is not None:
                reset_current_workspace(selected)
            await foreground.stop()
            await manager.stop_heartbeat()
            if receiver is not None:
                await receiver.stop_heartbeat()

    try:
        _in_workspace_case(native_engine, scenario, owner_user_id=owner)
    finally:
        if ledger is not None:
            ledger.engine.dispose()


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduler_remote_tool_list_preserves_admitted_session(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    _exercise_scheduler_tool_list(native_engine, executor_engine, monkeypatch, tmp_path, remote=True)


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
@pytest.mark.parametrize("boundary", ["token_version", "permission_ceiling"])
def test_scoped_scheduler_remote_tool_retains_original_authority(native_engine, executor_engine, monkeypatch, tmp_path, boundary):  # noqa: F811
    _exercise_scheduler_tool_list(native_engine, executor_engine, monkeypatch, tmp_path, remote=True, boundary=boundary)

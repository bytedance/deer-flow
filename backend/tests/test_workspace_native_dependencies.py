"""One native PostgreSQL async dependency/notification story.

The remote MCP driver is deterministic IO. This does not claim physical B or
AIO acceptance; both C admissions, SQL task/outbox and launcher are real.
"""

import asyncio
import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
@pytest.mark.parametrize("revocation_phase", ["normal", "notification_member", "dispatched_member"])
def test_scoped_native_dependency_notification_resumes_original_goal(native_engine, executor_engine, monkeypatch, tmp_path, revocation_phase):  # noqa: F811
    _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, revocation_phase=revocation_phase)


def _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, *, revocation_phase="normal", scheduled=False, goal_replacement=False, member_control=False, queued_control=False, physical_b=None, pool_b=False):  # noqa: F811
    from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost, install_native_dispatch
    from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import SCHEMA_REVISION, upgrade_schema
    from fastapi import FastAPI
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from sqlalchemy import select, update

    from app.gateway import deps, services
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.native_admission import make_native_snapshot
    from app.gateway.run_models import RunCreateRequest
    from app.mcp_tasks.service import McpTaskService
    from app.scheduler.service import ScheduledTaskService
    from deerflow.agents.thread_state import ThreadState
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config import paths as paths_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import Paths
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskSnapshot, TaskStatus, TaskSubmission, TaskSubmitRequest
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
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
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager
    from deerflow.runtime import goal as goal_runtime
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.runs import worker as native_worker
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    assert native_engine.dialect.name == executor_engine.dialect.name == "postgresql"
    upgrade_schema(executor_engine)
    ledger = JobStore(executor_engine.url.render_as_string(hide_password=False))
    owner_user_id = "11111111-1111-4111-8111-111111111111"
    configuration = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    monkeypatch.setattr(services, "get_app_config", lambda: configuration)
    if scheduled:
        import deerflow.config as config_facade
        from deerflow.config import app_config

        configuration.scheduler.enabled = True
        for module in (config_facade, app_config, deps):
            monkeypatch.setattr(module, "get_app_config", lambda: configuration)
    if goal_replacement:
        from app.gateway.auth import config as auth_config

        monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="synthetic-scheduled-goal-replacement-key-at-least-64-characters!!"))
        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "owned-files"))

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        origin = await threads.create("native-dependency-main", user_id=owner_user_id)
        run_store = RunRepository(case.sf, workspace_required=True)
        task_repo = McpTaskRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120)
        central = RunManager(run_store, worker_id="dependency-central", run_ownership_config=ownership)
        receiver = RunManager(run_store, worker_id="dependency-worker", run_ownership_config=ownership)
        user_repo = SQLiteUserRepository(case.sf)
        monkeypatch.setattr(deps, "_cached_repo", user_repo)
        monkeypatch.setattr(deps, "_cached_local_provider", LocalAuthProvider(user_repo))
        principal = await deps.get_local_provider().get_user(owner_user_id)
        principal_token = set_current_user(principal)
        saver = MemorySaver()
        central_app, worker_app = FastAPI(), FastAPI()
        events = DbRunEventStore(case.sf, workspace_required=True)
        for app, manager in ((central_app, central), (worker_app, receiver)):
            app.state.run_manager, app.state.run_store = manager, run_store
            app.state.thread_store, app.state.mcp_task_repo = threads, task_repo
            app.state.stream_bridge, app.state.checkpointer, app.state.store = MemoryStreamBridge(), saver, None
            app.state.run_event_store = events
            app.state.project_repo = ProjectRepository(case.sf, workspace_required=True)
            app.state.project_document_repo = ProjectDocumentRepository(case.sf, workspace_required=True)
        node = Node(cpu_millis=4000, memory_mib=8192, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report", "small"} if pool_b else {"report"}, kinds={"B", "C"} if pool_b else {"C"})
        pool = Scheduling(ledger, nodes={"worker": node})
        secret = "native-dependency-offline-fixture-32-bytes"
        config = {"artifact_root": str(tmp_path / "dependency-pool"), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}
        dispatcher = NativeDispatchHost(central_app, pool, config, {"worker": secret})
        central_app.state.native_run_admission_host = dispatcher
        install_native_dispatch(central_app, dispatcher)
        host = NativeWorkerHost.__new__(NativeWorkerHost)
        host.app, host.secret, host.adoption_lock = worker_app, secret, asyncio.Lock()
        host.config = {"node_id": "worker"}
        scheduler_tasks = scheduler_occurrences = foreground = control = None
        scheduler_id, occurrence_id = "task-installed-dependency", None
        reconciled = []
        if scheduled:
            scheduler_tasks = ScheduledTaskRepository(case.sf, run_repository=run_store, workspace_required=True)
            scheduler_occurrences = ScheduledTaskRunRepository(case.sf, run_repository=run_store, workspace_required=True)
            history = ScheduledTaskEventRepository(case.sf, workspace_required=True)

            async def launch_scheduled(**kwargs):
                return await services.launch_scheduled_thread_run(app=central_app, **kwargs)

            actual_reconciler = dispatcher.reconcile_dependency_waits

            async def observe_reconciler(source_run_ids):
                valid = await actual_reconciler(source_run_ids)
                reconciled.append((frozenset(source_run_ids), frozenset(valid)))
                return valid

            foreground = ScheduledTaskService(
                task_repo=scheduler_tasks, task_run_repo=scheduler_occurrences, launch_run=launch_scheduled, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, dispatch_enabled=False, multi_instance=True
            )
            control = ScheduledTaskService(
                task_repo=scheduler_tasks,
                task_run_repo=scheduler_occurrences,
                launch_run=launch_scheduled,
                poll_interval_seconds=1,
                lease_seconds=120,
                max_concurrent_runs=1,
                multi_instance=True,
                dependency_wait_reconciler=observe_reconciler,
            )
            for app in (central_app, worker_app):
                app.state.scheduled_task_repo, app.state.scheduled_task_run_repo = scheduler_tasks, scheduler_occurrences
                app.state.scheduled_task_event_repo, app.state.scheduled_task_service = history, foreground
        notification_trace = []
        withdrawn = False
        host.executions, host.stop_tasks, host.sandbox_captures = {}, {}, {}

        async def request_worker(operation, **values):
            nonlocal withdrawn
            if operation == "notification" and revocation_phase == "notification_member" and not withdrawn:
                # The worker has already prepared and signed this request. The
                # controller must independently reject the original SQL grant.
                assert values.get("capability")
                async with case.sf() as session:
                    changed = await session.execute(
                        update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == owner_user_id).values(version=WorkspaceMembershipRow.version + 1)
                    )
                    assert changed.rowcount == 1
                    await session.commit()
                withdrawn = True
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=central_app), base_url="http://native-dependency-fixture") as client:
                response = await client.post(
                    f"/api/native-workers/worker/{operation}",
                    headers={"Authorization": "Bearer " + secret},
                    json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": dispatcher.mount_id, "owner": "dependency-owner", **values},
                )
            if operation == "notification":
                notification_trace.append({"stage": "controller_http", "status": response.status_code})
            response.raise_for_status()
            return response.json()

        host.request = request_worker
        worker_app.state.native_run_admission_host = host
        ctx = RunContext(checkpointer=saver, thread_store=threads, mcp_task_repo=task_repo, event_store=events, app_config=configuration, on_dependency_wait=host.persist_dependency_wait)
        monkeypatch.setattr(services, "get_run_context", lambda request: ctx)
        io_scopes, created_tasks, executed = [], [], []

        def observe_async(stage, original):
            async def observed(*args, **kwargs):
                try:
                    return await original(*args, **kwargs)
                except Exception as exc:
                    notification_trace.append({"stage": stage, "exception": type(exc).__name__, "reason": str(exc).replace(secret, "<redacted>").splitlines()[0][:200] if str(exc) else ""})
                    raise

            return observed

        monkeypatch.setattr(services, "ensure_checkpoint_history_seeded", observe_async("checkpoint_history_seed", services.ensure_checkpoint_history_seeded))
        monkeypatch.setattr(dispatcher, "prepare_notification", observe_async("dependency_prepare", dispatcher.prepare_notification))
        monkeypatch.setattr(services, "_launch_mcp_task_notification_run", observe_async("native_launcher", services._launch_mcp_task_notification_run))
        original_notification_authority = task_repo.resolve_notification_authority

        async def observe_notification_authority(task_id, **kwargs):
            resolved = await observe_async("notification_sql", original_notification_authority)(task_id, **kwargs)
            notification = kwargs.get("notification")
            if notification is not None:
                notification_trace.append(
                    {
                        "stage": "notification_sql_match",
                        "version_matches": resolved["dispatch_version"] == notification["dispatch_version"],
                        "attempt_matches": resolved["dispatch_attempt"] == notification["dispatch_attempt"],
                        "event_matches": resolved["dispatch_event"] == notification["event"],
                    }
                )
            return resolved

        monkeypatch.setattr(task_repo, "resolve_notification_authority", observe_notification_authority)
        from ecs_executor import agent_dispatch as dispatch_module

        original_scope_verifier = dispatch_module.verify_execution_scope

        def observe_scope_verifier(*args, **kwargs):
            try:
                return original_scope_verifier(*args, **kwargs)
            except Exception as exc:
                if kwargs.get("expected_operation") == "native_notification":
                    notification_trace.append({"stage": "notification_capability", "exception": type(exc).__name__, "reason": str(exc).splitlines()[0][:200] if str(exc) else ""})
                raise

        monkeypatch.setattr(dispatch_module, "verify_execution_scope", observe_scope_verifier)

        class DeterministicRemoteIO:
            async def submit(self, request):
                io_scopes.append(("submit", request.workspace_context, get_current_workspace()))
                return TaskSubmission(remote_task_id="owned-deterministic-report", snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED))

            async def get_status(self, reference):
                io_scopes.append(("status", reference.workspace_context, get_current_workspace()))
                return TaskSnapshot(status=TaskStatus.COMPLETED, result={"report": "owned dependency report"}, result_preview="owned dependency report")

            async def cancel(self, reference):
                raise AssertionError("normal dependency story must not cancel its remote task")

        drivers = McpTaskDriverRegistry()
        physical_state = physical_b(case, owner_user_id, tmp_path / "owned-files", io_scopes, pool=pool if pool_b else None) if physical_b is not None else None
        if physical_state is None:
            drivers.register("deterministic", DeterministicRemoteIO())
        else:
            drivers.register("ordinary-tools", physical_state.driver)
        tasks = McpTaskService(
            repository=task_repo,
            drivers=drivers,
            poll_interval_seconds=1,
            lease_seconds=120,
            max_concurrent_polls=1,
            launch_notification=lambda **kwargs: services.launch_mcp_task_notification_run(app=worker_app, **kwargs),
            get_run=receiver.get,
        )
        if physical_state is not None:

            async def drain_cancelled():
                await tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=30))

            physical_state.drain_cancelled = drain_cancelled
            from deerflow.mcp.tasks import runtime as task_runtime

            previous_submitter = task_runtime._submitter
            task_runtime.set_mcp_task_submitter(tasks)
            actual_submit = tasks.submit

            async def capture_real_submission(**kwargs):
                created = await actual_submit(**kwargs)
                created_tasks.append(created)
                return created

            monkeypatch.setattr(tasks, "submit", capture_real_submission)
        first = None

        async def respond(state, config):
            assert get_current_workspace() == case.original
            executed.append(state.get("goal"))
            if not created_tasks:
                created_tasks.append(
                    await tasks.submit(
                        driver_name="deterministic",
                        request=TaskSubmitRequest(
                            user_id=first.user_id,
                            thread_id=first.thread_id,
                            thread_incarnation=first.thread_incarnation,
                            run_id=first.run_id,
                            tool_call_id="owned-dependency-submit",
                            server_name="deterministic",
                            task_name="report",
                            arguments={},
                            workspace_context=first.workspace_context,
                            source_worker_id=first.owner_worker_id,
                        ),
                        now=datetime.now(UTC),
                    )
                )
                return {"messages": [AIMessage(content="Waiting for the owned asynchronous report")], "title": "Owned dependency report"}
            completed = await task_repo.get(created_tasks[0]["id"], user_id=owner_user_id, thread_id=first.thread_id, thread_incarnation=first.thread_incarnation)
            assert completed["status"] == "completed" and "owned dependency report" in str(completed)
            return {"messages": [AIMessage(content="Delivered the owned dependency report")], "title": "Owned dependency report"}

        builder = StateGraph(ThreadState, context_schema=dict)
        builder.add_node("answer", respond)
        builder.add_edge(START, "answer")
        builder.add_edge("answer", END)
        if physical_state is not None:
            from langgraph.prebuilt import ToolNode

            async def plan_physical(state):
                if created_tasks:
                    return {"messages": [AIMessage(content="Inspect the completed original execution")]}  # C2 never resubmits B.
                return {"messages": [AIMessage(content="", tool_calls=[{"name": physical_state.tool.name, "args": physical_state.arguments(first), "id": "real-b-submit", "type": "tool_call"}])]}

            async def physical_answer(state):
                assert get_current_workspace() == case.original
                executed.append(state.get("goal"))
                completed = await task_repo.get(created_tasks[0]["id"], user_id=owner_user_id, thread_id=first.thread_id, thread_incarnation=first.thread_incarnation)
                if completed["status"] != "completed":
                    assert completed["status"] in ("submitted", "working")
                    return {"messages": [AIMessage(content="Waiting for the real Docker report")], "title": "Owned dependency report"}
                # Both the durable MCP return and the real native publication
                # must exist. A deterministic success string is never injected.
                import hashlib

                report_path = physical_state.output_path(first, completed["remote_task_id"])
                report = report_path.read_text()
                payload = (report_path.parent.parent / "result.json").read_bytes()
                result = json.loads(payload)
                assert report == "owned dependency report" and result["stdout"] == report and result["exit_code"] == 0
                assert completed["result"] == {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "exit_code": 0}
                assert completed["result_artifact"]["uri"].endswith("/" + completed["remote_task_id"] + "/result.json")
                physical_state.evidence["c2_read_actual_published_report"] = True
                return {"messages": [AIMessage(content="Delivered " + report)], "title": "Owned dependency report"}

            builder = StateGraph(ThreadState, context_schema=dict)
            builder.add_node("plan", plan_physical)
            builder.add_node("tools", ToolNode([physical_state.tool], handle_tool_errors=False))
            builder.add_node("answer", physical_answer)
            builder.add_edge(START, "plan")
            builder.add_conditional_edges("plan", lambda state: "tools" if state["messages"][-1].tool_calls else "answer")
            builder.add_edge("tools", "answer")
            builder.add_edge("answer", END)
        graph = builder.compile(checkpointer=saver)
        monkeypatch.setattr(services, "resolve_agent_factory", lambda assistant_id: lambda **kwargs: graph)
        outcomes = iter(
            [{"satisfied": False, "blocker": "external_wait", "reason": "remote report pending", "relied_on_assumption": False}, {"satisfied": True, "blocker": "none", "reason": "owned report delivered", "relied_on_assumption": False}]
        )

        async def evaluate(*args, **kwargs):
            return next(outcomes)

        monkeypatch.setattr(native_worker, "create_goal_evaluator_model", lambda **kwargs: object())
        monkeypatch.setattr(native_worker, "evaluate_goal_completion", evaluate)
        admitted = []

        async def execute_envelope(envelope):
            job = await host.report(envelope["job"], {"start_intent": True})
            record = await host.adopt_owned(job, envelope["capability"])
            admitted.append(record)
            host.executions[job["id"]] = (job, record)
            await host.report(job, {"state": "running"})
            await asyncio.wait_for(record.task, timeout=20)
            assert record.status.value == "success", record.error
            host.sandbox_captures[job["id"]].execution_drained(record)
            await host.stop_owned(job)  # Real, drained no-sandbox proof before capacity release.
            await host.report(job, {"state": "completed", "physical_stopped": True})
            host.executions.pop(job["id"])
            return record

        try:
            if physical_state is not None:
                await physical_state.open()
            if scheduled:
                await foreground.start()
                ctx = replace(ctx, on_run_completed=control.handle_run_completion)
                now = datetime.now(UTC)
                await scheduler_tasks.create(
                    task_id=scheduler_id,
                    user_id=owner_user_id,
                    thread_id=None,
                    origin_thread_id=origin["thread_id"],
                    context_mode="fresh_thread_per_run",
                    assistant_id="lead_agent",
                    title="Installed dependency follow-up",
                    prompt="Deliver the owned asynchronous report",
                    goal_objective="Deliver the owned asynchronous report",
                    schedule_type="once",
                    schedule_spec={"run_at": now.isoformat()},
                    timezone="UTC",
                    next_run_at=now,
                )
                due = await scheduler_tasks.claim_due_tasks(now=now, lease_owner=foreground._lease_owner, lease_seconds=120, limit=1)
                assert len(due) == 1 and due[0]["id"] == scheduler_id
                queued = await foreground.dispatch_task(due[0], now=now, trigger="scheduled")
                occurrence_id = queued["task_run_id"]
                assert queued["outcome"] == "queued"
                if queued_control:
                    from ecs_executor import dependencies as dependency_module
                    from ecs_executor.job_store import _JOBS

                    from deerflow.persistence.user.model import UserRow
                    from deerflow.persistence.workspaces.model import WorkspaceAuditEventRow, WorkspaceOperationOutboxRow
                    from deerflow.persistence.workspaces.sql import WorkspaceRepository

                    unknown_id = "task-unknown-queued-control"
                    await scheduler_tasks.create(
                        task_id=unknown_id,
                        user_id=owner_user_id,
                        thread_id=None,
                        origin_thread_id=origin["thread_id"],
                        context_mode="fresh_thread_per_run",
                        assistant_id="lead_agent",
                        title="Retain unknown queued accounting",
                        prompt="Retain the original queued intent",
                        schedule_type="once",
                        schedule_spec={"run_at": now.isoformat()},
                        timezone="UTC",
                        next_run_at=now,
                    )
                    due_unknown = await scheduler_tasks.claim_due_tasks(now=now, lease_owner=foreground._lease_owner, lease_seconds=120, limit=2)
                    unknown_task = next(row for row in due_unknown if row["id"] == unknown_id)
                    unknown_queued = await foreground.dispatch_task(unknown_task, now=now, trigger="scheduled")
                    assert unknown_queued["outcome"] == "queued"
                    unknown_occurrence_id = unknown_queued["task_run_id"]
                    async with case.sf() as session:
                        await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == unknown_occurrence_id).values(launch_accounted=None))
                        await session.commit()

                    async def queued_snapshot():
                        async with case.sf() as session:
                            parent_rows = {row["id"]: dict(row) for row in (await session.execute(select(ScheduledTaskRow.__table__).where(ScheduledTaskRow.id.in_((scheduler_id, unknown_id))))).mappings()}
                            occurrence_rows = {row["id"]: dict(row) for row in (await session.execute(select(ScheduledTaskRunRow.__table__).where(ScheduledTaskRunRow.task_id.in_((scheduler_id, unknown_id))))).mappings()}
                            native_ids = frozenset(await session.scalars(select(RunRow.run_id).where(RunRow.operation_kind == "run")))
                            event_rows = [
                                dict(row) for row in (await session.execute(select(ScheduledTaskEventRow.__table__).where(ScheduledTaskEventRow.task_id.in_((scheduler_id, unknown_id))).order_by(ScheduledTaskEventRow.id))).mappings()
                            ]
                            audit_rows = [
                                dict(row)
                                for row in (
                                    await session.execute(
                                        select(WorkspaceAuditEventRow.__table__)
                                        .where(
                                            WorkspaceAuditEventRow.workspace_id == case.original.workspace_id,
                                            WorkspaceAuditEventRow.action == "scheduler.revoke_settled",
                                        )
                                        .order_by(WorkspaceAuditEventRow.id)
                                    )
                                ).mappings()
                            ]
                            revoke_rows = [
                                dict(row)
                                for row in (
                                    await session.execute(
                                        select(WorkspaceOperationOutboxRow.__table__)
                                        .where(
                                            WorkspaceOperationOutboxRow.workspace_id == case.original.workspace_id,
                                            WorkspaceOperationOutboxRow.user_id == owner_user_id,
                                            WorkspaceOperationOutboxRow.kind == "workspace_revoke",
                                        )
                                        .order_by(WorkspaceOperationOutboxRow.operation_id)
                                    )
                                ).mappings()
                            ]
                        return deepcopy((parent_rows, occurrence_rows, native_ids, event_rows, audit_rows, revoke_rows))

                    def queued_pool_snapshot():
                        with ledger.engine.connect() as connection:
                            return deepcopy([dict(row) for row in connection.execute(select(_JOBS).order_by(_JOBS.c.id)).mappings()])

                    before_membership = await queued_snapshot()
                    known = before_membership[1][occurrence_id]
                    unknown = before_membership[1][unknown_occurrence_id]
                    assert known["status"] == unknown["status"] == "queued" and known["run_id"] is unknown["run_id"] is None
                    assert known["launch_accounted"] is False and unknown["launch_accounted"] is None
                    assert known["attempt_count"] == unknown["attempt_count"] == 0
                    for row in (known, unknown):
                        assert row["started_at"] is row["lease_owner"] is row["lease_expires_at"] is None
                        assert row["workspace_context_json"] == asdict(case.original)
                    successor = "22222222-2222-4222-8222-222222222222"
                    async with case.sf() as session:
                        session.add(UserRow(id=successor, email="queued-control-successor@example.com", email_verified_at=datetime.now(UTC)))
                        await session.commit()
                    workspaces = WorkspaceRepository(case.sf)
                    await workspaces.add_member(case.original.workspace_id, owner_user_id, successor, role="admin")
                    await workspaces.transfer_owner(case.original.workspace_id, owner_user_id, successor)
                    await workspaces.remove_member(case.original.workspace_id, successor, owner_user_id)
                    before = await queued_snapshot()
                    assert before[:5] == before_membership[:5]
                    assert len(before[5]) == 2 and all(row["state"] == "pending" and "scheduler" in row["payload"]["pending_domains"] for row in before[5])
                    pool_before = await asyncio.to_thread(queued_pool_snapshot)
                    forbidden_calls = []

                    async def forbid_business_or_physical(*args, **kwargs):
                        forbidden_calls.append("business_read_or_physical_action")
                        raise AssertionError("Queued revocation attempted business work or a physical receipt")

                    selected = set_current_workspace(case.other)
                    try:
                        with monkeypatch.context() as control_only:
                            for module, name in (
                                (dependency_module, "checkpoint_receipt"),
                                (goal_runtime, "read_thread_goal"),
                                (native_worker, "clear_recovered_scheduled_goal"),
                                (central, "get"),
                                (receiver, "get"),
                                (task_repo, "get"),
                                (task_repo, "list_by_run"),
                                (host, "stop_owned"),
                                (host, "report"),
                            ):
                                control_only.setattr(module, name, forbid_business_or_physical)
                            await control.run_once(now=datetime.now(UTC))
                            after = await queued_snapshot()
                            assert after[0][unknown_id] == before[0][unknown_id] and after[1][unknown_occurrence_id] == before[1][unknown_occurrence_id]
                            assert after[0][scheduler_id]["status"] == "cancelled" and after[1][occurrence_id]["status"] == "interrupted"
                            for key, value in before[0][scheduler_id].items():
                                if key not in {"status", "next_run_at", "updated_at"}:
                                    assert after[0][scheduler_id][key] == value
                            for key, value in before[1][occurrence_id].items():
                                if key not in {"status", "error", "finished_at"}:
                                    assert after[1][occurrence_id][key] == value
                            assert after[1][occurrence_id]["run_id"] is None and after[1][occurrence_id]["launch_accounted"] is False
                            assert after[0][scheduler_id]["run_count"] == 0
                            assert after[2:4] == before[2:4] and after[5] == before[5]
                            assert len(after[4]) == 1 and after[4][0]["resource_id"] == occurrence_id and after[4][0]["actor_user_id"] is None
                            assert after[4][0]["request_id"] in {row["operation_id"] for row in before[5]}
                            assert await asyncio.to_thread(queued_pool_snapshot) == pool_before
                            await control.run_once(now=datetime.now(UTC))
                            assert await queued_snapshot() == after
                            assert await asyncio.to_thread(queued_pool_snapshot) == pool_before
                        assert forbidden_calls == [] and get_current_workspace() == case.other
                        assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                        assert admitted == [] and executed == [] and created_tasks == []
                    finally:
                        reset_current_workspace(selected)
                    return
                await control.run_once(now=now)
                async with case.sf() as session:
                    occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
                    assert occurrence.run_id is not None and occurrence.status == "running"
                    source_id = occurrence.run_id
                source = await central.get(source_id, user_id=owner_user_id)
                assert source is not None
                first = source
                original_goal = None
            else:
                original_goal = goal_runtime.build_goal_state("Deliver the owned asynchronous report")
                await graph.aupdate_state({"configurable": {"thread_id": "native-dependency-main"}}, {"goal": original_goal}, as_node="answer")
                source = await central.create_or_reject("native-dependency-main", user_id=owner_user_id)
                first = source
                # The receiver hydrates its own RunRecord; the first graph uses
                # that SQL-adopted record, rather than the former central owner.
                request = SimpleNamespace(app=central_app, url="https://native.example.invalid/")

                async def snapshot_factory(**transport):
                    return await make_native_snapshot(
                        request,
                        source,
                        run_ctx=replace(ctx, workspace_context=case.original),
                        body=RunCreateRequest(),
                        config={"configurable": {"thread_id": source.thread_id}},
                        graph_input={"messages": [HumanMessage(content="Deliver this report")]},
                        admitted_knowledge_scope=None,
                        scope_assistant_id=None,
                        scheduled_task_runtime=None,
                        require_existing_thread=True,
                        **transport,
                    )

                assert await dispatcher.admit_native(source, snapshot_factory)
            selected = set_current_workspace(case.other)
            try:
                polled = await request_worker("poll")
                job = polled["claim"]["job"]
                job = await host.report(job, {"start_intent": True})
                first = await host.adopt_owned(job, polled["claim"]["capability"])
                admitted.append(first)
                host.executions[job["id"]] = (job, first)
                await host.report(job, {"state": "running"})
                await asyncio.wait_for(first.task, timeout=20)
                assert first.status.value == "success", first.error
                assert first.goal_verdict["native_dependency_wait"] is True
                waiting = await asyncio.to_thread(ledger.get, job["id"])
                assert waiting["dependency_wait"]["source_run_id"] == first.run_id
                preserved = await goal_runtime.read_thread_goal(saver, first.thread_id)
                assert preserved["status"] == "active"
                if scheduled:
                    original_goal = preserved
                else:
                    assert preserved["created_at"] == original_goal["created_at"]
                await host.stop_owned(job)
                await host.report(job, {"state": "completed", "physical_stopped": True})
                host.executions.pop(job["id"])
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                if scheduled:
                    await control.run_once(now=datetime.now(UTC))
                    assert any(first.run_id in checked and first.run_id in valid for checked, valid in reconciled), "Installed dependency reconciler did not validate/protect C1: " + repr(reconciled)
                    async with case.sf() as session:
                        occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
                        parent_task = await session.get(ScheduledTaskRow, scheduler_id)
                        assert occurrence.status == "running" and occurrence.run_id == first.run_id and occurrence.launch_accounted is True
                        assert parent_task.status == "running" and parent_task.run_count == 1
                if member_control:
                    from ecs_executor import dependencies as dependency_module
                    from ecs_executor.job_store import _JOBS

                    from deerflow.persistence.user.model import UserRow
                    from deerflow.persistence.workspaces.model import WorkspaceAuditEventRow, WorkspaceOperationOutboxRow
                    from deerflow.persistence.workspaces.sql import WorkspaceRepository

                    successor = "22222222-2222-4222-8222-222222222222"
                    async with case.sf() as session:
                        session.add(UserRow(id=successor, email="scheduler-control-successor@example.com", email_verified_at=datetime.now(UTC)))
                        await session.commit()
                    workspaces = WorkspaceRepository(case.sf)
                    await workspaces.add_member(case.original.workspace_id, owner_user_id, successor, role="admin")
                    await workspaces.transfer_owner(case.original.workspace_id, owner_user_id, successor)
                    await workspaces.remove_member(case.original.workspace_id, successor, owner_user_id)
                    async with case.sf() as session:
                        member = await session.get(WorkspaceMembershipRow, (case.original.workspace_id, owner_user_id))
                        assert member.status == "removed" and member.version == case.original.membership_version + 2
                        revokes = (
                            await session.scalars(
                                select(WorkspaceOperationOutboxRow).where(
                                    WorkspaceOperationOutboxRow.workspace_id == case.original.workspace_id,
                                    WorkspaceOperationOutboxRow.user_id == owner_user_id,
                                    WorkspaceOperationOutboxRow.kind == "workspace_revoke",
                                )
                            )
                        ).all()
                        assert len(revokes) == 2 and all(row.state == "pending" and "scheduler" in row.payload["pending_domains"] for row in revokes)
                        revoke_baseline = deepcopy({row.operation_id: row.payload for row in revokes})

                    async def control_snapshot():
                        async with case.sf() as session:
                            source = dict((await session.execute(select(RunRow.__table__).where(RunRow.run_id == first.run_id))).mappings().one())
                            normal_ids = frozenset(await session.scalars(select(RunRow.run_id).where(RunRow.operation_kind == "run")))
                            child = dict((await session.execute(select(ScheduledTaskRunRow.__table__).where(ScheduledTaskRunRow.id == occurrence_id))).mappings().one())
                            parent = dict((await session.execute(select(ScheduledTaskRow.__table__).where(ScheduledTaskRow.id == scheduler_id))).mappings().one())
                            lifetimes = [
                                dict(row)
                                for row in (
                                    await session.execute(
                                        select(WorkspaceOperationOutboxRow.__table__).where(
                                            WorkspaceOperationOutboxRow.kind == "run_execution",
                                            WorkspaceOperationOutboxRow.payload["run_id"].as_string() == first.run_id,
                                        )
                                    )
                                ).mappings()
                            ]
                            events = [dict(row) for row in (await session.execute(select(ScheduledTaskEventRow.__table__).where(ScheduledTaskEventRow.task_id == scheduler_id))).mappings()]
                            audits = [
                                dict(row)
                                for row in (
                                    await session.execute(
                                        select(WorkspaceAuditEventRow.__table__)
                                        .where(
                                            WorkspaceAuditEventRow.action == "scheduler.revoke_settled",
                                            WorkspaceAuditEventRow.resource_id == occurrence_id,
                                        )
                                        .order_by(WorkspaceAuditEventRow.id)
                                    )
                                ).mappings()
                            ]
                            ops = [
                                dict(row)
                                for row in (
                                    await session.execute(select(WorkspaceOperationOutboxRow.__table__).where(WorkspaceOperationOutboxRow.operation_id.in_(revoke_baseline)).order_by(WorkspaceOperationOutboxRow.operation_id))
                                ).mappings()
                            ]
                        return deepcopy((source, normal_ids, child, parent, lifetimes, events, audits, ops))

                    def pool_snapshot():
                        with ledger.engine.connect() as connection:
                            return deepcopy([dict(row) for row in connection.execute(select(_JOBS).order_by(_JOBS.c.id)).mappings() if row["record"].get("kind") == "C"])

                    before = await control_snapshot()
                    assert len(before[4]) == 1 and before[4][0]["state"] == "completed"
                    pool_before = await asyncio.to_thread(pool_snapshot)
                    forbidden_reads = []

                    async def forbid_business(*args, **kwargs):
                        forbidden_reads.append("checkpoint/result/goal/business_run")
                        raise AssertionError("Withdrawn Scheduler control attempted a business read")

                    # These are real business entry points, not authorization
                    # replacements. Control inspection and raw test SQL remain.
                    with monkeypatch.context() as control_only:
                        control_only.setattr(dependency_module, "checkpoint_receipt", forbid_business)
                        control_only.setattr(goal_runtime, "read_thread_goal", forbid_business)
                        control_only.setattr(native_worker, "clear_recovered_scheduled_goal", forbid_business)
                        control_only.setattr(central, "get", forbid_business)
                        control_only.setattr(receiver, "get", forbid_business)
                        control_only.setattr(task_repo, "get", forbid_business)
                        control_only.setattr(task_repo, "list_by_run", forbid_business)
                        await control.run_once(now=datetime.now(UTC))
                        after = await control_snapshot()
                        assert after[2]["status"] == "interrupted", "Revoked closed C1 still holds the Scheduler budget"
                        assert after[3]["status"] == "cancelled"
                        assert after[0] == before[0] and after[1] == before[1] and after[4] == before[4]
                        assert after[2]["run_id"] == first.run_id and after[2]["launch_accounted"] is True
                        assert after[2]["workspace_context_json"] == after[3]["workspace_context_json"] == asdict(case.original)
                        assert after[3]["run_count"] == before[3]["run_count"] == 1
                        assert after[5] == before[5] and len(after[6]) == 1
                        assert after[6][0]["request_id"] in revoke_baseline and after[6][0]["actor_user_id"] is None
                        assert after[7] == before[7]  # Parent and scheduler domain remain pending.
                        old_wait = await asyncio.to_thread(ledger.get, job["id"])
                        assert old_wait["dependency_wait"]["active"] is False
                        pool_after = await asyncio.to_thread(pool_snapshot)
                        # Ledger control retires only the wait/version, never a
                        # pool reservation or native/physical receipt.
                        assert len(pool_after) == len(pool_before)
                        for previous, current in zip(pool_before, pool_after, strict=True):
                            assert current["id"] == previous["id"]
                            old, new = deepcopy(previous["record"]), deepcopy(current["record"])
                            if current["id"] == job["id"]:
                                old["dependency_wait"]["active"] = False
                            assert new == old
                        await control.run_once(now=datetime.now(UTC))
                        assert await control_snapshot() == after
                        assert await asyncio.to_thread(pool_snapshot) == pool_after
                    assert forbidden_reads == []
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                    assert len(admitted) == 1 and len(executed) == 1 and get_current_workspace() == case.other
                    return
                if goal_replacement:
                    from ecs_executor.job_store import _JOBS

                    from app.gateway.auth import create_access_token
                    from app.gateway.auth_middleware import AuthMiddleware
                    from app.gateway.csrf_middleware import CSRFMiddleware
                    from app.gateway.routers import threads as threads_router

                    # Freeze the canonical source, not checkpoint-write reservations.
                    # These native control operations may legitimately create rows.
                    async def native_snapshot():
                        async with case.sf() as session:
                            source = dict((await session.execute(select(RunRow.__table__).where(RunRow.run_id == first.run_id))).mappings().one())
                            normal_ids = frozenset(await session.scalars(select(RunRow.run_id).where(RunRow.operation_kind == "run")))
                            child = dict((await session.execute(select(ScheduledTaskRunRow.__table__).where(ScheduledTaskRunRow.id == occurrence_id))).mappings().one())
                            parent = dict((await session.execute(select(ScheduledTaskRow.__table__).where(ScheduledTaskRow.id == scheduler_id))).mappings().one())
                            event_rows = [dict(row) for row in (await session.execute(select(ScheduledTaskEventRow.__table__).where(ScheduledTaskEventRow.task_id == scheduler_id).order_by(ScheduledTaskEventRow.id))).mappings()]
                        return deepcopy((source, normal_ids, child, parent, event_rows))

                    def c_job_ids():
                        with ledger.engine.connect() as connection:
                            return frozenset(row.id for row in connection.execute(select(_JOBS)) if row.record.get("kind") == "C")

                    before = await native_snapshot()
                    pool_ids = await asyncio.to_thread(c_job_ids)
                    browser_app = FastAPI()
                    browser_app.state = central_app.state
                    browser_app.state.workspace_service = case.service
                    browser_app.include_router(threads_router.router)
                    browser_app.add_middleware(AuthMiddleware)
                    browser_app.add_middleware(CSRFMiddleware)
                    assert get_current_workspace() == case.other
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=browser_app),
                        base_url="http://localhost",
                        headers={"Origin": "http://localhost", "X-CSRF-Token": "goal-replacement-csrf", "X-Deerflow-Workspace": case.original.workspace_id},
                    ) as client:
                        client.cookies.set("access_token", create_access_token(owner_user_id))
                        client.cookies.set("csrf_token", "goal-replacement-csrf")
                        response = await client.put("/api/threads/" + first.thread_id + "/goal", json={"objective": "Investigate the revised research objective instead of the old report"})
                    assert response.status_code == 200, response.text
                    new_goal = response.json()["goal"]
                    assert new_goal["objective"] != original_goal["objective"] and new_goal["status"] == "active"
                    assert await goal_runtime.read_thread_goal(saver, first.thread_id) == new_goal
                    assert get_current_workspace() == case.other
                    await control.run_once(now=datetime.now(UTC))
                    after = await native_snapshot()
                    assert after[0] == before[0] and after[1] == before[1]
                    assert after[2]["status"] == "interrupted" and after[2]["run_id"] == first.run_id and after[2]["launch_accounted"] is True
                    assert after[3]["status"] == "cancelled" and after[3]["run_count"] == 1
                    assert after[4] == before[4]  # Native interrupted once occurrences are silent.
                    assert (await asyncio.to_thread(ledger.get, job["id"]))["dependency_wait"]["active"] is False
                    assert await goal_runtime.read_thread_goal(saver, first.thread_id) == new_goal
                    scoped = set_current_workspace(case.original)
                    try:
                        assert (await scheduler_tasks.automatic_runs_used_for([scheduler_id]))[scheduler_id] == 1
                    finally:
                        reset_current_workspace(scoped)
                    await control.run_once(now=datetime.now(UTC))
                    assert await native_snapshot() == after  # Exact first-terminal replay, no duplicate event.
                    assert await asyncio.to_thread(c_job_ids) == pool_ids
                    assert await goal_runtime.read_thread_goal(saver, first.thread_id) == new_goal
                    assert (await request_worker("poll"))["claim"] is None
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                    # The late real MCP result remains available, but cannot
                    # revive the superseded goal or launch another native C.
                    await tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=30))
                    assert (await request_worker("poll"))["claim"] is None
                    async with case.sf() as session:
                        durable = await session.get(McpTaskRow, created_tasks[0]["id"])
                        assert durable.status == "completed"
                        assert durable.result == {"report": "owned dependency report"} and durable.result_preview == "owned dependency report"
                        assert durable.notification_status == "dead_letter" and durable.notified_version == 0, {
                            "status": durable.notification_status,
                            "error": durable.notification_error,
                            "trace": notification_trace,
                        }
                        assert durable.notification_run_id is None
                    assert await native_snapshot() == after
                    assert await asyncio.to_thread(c_job_ids) == pool_ids
                    assert await goal_runtime.read_thread_goal(saver, first.thread_id) == new_goal
                    assert len(admitted) == 1 and len(executed) == 1
                    assert get_current_workspace() == case.other
                    return
                now = datetime.now(UTC) + timedelta(seconds=30)
                await tasks.run_once(now=now)
                if physical_state is not None:
                    if pool_b and not physical_state.withdrawal:

                        async def before_b_stop():
                            assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                            # Completed publication is available before physical
                            # removal. Transfer C2 once, but capacity must hold it.
                            await tasks.run_once(now=now + timedelta(seconds=30))
                            assert (await request_worker("poll"))["claim"] is None
                            async with case.sf() as session:
                                occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
                                successor = await session.get(RunRow, occurrence.run_id)
                                assert occurrence.status == "running" and occurrence.run_id != first.run_id
                                assert successor.status == "pending" and successor.workspace_context_json == asdict(case.original)
                                assert occurrence.launch_accounted is True
                            physical_state.evidence["pending_c2_blocked_until_b_stop"] = True
                            physical_state.save_evidence()

                        physical_state.before_stop = before_b_stop
                    # This first real status call activates the committed B job;
                    # the physical worker must finish before result polling.
                    await physical_state.execute(created_tasks[0], first)
                    if physical_state.withdrawal:
                        assert len(admitted) == len(executed) == 1
                        assert get_current_workspace() == case.other
                        return  # Revocation proves STOP, never a successful result/continuation.
                    await tasks.run_once(now=now + timedelta(seconds=30))
                resumed = await request_worker("poll")
                diagnostic = {}
                if resumed["claim"] is None:
                    async with case.sf() as session:
                        task = await session.get(McpTaskRow, created_tasks[0]["id"])
                        source_row = await session.get(RunRow, first.run_id)
                        diagnostic = {
                            "notification_trace": notification_trace,
                            "task": {key: getattr(task, key) for key in ("status", "notification_status", "notification_error", "event_version", "notified_version", "dispatch_version", "dispatch_attempt")},
                            "source": {key: getattr(source_row, key) for key in ("status", "cancel_action")},
                            "thread_runs": [{"run_id": row.run_id, "status": row.status} for row in (await session.scalars(select(RunRow).where(RunRow.thread_id == first.thread_id))).all()],
                        }
                if revocation_phase == "notification_member":
                    assert withdrawn and resumed["claim"] is None, diagnostic
                    assert {"stage": "controller_http", "status": 403} in notification_trace, diagnostic
                    assert any(item["stage"] == "notification_sql" for item in notification_trace), diagnostic
                    assert sum(item["stage"] == "notification_sql_match" for item in notification_trace) >= 1, diagnostic
                    # Privileged fixture observation only: a revoked actor must
                    # not read through the business repository to assert denial.
                    async with case.sf() as session:
                        durable = await session.get(McpTaskRow, created_tasks[0]["id"])
                        source_row = await session.get(RunRow, first.run_id)
                        runs = (await session.scalars(select(RunRow).where(RunRow.thread_id == first.thread_id))).all()
                        member = await session.get(WorkspaceMembershipRow, (case.original.workspace_id, owner_user_id))
                        assert member.version == case.original.membership_version + 1
                        assert durable.status == "completed" and durable.event_version == 1 and durable.notified_version == 0
                        assert durable.notification_status == "dead_letter", diagnostic
                        assert durable.notification_lease_owner is durable.notification_lease_token is durable.notification_lease_expires_at is None
                        assert durable.dispatch_version is durable.notification_run_id is None
                        assert source_row.status == "success" and source_row.cancel_action is None
                        assert len(runs) == 1 and runs[0].run_id == first.run_id
                    assert len(executed) == 1
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                    assert (await request_worker("poll"))["claim"] is None
                    assert get_current_workspace() == case.other
                    return
                assert resumed["claim"] is not None, "Native MCP notification did not admit a continuation through start_run: " + json.dumps(diagnostic, sort_keys=True)
                if pool_b:
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                    physical_state.evidence["c2_shared_pool_reserved"] = True
                    physical_state.save_evidence()
                if revocation_phase == "dispatched_member":
                    pending_job = resumed["claim"]["job"]
                    async with case.sf() as session:
                        durable = await session.get(McpTaskRow, created_tasks[0]["id"])
                        pending_run_id = durable.notification_run_id
                        assert durable.notification_status == "dispatched" and pending_run_id != first.run_id
                        assert durable.notification_lease_token is None
                        changed = await session.execute(
                            update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == owner_user_id).values(version=WorkspaceMembershipRow.version + 1)
                        )
                        assert changed.rowcount == 1
                        await session.commit()
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1

                    async def forbidden_business(*args, **kwargs):
                        pytest.fail("Revoked dispatched settlement invoked a business read or launch")

                    monkeypatch.setattr(tasks, "_get_run", forbidden_business)
                    monkeypatch.setattr(tasks, "_launch_notification", forbidden_business)
                    monkeypatch.setattr(task_repo, "resolve_notification_authority", forbidden_business)
                    monkeypatch.setattr(services, "ensure_checkpoint_history_seeded", forbidden_business)
                    previous_io = list(io_scopes)
                    for _ in range(2):
                        await tasks.run_once(now=now + timedelta(seconds=30))
                        # Independent privileged SQL observes control state; no
                        # revoked business repository or Run accessor is used.
                        async with case.sf() as session:
                            durable = await session.get(McpTaskRow, created_tasks[0]["id"])
                            pending_run = await session.get(RunRow, pending_run_id)
                            runs = (await session.scalars(select(RunRow).where(RunRow.thread_id == first.thread_id))).all()
                            assert durable.notification_status == "dead_letter", "Revoked dispatched notification remained stranded: " + durable.notification_status
                            assert durable.notified_version == 0 and durable.event_version == 1
                            assert durable.notification_lease_owner is durable.notification_lease_token is durable.notification_lease_expires_at is None
                            assert durable.dispatch_version is durable.notification_run_id is None
                            assert pending_run.status == "pending" and pending_run.cancel_action is None
                            assert len(runs) == 2
                        assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                        retained = await asyncio.to_thread(ledger.get, pending_job["id"])
                        assert retained["physical_stopped"] is False
                    assert io_scopes == previous_io and len(executed) == 1
                    assert get_current_workspace() == case.other
                    return
                if scheduled:
                    pending_id = resumed["claim"]["job"]["native"]["run_id"]
                    async with case.sf() as session:
                        occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
                        parent_task = await session.get(ScheduledTaskRow, scheduler_id)
                        assert occurrence.run_id == pending_id and occurrence.status == "running" and occurrence.launch_accounted is True
                        assert parent_task.last_run_id == pending_id and parent_task.run_count == 1
                    assert not await scheduler_tasks.complete_run(
                        scheduler_id, user_id=owner_user_id, task_run_id=occurrence_id, run_id=first.run_id, status="success", error=None, finished_at=datetime.now(UTC), goal_verdict=first.goal_verdict
                    )
                    async with case.sf() as session:
                        assert (await session.get(ScheduledTaskRunRow, occurrence_id)).run_id == pending_id
                continuation = await execute_envelope(resumed["claim"])
                assert continuation.run_id != first.run_id and continuation.workspace_context == case.original
                assert continuation.thread_incarnation == first.thread_incarnation
                await tasks.run_once(now=now + timedelta(seconds=30))
                async with case.sf() as session:
                    durable = await session.get(McpTaskRow, created_tasks[0]["id"])
                    runs = (await session.scalars(select(RunRow).where(RunRow.thread_id == first.thread_id))).all()
                    assert durable.notification_status == "delivered" and durable.notified_version == durable.event_version
                    assert len(runs) == 2 and all(row.workspace_id == case.original.workspace_id and row.user_id == owner_user_id for row in runs)
                    assert all(row.status == "success" for row in runs)
                if scheduled:
                    for _ in range(2):
                        await control.run_once(now=datetime.now(UTC))
                        await tasks.run_once(now=now + timedelta(seconds=60))
                    async with case.sf() as session:
                        occurrence = await session.get(ScheduledTaskRunRow, occurrence_id)
                        parent_task = await session.get(ScheduledTaskRow, scheduler_id)
                        child_rows = (await session.scalars(select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == scheduler_id))).all()
                        history_rows = (await session.scalars(select(ScheduledTaskEventRow).where(ScheduledTaskEventRow.task_id == scheduler_id))).all()
                        assert len(child_rows) == 1 and occurrence.occurrence_seq == 1 and occurrence.launch_accounted is True
                        assert occurrence.status == "success" and occurrence.run_id == continuation.run_id
                        assert parent_task.status == "completed" and parent_task.run_count == 1 and parent_task.last_run_id == continuation.run_id
                        assert occurrence.workspace_context_json == parent_task.workspace_context_json == asdict(case.original)
                        assert len(history_rows) == 1 and history_rows[0].event == "task_finished"
                        assert history_rows[0].thread_id == origin["thread_id"] and history_rows[0].thread_incarnation == origin["incarnation"]
                    scoped = set_current_workspace(case.original)
                    try:
                        assert (await scheduler_tasks.automatic_runs_used_for([scheduler_id]))[scheduler_id] == 1
                    finally:
                        reset_current_workspace(scoped)
                    assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                assert len(executed) == 2 and executed[1]["created_at"] == original_goal["created_at"]
                assert executed[1]["continuation_count"] == original_goal.get("continuation_count", 0) + 1
                if physical_state is None:
                    assert io_scopes == [("submit", case.original, case.original), ("status", case.original, case.original)]
                else:
                    assert [operation for operation, _, _ in io_scopes] == ["submit", "status", "status"]
                    assert all(expected == actual == case.original for _, expected, actual in io_scopes)
                    physical_state.evidence.update(c1_run_id=first.run_id, c2_run_id=continuation.run_id, occurrence_id=occurrence_id, task_id=scheduler_id, final_occurrence_status="success", task_run_count=1)
                    physical_state.save_evidence()
                assert get_current_workspace() == case.other
                assert (await request_worker("poll"))["claim"] is None
            finally:
                reset_current_workspace(selected)
        finally:
            for record in admitted:
                if record.task is not None and not record.task.done():
                    record.task.cancel()
                    try:
                        await record.task
                    except asyncio.CancelledError:
                        pass
            if physical_state is not None:
                try:
                    await physical_state.close()
                finally:
                    task_runtime.set_mcp_task_submitter(previous_submitter)
            if foreground is not None:
                await foreground.stop()
            await central.stop_heartbeat()
            await receiver.stop_heartbeat()
            reset_current_user(principal_token)

    try:
        _in_workspace_case(native_engine, scenario, owner_user_id=owner_user_id)
    finally:
        ledger.engine.dispose()


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_installed_scheduler_dependency_transfers_original_occurrence(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, scheduled=True)


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduled_dependency_goal_replacement_preserves_new_goal(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, scheduled=True, goal_replacement=True)


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduler_revocation_settles_closed_dependency_control_only(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, scheduled=True, member_control=True)


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduler_revocation_retires_only_proven_queued_no_start(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, scheduled=True, queued_control=True)

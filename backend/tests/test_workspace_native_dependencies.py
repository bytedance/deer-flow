"""One native PostgreSQL async dependency/notification story.

The remote MCP driver is deterministic IO. This does not claim physical B or
AIO acceptance; both C admissions, SQL task/outbox and launcher are real.
"""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
@pytest.mark.parametrize("withdraw_before_receive", [False, True], ids=["normal", "notification_member"])
def test_scoped_native_dependency_notification_resumes_original_goal(native_engine, executor_engine, monkeypatch, tmp_path, withdraw_before_receive):  # noqa: F811
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
    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "owned-files"))

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("native-dependency-main", user_id=owner_user_id)
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
        node = Node(cpu_millis=4000, memory_mib=8192, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report"}, kinds={"C"})
        pool = Scheduling(ledger, nodes={"worker": node})
        secret = "native-dependency-offline-fixture-32-bytes"
        config = {"artifact_root": str(tmp_path / "dependency-pool"), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}
        dispatcher = NativeDispatchHost(central_app, pool, config, {"worker": secret})
        central_app.state.native_run_admission_host = dispatcher
        install_native_dispatch(central_app, dispatcher)
        host = NativeWorkerHost.__new__(NativeWorkerHost)
        host.app, host.secret, host.adoption_lock = worker_app, secret, asyncio.Lock()
        host.config = {"node_id": "worker"}
        notification_trace = []
        withdrawn = False
        host.executions, host.stop_tasks, host.sandbox_captures = {}, {}, {}

        async def request_worker(operation, **values):
            nonlocal withdrawn
            if operation == "notification" and withdraw_before_receive and not withdrawn:
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
        drivers.register("deterministic", DeterministicRemoteIO())
        tasks = McpTaskService(
            repository=task_repo,
            drivers=drivers,
            poll_interval_seconds=1,
            lease_seconds=120,
            max_concurrent_polls=1,
            launch_notification=lambda **kwargs: services.launch_mcp_task_notification_run(app=worker_app, **kwargs),
            get_run=receiver.get,
        )
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
                assert preserved["status"] == "active" and preserved["created_at"] == original_goal["created_at"]
                await host.stop_owned(job)
                await host.report(job, {"state": "completed", "physical_stopped": True})
                host.executions.pop(job["id"])
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                now = datetime.now(UTC) + timedelta(seconds=30)
                await tasks.run_once(now=now)
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
                if withdraw_before_receive:
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
                assert len(executed) == 2 and executed[1]["created_at"] == original_goal["created_at"]
                assert executed[1]["continuation_count"] == original_goal.get("continuation_count", 0) + 1
                assert io_scopes == [("submit", case.original, case.original), ("status", case.original, case.original)]
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
            await central.stop_heartbeat()
            await receiver.stop_heartbeat()
            reset_current_user(principal_token)

    try:
        _in_workspace_case(native_engine, scenario, owner_user_id=owner_user_id)
    finally:
        ledger.engine.dispose()

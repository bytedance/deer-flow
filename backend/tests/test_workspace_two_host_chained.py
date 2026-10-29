"""Opt-in two-host chained main: one scheduled occurrence drives C1, which
submits a real B through the controller's MCP HTTP endpoint; the worker
executes B through the shared pool over real TCP; the signed notification
travels back over TCP and the controller launches C2, which resumes from the
shared PostgreSQL checkpoint and reads the real published report.

All three channels are real VPC TCP: native dispatch, the B worker RPC and the
MCP submission HTTP. The deterministic graph and the same-host publication root
remain slice boundaries (no AIO execution, no cross-host NAS, no revocation).
"""

import asyncio
import base64
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("TENANT_TWO_HOST_ROLE") not in {"chained-controller", "chained-worker"}, reason="dedicated two-host chained opt-in required"),
]

# The scheduled persistence packages only import cleanly tasks-before-runs;
# pre-loading that order at module scope immunizes the whole process (the
# scheduler service import would otherwise trigger the cycle first).
import importlib as _importlib  # noqa: E402

_importlib.import_module("deerflow.persistence.scheduled_tasks.sql")  # noqa: E402
_importlib.import_module("deerflow.persistence.scheduled_task_runs.sql")  # noqa: E402

ROLE = os.environ.get("TENANT_TWO_HOST_ROLE")
NATIVE_PORT = int(os.environ.get("TENANT_TWO_HOST_NATIVE_PORT", "8022"))
SCHEDULER_ID = "two-host-chained-task"
ORIGIN_THREAD = "two-host-slice-two-thread"


def _require_env(names):
    missing = [name for name in names if not os.environ.get(name)]
    assert not missing, f"two-host role {ROLE} requires env {missing}"


def test_two_host_chained_main():
    if ROLE == "chained-controller":
        asyncio.run(_chained_controller())
    else:
        asyncio.run(_chained_worker())


def _workspace_context():
    from deerflow.authz.workspace import WorkspaceContext

    return WorkspaceContext(
        workspace_id=os.environ["TENANT_TWO_HOST_WORKSPACE_ID"],
        actor_user_id=os.environ["TENANT_TWO_HOST_OWNER"],
        membership_version=1,
        policy_version=1,
    )


def _assembly(saver, *, worker_id):
    import importlib

    _tasks_sql = importlib.import_module("deerflow.persistence.scheduled_tasks.sql")
    _runs_sql = importlib.import_module("deerflow.persistence.scheduled_task_runs.sql")

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.scheduled_task_events.sql import ScheduledTaskEventRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.runtime import RunManager
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.stream_bridge.redis import RedisStreamBridge

    engine = create_async_engine(os.environ["TENANT_TWO_HOST_NATIVE_ASYNC_URL"])
    sf = async_sessionmaker(engine, expire_on_commit=False)
    threads = ThreadMetaRepository(sf, workspace_required=True)
    run_store = RunRepository(sf, workspace_required=True)
    task_repo = McpTaskRepository(sf, workspace_required=True)
    manager = RunManager(run_store, worker_id=worker_id, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
    events = DbRunEventStore(sf, workspace_required=True)
    bridge = RedisStreamBridge(redis_url=os.environ["TENANT_TWO_HOST_REDIS_URL"])
    app = FastAPI()
    app.state.run_manager, app.state.run_store = manager, run_store
    app.state.thread_store, app.state.mcp_task_repo = threads, task_repo
    app.state.stream_bridge, app.state.checkpointer, app.state.store = bridge, saver, None
    app.state.run_event_store = events
    app.state.project_repo = ProjectRepository(sf, workspace_required=True)
    app.state.project_document_repo = ProjectDocumentRepository(sf, workspace_required=True)
    app.state.scheduled_task_repo = _tasks_sql.ScheduledTaskRepository(sf, run_repository=run_store, workspace_required=True)
    app.state.scheduled_task_run_repo = _runs_sql.ScheduledTaskRunRepository(sf, run_repository=run_store, workspace_required=True)
    app.state.scheduled_task_event_repo = ScheduledTaskEventRepository(sf, workspace_required=True)
    return dict(app=app, engine=engine, sf=sf, threads=threads, run_store=run_store, task_repo=task_repo, manager=manager, events=events, users=SQLiteUserRepository(sf), tasks_sql=_tasks_sql)


def _shared_saver():
    from types import SimpleNamespace

    from deerflow.runtime.checkpointer.async_provider import _async_checkpointer_from_database

    config = SimpleNamespace(backend="postgres", postgres_url=os.environ["TENANT_TWO_HOST_NATIVE_ASYNC_URL"], postgres_schema=None)
    return _async_checkpointer_from_database(config)


def _graph_builder(saver, tools_registry):
    """Deterministic chained C graph: submit B once, then deliver the report."""
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph

    from deerflow.agents.thread_state import ThreadState

    async def plan(state):
        if tools_registry["created"]:
            return {"messages": [AIMessage(content="Inspect the completed original execution")]}
        return {"messages": [AIMessage(content="", tool_calls=[{"name": tools_registry["tool"].name, "args": tools_registry["arguments"], "id": "real-b-submit", "type": "tool_call"}])]}

    async def answer(state):
        from deerflow.mcp.tasks import TaskStatus

        task_repo = tools_registry["task_repo"]
        created = tools_registry["created"]
        if not created:
            return {"messages": [AIMessage(content="Waiting for the owned asynchronous report")], "title": "Owned dependency report"}
        owner, thread = tools_registry["owner"], tools_registry["thread"]
        completed = await task_repo.get(created[0]["id"], user_id=owner, thread_id=thread)
        if completed["status"] != TaskStatus.COMPLETED.value:
            return {"messages": [AIMessage(content="Waiting for the real Docker report")], "title": "Owned dependency report"}
        publication = tools_registry["publication"]
        report = (publication / completed["remote_task_id"] / "files" / "report.md").read_text()
        result = json.loads((publication / completed["remote_task_id"] / "result.json").read_bytes())
        assert report == "two host owned dependency report" and result["stdout"] == report and result["exit_code"] == 0
        return {"messages": [AIMessage(content="Delivered " + report)], "title": "Owned dependency report"}

    builder = StateGraph(ThreadState, context_schema=dict)
    builder.add_node("plan", plan)
    builder.add_node("tools", tools_registry["tool_node"])
    builder.add_node("answer", answer)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", lambda state: "tools" if state["messages"][-1].tool_calls else "answer")
    builder.add_edge("tools", "answer")
    builder.add_edge("answer", END)
    return builder.compile(checkpointer=saver)


async def _chained_controller():
    from dataclasses import replace

    import sqlalchemy as sa
    import uvicorn
    from ecs_executor.agent_dispatch import NativeDispatchHost, install_native_dispatch
    from ecs_executor.job_store import JobStore
    from ecs_executor.jobs import ExecutionJobs, ExecutionProfile
    from ecs_executor.mcp_server import create_app
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import upgrade_schema
    from langchain_core.messages import HumanMessage

    from app.gateway import deps, services
    from app.gateway.native_admission import make_native_snapshot
    from app.gateway.run_models import RunCreateRequest
    from app.scheduler.service import ScheduledTaskService
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.runtime import RunContext
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    _require_env(
        [
            "TENANT_TWO_HOST_NATIVE_URL",
            "TEST_EXECUTOR_POSTGRES_URL",
            "TENANT_TWO_HOST_REDIS_URL",
            "TENANT_TWO_HOST_OWNER",
            "TENANT_TWO_HOST_WORKSPACE_ID",
            "TENANT_TWO_HOST_WORKER_CREDENTIAL",
            "TENANT_TWO_HOST_ARTIFACT_ROOT",
            "TENANT_TWO_HOST_WORKSPACE_ROOT",
            "TEST_SCOPE_EXECUTION_IMAGE",
            "TEST_SCOPE_EVIDENCE",
        ]
    )
    owner = os.environ["TENANT_TWO_HOST_OWNER"]
    context = _workspace_context()
    evidence_path = Path(os.environ["TEST_SCOPE_EVIDENCE"])
    pool_root = Path(os.environ["TENANT_TWO_HOST_ARTIFACT_ROOT"]).resolve()
    workspace_root = Path(os.environ["TENANT_TWO_HOST_WORKSPACE_ROOT"]).resolve()
    image = os.environ["TEST_SCOPE_EXECUTION_IMAGE"]
    executor_engine = sa.create_engine(os.environ["TEST_EXECUTOR_POSTGRES_URL"])
    upgrade_schema(executor_engine)
    evidence = {"scope": "two-host-chained", "role": "chained-controller", "port": NATIVE_PORT}
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def run_session():
        async with _shared_saver() as saver:
            assembly = _assembly(saver, worker_id="two-host-central")
            try:
                yield saver, assembly
            finally:
                await assembly["engine"].dispose()

    async with run_session() as (saver, assembly):
        central_app = assembly["app"]
        b_store = JobStore(os.environ["TEST_EXECUTOR_POSTGRES_URL"])
        node = Node(cpu_millis=2000, memory_mib=3542, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report", "small"}, kinds={"B", "C"})
        pool = Scheduling(b_store, nodes={"worker": node})
        secret = b"synthetic-two-host-chained-key-at-least-32-bytes"
        jobs = ExecutionJobs(
            b_store,
            secret=secret,
            audience="B",
            profiles={"small": ExecutionProfile(image=image)},
            user_profiles={owner: {"small"}},
            artifact_root=pool_root,
            workspace_root=workspace_root,
            metadata_database_url=os.environ["TENANT_TWO_HOST_NATIVE_URL"],
            workspace_required=True,
            native_server_name="ecs",
            staged_ttl_seconds=60,
        )
        from deerflow.authz.workspace import reset_current_workspace, set_current_workspace

        upload_token = set_current_workspace(context)
        try:
            upload_dir = jobs.publication.paths.sandbox_uploads_dir("two-host-chained-thread", user_id=owner)
        finally:
            reset_current_workspace(upload_token)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / "program.txt").write_bytes(b"two host owned dependency report")
        native_url = os.environ["TENANT_TWO_HOST_NATIVE_URL"]

        central_app = create_app(jobs, pool=pool, worker_credentials={"worker": os.environ["TENANT_TWO_HOST_WORKER_CREDENTIAL"]}, user_credentials={owner: "original-owner-credential"}, discovery_credential="discovery-only")
        for key, value in assembly.items():
            if key not in ("app", "engine"):
                setattr(central_app.state, key if key != "tasks_sql" else "tasks_sql", value)
        central_app.state.run_manager, central_app.state.run_store = assembly["manager"], assembly["run_store"]
        central_app.state.thread_store, central_app.state.mcp_task_repo = assembly["threads"], assembly["task_repo"]
        central_app.state.stream_bridge, central_app.state.checkpointer = assembly["app"].state.stream_bridge, saver
        central_app.state.run_event_store = assembly["events"]
        central_app.state.project_repo = assembly["app"].state.project_repo
        central_app.state.project_document_repo = assembly["app"].state.project_document_repo
        central_app.state.scheduled_task_repo = assembly["app"].state.scheduled_task_repo
        central_app.state.scheduled_task_run_repo = assembly["app"].state.scheduled_task_run_repo
        central_app.state.scheduled_task_event_repo = assembly["app"].state.scheduled_task_event_repo

        configuration = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
        ctx = RunContext(checkpointer=saver, thread_store=assembly["threads"], mcp_task_repo=assembly["task_repo"], event_store=assembly["events"], app_config=configuration, on_dependency_wait=None)
        original_get_run_context = services.get_run_context
        services.get_run_context = lambda request: ctx
        original_repo, original_provider = deps._cached_repo, deps._cached_local_provider
        deps._cached_repo = assembly["users"]
        from app.gateway.auth.local_provider import LocalAuthProvider

        deps._cached_local_provider = LocalAuthProvider(assembly["users"])
        principal = await deps.get_local_provider().get_user(owner)
        principal_token = set_current_user(principal)
        for route in list(central_app.routes):
            route_app = getattr(route, "app", None)
            manager = getattr(route_app, "session_manager", None)
            if manager is not None:
                # VPC-private fixture: match the SDK's backwards-compatible
                # default (no DNS-rebind checks) instead of the FastMCP
                # default allowlist, which rejects the private Host header.
                manager.security_settings = None
        dispatcher = NativeDispatchHost(
            central_app,
            pool,
            {"artifact_root": str(pool_root), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}},
            {"worker": os.environ["TENANT_TWO_HOST_WORKER_CREDENTIAL"]},
        )
        central_app.state.native_run_admission_host = dispatcher
        install_native_dispatch(central_app, dispatcher)
        from types import SimpleNamespace

        request = SimpleNamespace(app=central_app, url="https://native.example.invalid/")

        async def snapshot_factory(**transport):
            return await make_native_snapshot(
                request,
                None,
                run_ctx=replace(ctx, workspace_context=context),
                body=RunCreateRequest(),
                config={"configurable": {"thread_id": transport.get("thread_id", "two-host-chained-thread")}},
                graph_input={"messages": [HumanMessage(content="Deliver this report")]},
                admitted_knowledge_scope=None,
                scope_assistant_id=None,
                scheduled_task_runtime=None,
                require_existing_thread=False,
                **transport,
            )

        services_get_launch = services.launch_scheduled_thread_run
        evidence["assembled"] = True
        evidence_path.write_text(json.dumps(evidence, indent=2))

        scheduler_tasks = central_app.state.scheduled_task_repo
        foreground = ScheduledTaskService(
            task_repo=scheduler_tasks,
            task_run_repo=central_app.state.scheduled_task_run_repo,
            launch_run=lambda **kwargs: services_get_launch(app=central_app, **kwargs),
            poll_interval_seconds=1,
            lease_seconds=120,
            max_concurrent_runs=1,
            dispatch_enabled=False,
            multi_instance=True,
        )
        central_app.state.scheduled_task_service = foreground
        await foreground.start()
        control = ScheduledTaskService(
            task_repo=scheduler_tasks,
            task_run_repo=central_app.state.scheduled_task_run_repo,
            launch_run=lambda **kwargs: services.launch_scheduled_thread_run(app=central_app, **kwargs),
            poll_interval_seconds=1,
            lease_seconds=120,
            max_concurrent_runs=1,
            multi_instance=True,
        )
        await control.start()
        now = datetime.now(UTC)
        workspace_token = set_current_workspace(context)
        await scheduler_tasks.create(
            task_id=SCHEDULER_ID,
            user_id=owner,
            thread_id=None,
            origin_thread_id=ORIGIN_THREAD,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="Two-host chained report",
            prompt="Deliver the owned asynchronous report",
            goal_objective="Deliver the owned asynchronous report",
            schedule_type="once",
            schedule_spec={"run_at": now.isoformat()},
            timezone="UTC",
            next_run_at=now,
        )
        due = await scheduler_tasks.claim_due_tasks(now=now, lease_owner=foreground._lease_owner, lease_seconds=120, limit=1)
        assert len(due) == 1 and due[0]["id"] == SCHEDULER_ID, due
        queued = await foreground.dispatch_task(due[0], now=now, trigger="scheduled")
        assert queued["outcome"] == "queued", queued
        evidence["occurrence_queued"] = True
        evidence["occurrence_id"] = queued["task_run_id"]
        evidence_path.write_text(json.dumps(evidence, indent=2))

        server = uvicorn.Server(uvicorn.Config(central_app, host="0.0.0.0", port=NATIVE_PORT, log_level="warning", lifespan="on"))
        serve = asyncio.create_task(server.serve())
        try:
            deadline = time.monotonic() + 30
            while not server.started and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            assert server.started, f"serve died: {serve.exception() if serve.done() else 'running'}"
            import httpx

            async with httpx.AsyncClient() as probe_client:
                probe = await probe_client.post(f"http://127.0.0.1:{NATIVE_PORT}/api/native-workers/worker/poll", json={}, timeout=5)
                assert probe.status_code == 403, probe.status_code
            deadline = time.monotonic() + 600
            occurrence_id = evidence["occurrence_id"]

            async def occurrence_status():
                rows = await central_app.state.scheduled_task_run_repo.list_by_task(SCHEDULER_ID)
                for row in rows:
                    if row["id"] == occurrence_id:
                        return row.get("status")
                return None

            while time.monotonic() < deadline:
                if await occurrence_status() == "success":
                    break
                await asyncio.sleep(2.0)
            occurrence = {"status": await occurrence_status()}
            with sa.create_engine(native_url).connect() as check:
                runs = check.execute(sa.text("SELECT run_id,status FROM runs ORDER BY created_at")).fetchall()
                checkpoints = check.execute(sa.text("SELECT count(*) FROM checkpoints")).scalar_one()
            with executor_engine.connect() as check:
                b_jobs = check.execute(sa.text("SELECT id, record->>'state' FROM ecs_execution_jobs WHERE namespace IS NOT NULL")).fetchall()
            evidence.update(occurrence_status=occurrence.get("status"), runs=[list(row) for row in runs], shared_checkpoints=checkpoints, b_jobs=[[row[0], row[1]] for row in b_jobs])
            evidence_path.write_text(json.dumps(evidence, indent=2))
            assert occurrence.get("status") == "success", occurrence
            assert len(runs) >= 2 and all(row[1] == "success" for row in runs), runs
            assert any(row[1] == "completed" for row in b_jobs), b_jobs
        finally:
            server.should_exit = True
            await asyncio.gather(serve, return_exceptions=True)
            await control.stop()
            await foreground.stop()
            reset_current_workspace(workspace_token)
            reset_current_user(principal_token)
            services.get_run_context = original_get_run_context
            deps._cached_repo, deps._cached_local_provider = original_repo, original_provider
            b_store.engine.dispose()
            jobs.publication.engine.dispose()
        executor_engine.dispose()


async def _chained_worker():
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeWorkerHost
    from ecs_executor.dispatch import OutboundStore
    from ecs_executor.publication import WorkspacePublication
    from ecs_executor.worker import Docker, LocalWorker
    from langchain_core.tools import tool
    from langgraph.prebuilt import ToolNode

    from app.gateway import services
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller
    from deerflow.mcp.tasks import McpTaskDriverRegistry
    from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver
    from deerflow.mcp.tools import _make_background_submit_tool
    from deerflow.runtime import RunContext
    from deerflow.runtime.runs import worker as native_worker

    _require_env(
        [
            "TENANT_TWO_HOST_NATIVE_EXECUTOR_URL",
            "TENANT_TWO_HOST_NATIVE_NODE_SECRET",
            "TENANT_TWO_HOST_NATIVE_URL",
            "TENANT_TWO_HOST_REDIS_URL",
            "TENANT_TWO_HOST_OWNER",
            "TENANT_TWO_HOST_ARTIFACT_ROOT",
            "TENANT_TWO_HOST_WORKSPACE_ROOT",
            "TEST_SCOPE_EXECUTION_IMAGE",
            "TEST_SCOPE_EVIDENCE",
        ]
    )
    owner = os.environ["TENANT_TWO_HOST_OWNER"]
    evidence_path = Path(os.environ["TEST_SCOPE_EVIDENCE"])
    pool_root = Path(os.environ["TENANT_TWO_HOST_ARTIFACT_ROOT"]).resolve()
    workspace_root = Path(os.environ["TENANT_TWO_HOST_WORKSPACE_ROOT"]).resolve()
    assert (pool_root / "pool-mount-id").is_file(), "runner must sync the controller pool mount id"
    executor_url = os.environ["TENANT_TWO_HOST_NATIVE_EXECUTOR_URL"]
    evidence = {"scope": "two-host-chained", "role": "chained-worker", "executor_url": executor_url}
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def run_session():
        async with _shared_saver() as saver:
            assembly = _assembly(saver, worker_id="two-host-chained-worker")
            try:
                yield saver, assembly
            finally:
                await assembly["engine"].dispose()

    async with run_session() as (saver, assembly):
        worker_app = assembly["app"]
        host = NativeWorkerHost(worker_app, config={"artifact_root": str(pool_root), "node_id": "worker", "credential_env": "TENANT_TWO_HOST_NATIVE_NODE_SECRET", "executor_url": executor_url})
        worker_app.state.native_run_admission_host = host

        from app.gateway import deps
        from app.gateway.auth.local_provider import LocalAuthProvider
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        configuration = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
        worker_ctx = RunContext(checkpointer=saver, thread_store=assembly["threads"], mcp_task_repo=assembly["task_repo"], event_store=assembly["events"], app_config=configuration, on_dependency_wait=host.persist_dependency_wait)
        original_get_run_context = services.get_run_context
        services.get_run_context = lambda request: worker_ctx
        original_repo, original_provider = deps._cached_repo, deps._cached_local_provider
        deps._cached_repo = assembly["users"]
        deps._cached_local_provider = LocalAuthProvider(assembly["users"])

        outcomes = iter(
            [{"satisfied": False, "blocker": "external_wait", "reason": "remote report pending", "relied_on_assumption": False}, {"satisfied": True, "blocker": "none", "reason": "owned report delivered", "relied_on_assumption": False}]
        )

        async def evaluate(*args, **kwargs):
            try:
                return next(outcomes)
            except StopIteration:
                return {"satisfied": True, "blocker": "none", "reason": "terminal", "relied_on_assumption": False}

        native_worker.create_goal_evaluator_model = lambda **kwargs: object()
        native_worker.evaluate_goal_completion = evaluate

        config = ExtensionsConfig.model_validate(
            {
                "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"],
                "mcpServers": {
                    "ecs": {
                        "type": "http",
                        "url": executor_url + "/mcp",
                        "headers": {"Authorization": "Bearer discovery-only"},
                        "user_auth": {"enabled": True, "on_missing": "deny", "users": {owner: "Bearer original-owner-credential"}},
                        "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                    }
                },
            }
        )
        import ecs_executor.interceptor as interceptor_module

        original_interceptor_config = interceptor_module.get_extensions_config
        interceptor_module.get_extensions_config = lambda: config
        for key, value in {"SERVER": "ecs", "SUBMIT_TOOL": "submit", "STATUS_TOOL": "status", "CANCEL_TOOL": "cancel", "AUDIENCE": "B", "SECRET": "synthetic-two-host-chained-key-at-least-32-bytes"}.items():
            os.environ["ECS_EXECUTOR_SCOPE_" + key] = value

        @tool
        async def submit(request_key: str, profile: str, argv: list[str], input_refs: dict[str, dict[str, str]]) -> str:
            """Build the original research report through a durable B execution."""
            raise AssertionError("The actual ToolNode must use its native background wrapper")

        wrapped = _make_background_submit_tool(submit, server_name="ecs", task_name="execution", submit_tool="submit", status_tool="status", cancel_tool="cancel", connection_scope="deployment")
        created_tasks = []
        publication = WorkspacePublication(workspace_root=workspace_root, metadata_database_url=os.environ["TENANT_TWO_HOST_NATIVE_URL"], native_server_name="ecs")

        class CapturingDriver(OrdinaryMcpTaskDriver):
            async def submit(self, request):
                result = await super().submit(request)
                created_tasks.append({"id": result.task_id, "remote_task_id": result.remote_task_id})
                evidence["b_task_submitted_over_mcp_http"] = True
                evidence_path.write_text(json.dumps(evidence, indent=2))
                return result

        drivers = McpTaskDriverRegistry()
        drivers.register("ordinary-tools", CapturingDriver(McpTaskToolCaller(config)))
        from app.mcp_tasks.service import McpTaskService

        tasks = McpTaskService(
            repository=assembly["task_repo"],
            drivers=drivers,
            poll_interval_seconds=1,
            lease_seconds=120,
            max_concurrent_polls=1,
            launch_notification=lambda **kwargs: services.launch_mcp_task_notification_run(app=worker_app, **kwargs),
        )
        from deerflow.mcp.tasks import runtime as task_runtime

        task_runtime.set_mcp_task_submitter(tasks)
        tools_registry = {
            "created": created_tasks,
            "tool": wrapped,
            "tool_node": ToolNode([wrapped], handle_tool_errors=False),
            "arguments": {
                "request_key": "two-host-chained-report",
                "profile": "small",
                "argv": ["/bin/sh", "-c", "set -eu; cat /inputs/program.txt > /output/report.md; cat /output/report.md"],
                # Inline bytes: the scheduler uses fresh_thread_per_run, so an
                # upload in a fixed thread directory is unreachable to the run.
                "input_files": {"program.txt": base64.b64encode(b"two host owned dependency report").decode("ascii")},
                "input_refs": {},
            },
            "task_repo": assembly["task_repo"],
            "run_store": assembly["run_store"],
            "owner": owner,
            "thread": None,
            "publication": workspace_root,
        }
        original_factory = services.resolve_agent_factory

        def thread_aware_factory(assistant_id):
            def build(**kwargs):
                config = kwargs.get("config") or {}
                tools_registry["thread"] = config.get("configurable", {}).get("thread_id")

                async def capture(state, config_inner):
                    tools_registry["thread"] = config_inner.get("configurable", {}).get("thread_id") or tools_registry["thread"]
                    return state

                return _graph_builder(saver, tools_registry)

            return build

        services.resolve_agent_factory = thread_aware_factory
        store = OutboundStore(url=executor_url, node_id="worker", credential=os.environ["TENANT_TWO_HOST_NATIVE_NODE_SECRET"], artifact_root=pool_root)
        b_jobs = SimpleNamespace(store=store, artifact_root=pool_root, publication=publication, workspace_required=True, execution_authority=store.execution_authority)
        docker = Docker()
        b_worker = LocalWorker(b_jobs, docker=docker, node_id="worker")
        await host.start()
        await tasks.start()
        evidence["loops_started"] = True
        evidence_path.write_text(json.dumps(evidence, indent=2))
        b_tick = asyncio.create_task(_b_loop(b_worker, evidence, evidence_path))
        try:
            deadline = time.monotonic() + 600
            settled = False
            while time.monotonic() < deadline:
                if created_tasks:
                    task = await assembly["task_repo"].get(created_tasks[0]["id"], user_id=owner)
                    evidence["b_task_status"] = task["status"]
                    evidence_path.write_text(json.dumps(evidence, indent=2))
                if not host.executions and created_tasks and evidence.get("b_task_status") == "completed":
                    import sqlalchemy as sa

                    engine = sa.create_engine(os.environ["TENANT_TWO_HOST_NATIVE_URL"])
                    with engine.connect() as check:
                        runs = check.execute(sa.text("SELECT count(*) FROM runs WHERE status='success'")).scalar_one()
                    engine.dispose()
                    if runs >= 2:
                        settled = True
                        break
                await asyncio.sleep(2.0)
            evidence["chained_settled"] = settled
            evidence_path.write_text(json.dumps(evidence, indent=2))
            assert settled, f"chained story did not settle: {evidence}"
            assert (await docker.list_owned()) == [], "leftover B containers"
        finally:
            b_tick.cancel()
            await tasks.stop()
            await host.stop()
            services.resolve_agent_factory = original_factory
            services.get_run_context = original_get_run_context
            interceptor_module.get_extensions_config = original_interceptor_config
            deps._cached_repo, deps._cached_local_provider = original_repo, original_provider
            store.client.close()
            publication.engine.dispose()


async def _b_loop(worker, evidence, evidence_path):
    while True:
        try:
            await worker.tick()
        except Exception as exc:
            evidence["b_tick_error"] = type(exc).__name__
        await asyncio.sleep(1.0)

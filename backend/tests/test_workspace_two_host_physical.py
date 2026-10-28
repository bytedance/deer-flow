"""Opt-in real two-host B main: controller serves the worker RPC over real VPC
TCP; worker claims and executes the real B Docker through OutboundStore with no
in-process ASGI bridge.

Slice 1 boundaries (see docs/tenant-workspaces-evidence):
- controller and worker are separate real processes on separate hosts sharing
  one PostgreSQL executor ledger plus the native metadata database;
- input staging, claim, authorize, report and stop travel over real TCP;
- the controller submits through the signed native execution scope (the MCP
  HTTP layer itself is already covered by the single-host physical job);
- worker-side publication writes under its own workspace_root and records
  native metadata; the controller asserts database-level states only.
  Byte-level output reads under a shared NAS root, real C1 AIO and the C2
  continuation across hosts belong to later two-host slices.
"""

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("TENANT_TWO_HOST_ROLE") not in {"controller", "worker", "native-controller", "native-worker"}, reason="dedicated two-host opt-in required"),
]

ROLE = os.environ.get("TENANT_TWO_HOST_ROLE")
B_IMAGE = os.environ.get("TEST_SCOPE_EXECUTION_IMAGE", "")
B_ARGV = ["/bin/sh", "-c", "set -eu; cat /inputs/program.txt > /output/report.md; cat /output/report.md"]
THREAD_ID = "two-host-slice-one-thread"
RUN_ID = "11111111-1111-4111-8111-111111111111"


def _require_env(names):
    missing = [name for name in names if not os.environ.get(name)]
    assert not missing, f"two-host role {ROLE} requires env {missing}"


def test_two_host_b_main():
    if ROLE == "controller":
        asyncio.run(_controller())
    elif ROLE == "worker":
        asyncio.run(_worker())
    elif ROLE == "native-controller":
        asyncio.run(_native_controller())
    else:
        asyncio.run(_native_worker())


async def _controller():
    import sqlalchemy as sa
    import uvicorn
    from ecs_executor.job_store import JobStore
    from ecs_executor.jobs import ExecutionJobs, ExecutionProfile
    from ecs_executor.mcp_server import create_app
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import upgrade_schema
    from ecs_executor.scope import mint_execution_scope

    from deerflow.authz.workspace import WorkspaceContext

    _require_env(
        [
            "TEST_EXECUTOR_POSTGRES_URL",
            "TENANT_TWO_HOST_PORT",
            "TENANT_TWO_HOST_WORKSPACE_ROOT",
            "TENANT_TWO_HOST_ARTIFACT_ROOT",
            "TENANT_TWO_HOST_NATIVE_URL",
            "TENANT_TWO_HOST_OWNER",
            "TENANT_TWO_HOST_WORKSPACE_ID",
            "TENANT_TWO_HOST_WORKER_CREDENTIAL",
            "TEST_SCOPE_EVIDENCE",
        ]
    )
    port = int(os.environ["TENANT_TWO_HOST_PORT"])
    owner = os.environ["TENANT_TWO_HOST_OWNER"]
    workspace_id = os.environ["TENANT_TWO_HOST_WORKSPACE_ID"]
    worker_credential = os.environ["TENANT_TWO_HOST_WORKER_CREDENTIAL"]
    evidence_path = Path(os.environ["TEST_SCOPE_EVIDENCE"])
    workspace_root = Path(os.environ["TENANT_TWO_HOST_WORKSPACE_ROOT"]).resolve()
    artifact_root = Path(os.environ["TENANT_TWO_HOST_ARTIFACT_ROOT"]).resolve()
    executor_url = os.environ["TEST_EXECUTOR_POSTGRES_URL"]
    native_url = os.environ["TENANT_TWO_HOST_NATIVE_URL"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", B_IMAGE)

    engine = sa.create_engine(executor_url)
    upgrade_schema(engine)
    b_store = JobStore(executor_url)
    node = Node(cpu_millis=2000, memory_mib=3542, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"small"}, kinds={"B", "C"})
    pool = Scheduling(b_store, nodes={"worker": node})
    secret = b"synthetic-two-host-B-key-at-least-32-bytes"
    jobs = ExecutionJobs(
        b_store,
        secret=secret,
        audience="B",
        profiles={"small": ExecutionProfile(image=B_IMAGE)},
        user_profiles={owner: {"small"}},
        artifact_root=artifact_root,
        workspace_root=workspace_root,
        metadata_database_url=native_url,
        workspace_required=True,
        native_server_name="ecs",
        staged_ttl_seconds=60,
    )
    context = WorkspaceContext(workspace_id=workspace_id, actor_user_id=owner, membership_version=1, policy_version=1)
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace

    selected = set_current_workspace(context)
    try:
        upload_dir = jobs.publication.paths.sandbox_uploads_dir(THREAD_ID, user_id=owner)
    finally:
        reset_current_workspace(selected)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "program.txt").write_bytes(b"two host owned dependency report")
    args = {
        "request_key": "two-host-report",
        "profile": "small",
        "argv": B_ARGV,
        "input_files": {},
        "input_refs": {"program.txt": {"path": "uploads/program.txt", "sha256": hashlib.sha256((upload_dir / "program.txt").read_bytes()).hexdigest()}},
    }
    token = mint_execution_scope(
        secret=secret,
        audience="B",
        user_id=owner,
        thread_id=THREAD_ID,
        incarnation="two-host-epoch",
        run_id=RUN_ID,
        operation="submit",
        arguments=args,
        workspace_context=context,
    )
    submitted = jobs.submit(owner, token, args)
    job_id = submitted["task_id"]
    # The already-verified MCP submission layer creates this task row; slice 1
    # stands it in so activation exercises the real task-authority SQL.
    from dataclasses import asdict

    import sqlalchemy as sa
    from ecs_executor.scope import mint_management_scope

    from deerflow.persistence.mcp_tasks.model import McpTaskRow

    with jobs.publication.engine.begin() as connection:
        connection.execute(
            sa.insert(McpTaskRow).values(
                id="two-host-slice-task",
                user_id=owner,
                thread_id=THREAD_ID,
                thread_incarnation="two-host-epoch",
                run_id=RUN_ID,
                server_name="ecs",
                driver_name="ordinary",
                remote_task_id=job_id,
                task_name="execution",
                status="working",
                workspace_id=workspace_id,
                workspace_context_json=asdict(context),
            )
        )
    status_token = mint_management_scope(secret=secret, audience="B", user_id=owner, task_id=job_id, operation="status", workspace_context=context)
    activated = jobs.status(owner, status_token, {"task_id": job_id})
    assert activated["status"] in {"running", "queued"}, activated

    app = create_app(
        jobs,
        pool=pool,
        worker_credentials={"worker": worker_credential},
        user_credentials={owner: "original-owner-credential"},
        discovery_credential="discovery-only",
    )
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", lifespan="on"))
    serve = asyncio.create_task(server.serve())
    evidence = {"scope": "two-host-B-TCP", "role": "controller", "image": B_IMAGE, "port": port, "b_job_id": job_id, "submitted": True}
    try:
        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert server.started, "controller worker RPC did not start"
        evidence_path.write_text(json.dumps(evidence, indent=2))

        deadline = time.monotonic() + 420
        job = b_store.get(job_id)
        while job["state"] not in {"completed", "failed", "cancelled"} and time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            job = b_store.get(job_id)
        evidence.update(
            b_terminal_state=job["state"], physical_stopped=job.get("physical_stopped"), cleanup_pending=job.get("cleanup_pending"), pool_unreleased_after_terminal=(await asyncio.to_thread(pool.node_status, "worker"))["unreleased"]
        )
        evidence_path.write_text(json.dumps(evidence, indent=2))
        assert job["state"] == "completed", job
        assert job.get("physical_stopped") is True and not job.get("cleanup_pending")
        assert evidence["pool_unreleased_after_terminal"] == 0, "shared capacity was not released after the remote B stop"
        assert job.get("artifact") and job.get("native_artifact_uri"), "remote worker publication metadata missing"
    finally:
        server.should_exit = True
        await asyncio.gather(serve, return_exceptions=True)
        b_store.engine.dispose()
        engine.dispose()
        jobs.publication.engine.dispose()


async def _worker():
    from ecs_executor.dispatch import OutboundStore
    from ecs_executor.publication import WorkspacePublication
    from ecs_executor.worker import Docker, LocalWorker

    _require_env(["TENANT_TWO_HOST_URL", "TENANT_TWO_HOST_WORKER_CREDENTIAL", "TENANT_TWO_HOST_ARTIFACT_ROOT", "TENANT_TWO_HOST_WORKSPACE_ROOT", "TENANT_TWO_HOST_NATIVE_URL", "TEST_SCOPE_EVIDENCE", "TEST_SCOPE_OWNED_MANIFEST"])
    root = Path(os.environ["TENANT_TWO_HOST_ARTIFACT_ROOT"]).resolve()
    workspace_root = Path(os.environ["TENANT_TWO_HOST_WORKSPACE_ROOT"]).resolve()
    manifest, evidence_path = Path(os.environ["TEST_SCOPE_OWNED_MANIFEST"]), Path(os.environ["TEST_SCOPE_EVIDENCE"])
    assert (root / "pool-mount-id").is_file(), "runner must sync the controller pool mount id before the worker starts"
    evidence = {"scope": "two-host-B-TCP", "role": "worker", "url": os.environ["TENANT_TWO_HOST_URL"]}

    store = OutboundStore(url=os.environ["TENANT_TWO_HOST_URL"], node_id="worker", credential=os.environ["TENANT_TWO_HOST_WORKER_CREDENTIAL"], artifact_root=root)
    publication = WorkspacePublication(workspace_root=workspace_root, metadata_database_url=os.environ["TENANT_TWO_HOST_NATIVE_URL"], native_server_name="ecs")
    jobs = SimpleNamespace(store=store, artifact_root=root, publication=publication, workspace_required=True, execution_authority=store.execution_authority)
    docker = Docker()
    try:
        claimed = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            await asyncio.to_thread(store.expire_staged)
            claimed = await asyncio.to_thread(store.claim_queued)
            if claimed is not None:
                break
            await asyncio.sleep(1.0)
        assert claimed is not None, "no queued scoped B reached the real two-host pool RPC"
        assert claimed["kind"] == "B" and claimed.get("workspace_id") is not None
        manifest.write_text(json.dumps([{"id": claimed["id"], "spec_digest": claimed["spec_digest"]}]))
        evidence.update(claimed_over_real_tcp=True, b_job_id=claimed["id"])
        evidence_path.write_text(json.dumps(evidence, indent=2))
        worker = LocalWorker(jobs, docker=docker, node_id="worker")
        await worker.launch(claimed)
        deadline = time.monotonic() + 300
        latest = claimed
        while time.monotonic() < deadline:
            latest = await asyncio.to_thread(store.get, claimed["id"])
            if latest["state"] in {"completed", "failed", "cancelled"}:
                break
            await worker.tick()
            await asyncio.sleep(0.1)
        stop_deadline = time.monotonic() + 60
        while time.monotonic() < stop_deadline:
            await worker.tick()
            latest = await asyncio.to_thread(store.get, claimed["id"])
            if latest.get("physical_stopped") is True and not latest.get("cleanup_pending"):
                break
            await asyncio.sleep(0.5)
        evidence.update(b_terminal_state=latest["state"], physical_stopped=latest.get("physical_stopped"), cleanup_pending=latest.get("cleanup_pending"), report_over_real_tcp=True)
        evidence_path.write_text(json.dumps(evidence, indent=2))
        assert latest["state"] == "completed", latest
        assert latest.get("physical_stopped") is True and not latest.get("cleanup_pending")
        assert await docker.inspect("deerflow-exec-" + claimed["id"]) is None, "exact B container still present after normal stop"
        evidence["normal_stop_exact_id_absent"] = True
        evidence_path.write_text(json.dumps(evidence, indent=2))
    finally:
        store.client.close()
        publication.engine.dispose()


NATIVE_THREAD = "two-host-slice-two-thread"
NATIVE_PORT = int(os.environ.get("TENANT_TWO_HOST_NATIVE_PORT", "8022"))


def _workspace_context():
    from deerflow.authz.workspace import WorkspaceContext

    return WorkspaceContext(
        workspace_id=os.environ["TENANT_TWO_HOST_WORKSPACE_ID"],
        actor_user_id=os.environ["TENANT_TWO_HOST_OWNER"],
        membership_version=1,
        policy_version=1,
    )


def _native_assembly(saver, *, worker_id):
    """Shared controller/worker app assembly over the two-host databases."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.run_event.sql import DbRunEventStore
    from deerflow.persistence.scheduled_task_events.sql import ScheduledTaskEventRepository
    from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository
    from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

    engine = create_async_engine(os.environ["TENANT_TWO_HOST_NATIVE_ASYNC_URL"])
    sf = async_sessionmaker(engine, expire_on_commit=False)
    threads = ThreadMetaRepository(sf, workspace_required=True)
    run_store = RunRepository(sf, workspace_required=True)
    task_repo = McpTaskRepository(sf, workspace_required=True)
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.runtime.runs.manager import RunManager

    manager = RunManager(run_store, worker_id=worker_id, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
    events = DbRunEventStore(sf, workspace_required=True)
    from deerflow.runtime.stream_bridge.redis import RedisStreamBridge

    app = FastAPI()
    app.state.run_manager, app.state.run_store = manager, run_store
    app.state.thread_store, app.state.mcp_task_repo = threads, task_repo
    bridge = RedisStreamBridge(redis_url=os.environ["TENANT_TWO_HOST_REDIS_URL"])
    app.state.stream_bridge, app.state.checkpointer, app.state.store = bridge, saver, None
    app.state.run_event_store = events
    app.state.project_repo = ProjectRepository(sf, workspace_required=True)
    app.state.project_document_repo = ProjectDocumentRepository(sf, workspace_required=True)
    app.state.scheduled_task_repo = ScheduledTaskRepository(sf, run_repository=run_store, workspace_required=True)
    app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(sf, run_repository=run_store, workspace_required=True)
    app.state.scheduled_task_event_repo = ScheduledTaskEventRepository(sf, workspace_required=True)
    return SimpleNamespace(app=app, engine=engine, sf=sf, threads=threads, run_store=run_store, task_repo=task_repo, manager=manager, events=events, users=SQLiteUserRepository(sf))


def _shared_saver():
    from deerflow.runtime.checkpointer.async_provider import _async_checkpointer_from_database

    config = SimpleNamespace(backend="postgres", postgres_url=os.environ["TENANT_TWO_HOST_NATIVE_ASYNC_URL"], postgres_schema=None)
    return _async_checkpointer_from_database(config)


async def _native_controller():
    """Serve native dispatch over real TCP and admit one cross-host C run."""
    from dataclasses import replace
    from types import SimpleNamespace as NS

    import sqlalchemy as sa
    import uvicorn
    from ecs_executor.agent_dispatch import NativeDispatchHost, install_native_dispatch
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import upgrade_schema
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, StateGraph

    from app.gateway import deps, services
    from app.gateway.native_admission import make_native_snapshot
    from app.gateway.run_models import RunCreateRequest
    from deerflow.runtime import RunContext
    from deerflow.agents.thread_state import ThreadState
    from deerflow.runtime import goal as goal_runtime
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
            "TEST_SCOPE_EVIDENCE",
        ]
    )
    owner = os.environ["TENANT_TWO_HOST_OWNER"]
    context = _workspace_context()
    evidence_path = Path(os.environ["TEST_SCOPE_EVIDENCE"])
    pool_root = Path(os.environ["TENANT_TWO_HOST_ARTIFACT_ROOT"]).resolve()
    executor_engine = sa.create_engine(os.environ["TEST_EXECUTOR_POSTGRES_URL"])
    upgrade_schema(executor_engine)
    evidence = {"scope": "two-host-C-native-dispatch", "role": "native-controller", "port": NATIVE_PORT}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def run_session():
        async with _shared_saver() as saver:
            assembly = _native_assembly(saver, worker_id="two-host-central")
            try:
                yield saver, assembly
            finally:
                await assembly.engine.dispose()

    async with run_session() as (saver, assembly):
        central_app = assembly.app
        original_get_run_context = services.get_run_context

        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        configuration = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
        ctx = RunContext(checkpointer=saver, thread_store=assembly.threads, mcp_task_repo=assembly.task_repo, event_store=assembly.events, app_config=configuration, on_dependency_wait=None)
        services.get_run_context = lambda request: ctx
        original_repo, original_provider = deps._cached_repo, deps._cached_local_provider
        deps._cached_repo = assembly.users
        from app.gateway.auth.local_provider import LocalAuthProvider

        deps._cached_local_provider = LocalAuthProvider(assembly.users)
        principal = await deps.get_local_provider().get_user(owner)
        principal_token = set_current_user(principal)
        try:
            builder = StateGraph(ThreadState, context_schema=dict)

            async def noop(state):
                return {"messages": []}

            builder.add_node("answer", noop)
            builder.add_edge(START, "answer")
            builder.add_edge("answer", END)
            graph = builder.compile(checkpointer=saver)
            goal = goal_runtime.build_goal_state("Deliver the two-host native report")
            await graph.aupdate_state({"configurable": {"thread_id": NATIVE_THREAD}}, {"goal": goal}, as_node="answer")
            source = await assembly.manager.create_or_reject(NATIVE_THREAD, user_id=owner)

            node = Node(cpu_millis=2000, memory_mib=3542, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report", "small"}, kinds={"B", "C"})
            pool = Scheduling(JobStore(os.environ["TEST_EXECUTOR_POSTGRES_URL"]), nodes={"worker": node})
            config = {"artifact_root": str(pool_root), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}
            dispatcher = NativeDispatchHost(central_app, pool, config, {"worker": os.environ["TENANT_TWO_HOST_WORKER_CREDENTIAL"]})
            central_app.state.native_run_admission_host = dispatcher
            install_native_dispatch(central_app, dispatcher)

            request = NS(app=central_app, url="https://native.example.invalid/")

            async def snapshot_factory(**transport):
                return await make_native_snapshot(
                    request,
                    source,
                    run_ctx=replace(ctx, workspace_context=context),
                    body=RunCreateRequest(),
                    config={"configurable": {"thread_id": NATIVE_THREAD}},
                    graph_input={"messages": [HumanMessage(content="Deliver this report")]},
                    admitted_knowledge_scope=None,
                    scope_assistant_id=None,
                    scheduled_task_runtime=None,
                    require_existing_thread=True,
                    **transport,
                )

            admitted = await dispatcher.admit_native(source, snapshot_factory)
            assert admitted, "native dispatch admission was rejected"
            evidence.update(admitted_native=True, source_run_id=source.run_id)
            evidence_path.write_text(json.dumps(evidence, indent=2))

            server = uvicorn.Server(uvicorn.Config(central_app, host="0.0.0.0", port=NATIVE_PORT, log_level="warning", lifespan="off"))
            serve = asyncio.create_task(server.serve())
            try:
                deadline = time.monotonic() + 30
                while not server.started and time.monotonic() < deadline:
                    await asyncio.sleep(0.1)
                assert server.started
                deadline = time.monotonic() + 300
                row = await assembly.run_store.get(source.run_id, user_id=owner)
                while row.get("status") not in {"success", "error", "interrupted", "cancelled"} and time.monotonic() < deadline:
                    await asyncio.sleep(1.0)
                    row = await assembly.run_store.get(source.run_id, user_id=owner)
                with sa.create_engine(os.environ["TENANT_TWO_HOST_NATIVE_URL"]).connect() as check:
                    checkpoints = check.execute(sa.text("SELECT count(*) FROM checkpoints")).scalar_one()
                evidence.update(run_status=row.get("status"), shared_checkpoints=checkpoints, run_completed_over_tcp=True)
                evidence_path.write_text(json.dumps(evidence, indent=2))
                assert row.get("status") == "success", row
                assert checkpoints >= 1, "no cross-process checkpoint landed in the shared database"
            finally:
                server.should_exit = True
                await asyncio.gather(serve, return_exceptions=True)
        finally:
            reset_current_user(principal_token)
            services.get_run_context = original_get_run_context
            deps._cached_repo, deps._cached_local_provider = original_repo, original_provider
        executor_engine.dispose()


async def _native_worker():
    """Real NativeWorkerHost: poll the controller over TCP, adopt and run the C graph."""
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph

    from app.gateway import services
    from deerflow.agents.thread_state import ThreadState

    _require_env(["TENANT_TWO_HOST_NATIVE_EXECUTOR_URL", "TENANT_TWO_HOST_NATIVE_NODE_SECRET", "TENANT_TWO_HOST_NATIVE_URL", "TENANT_TWO_HOST_REDIS_URL", "TENANT_TWO_HOST_ARTIFACT_ROOT", "TEST_SCOPE_EVIDENCE"])
    evidence_path = Path(os.environ["TEST_SCOPE_EVIDENCE"])
    pool_root = Path(os.environ["TENANT_TWO_HOST_ARTIFACT_ROOT"]).resolve()
    assert (pool_root / "pool-mount-id").is_file(), "runner must sync the controller pool mount id"
    evidence = {"scope": "two-host-C-native-dispatch", "role": "native-worker", "executor_url": os.environ["TENANT_TWO_HOST_NATIVE_EXECUTOR_URL"]}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def run_session():
        async with _shared_saver() as saver:
            assembly = _native_assembly(saver, worker_id="two-host-native-worker")
            try:
                yield saver, assembly
            finally:
                await assembly.engine.dispose()

    async with run_session() as (saver, assembly):
        worker_app = assembly.app
        original_factory = services.resolve_agent_factory

        async def respond(state):
            return {"messages": [AIMessage(content="two-host native report delivered")]}

        builder = StateGraph(ThreadState, context_schema=dict)
        builder.add_node("answer", respond)
        builder.add_edge(START, "answer")
        builder.add_edge("answer", END)
        graph = builder.compile(checkpointer=saver)
        services.resolve_agent_factory = lambda assistant_id: lambda **kwargs: graph
        from ecs_executor.agent_dispatch import NativeWorkerHost

        host = NativeWorkerHost(worker_app, config={"artifact_root": str(pool_root), "node_id": "worker", "credential_env": "TENANT_TWO_HOST_NATIVE_NODE_SECRET", "executor_url": os.environ["TENANT_TWO_HOST_NATIVE_EXECUTOR_URL"]})
        worker_app.state.native_run_admission_host = host
        await host.start()
        try:
            deadline = time.monotonic() + 300
            executed = list(getattr(host, "executions", {}))
            terminal = None
            while time.monotonic() < deadline:
                executed = list(getattr(host, "executions", {}))
                if executed:
                    break
                await asyncio.sleep(1.0)
            assert executed, "worker never claimed a native envelope over real TCP"
            job_id = executed[0]
            evidence.update(claimed_native_over_tcp=True, native_job_id=job_id)
            evidence_path.write_text(json.dumps(evidence, indent=2))
            while time.monotonic() < deadline:
                terminal = host.executions.get(job_id)
                if terminal is None:
                    break
                await asyncio.sleep(1.0)
            evidence.update(execution_settled=terminal is None)
            evidence_path.write_text(json.dumps(evidence, indent=2))
            assert terminal is None, "native execution record did not settle"
            evidence["native_run_settled_over_tcp"] = True
            evidence_path.write_text(json.dumps(evidence, indent=2))
        finally:
            await host.stop()
            services.resolve_agent_factory = original_factory

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
    pytest.mark.skipif(os.environ.get("TENANT_TWO_HOST_ROLE") not in {"controller", "worker"}, reason="dedicated two-host opt-in required"),
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
    else:
        asyncio.run(_worker())


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
        assert job.get("artifact") and job["artifact"].get("uri"), "remote worker publication metadata missing"
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
        await worker.tick()
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

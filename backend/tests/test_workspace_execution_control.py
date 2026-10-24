"""Durable native revocation -> authenticated control -> actual STOP -> native task."""

import importlib.util
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_workspace_execution_wire import _exercise_native_tool_to_b
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get("ECS_EXECUTOR_SCOPE_PHYSICAL_TEST") != "1", reason="dedicated Shanghai physical CI required")]


def test_native_revocation_outbox_settles_only_after_control_stop(native_engine, executor_engine, tmp_path, monkeypatch):  # noqa: F811
    assert importlib.util.find_spec("ecs_executor.control") is not None, "durable authenticated execution control is missing"
    import httpx
    import sqlalchemy as sa
    from deerflow_extension_api import ExtensionData, ExtensionRuntimeDeps
    from ecs_executor.control import ControlRoute, ExecutionControlService
    from ecs_executor.worker import Docker, LocalWorker

    from deerflow.mcp.tasks.control import TaskControlRuntime
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository

    secret = b"synthetic-control-role-separated-secret-32-bytes"
    runtime = TaskControlRuntime()
    app_store = ExtensionData("control-main")
    app_store.set(runtime)
    manifest = Path(os.environ["TEST_SCOPE_OWNED_MANIFEST"])

    async def control(case):
        job = case.store.get(case.remote_id)
        owned = json.loads(manifest.read_text())
        owned.append({"id": job["id"], "spec_digest": job["spec_digest"]})
        manifest.write_text(json.dumps(owned))
        worker = LocalWorker(case.jobs)
        service = ExecutionControlService(
            routes={"ecs": ControlRoute(url="http://127.0.0.1:8003", audience="B/control", credential="control-only-credential", secret=secret)},
            poll_seconds=3600,
            client_factory=lambda route: httpx.AsyncClient(transport=httpx.ASGITransport(app=case.control_app), base_url=route.url, timeout=30, trust_env=False),
        )
        ref = "deerflow-exec-" + job["id"]
        try:
            await service.start(ExtensionRuntimeDeps(app_store=app_store, session_factory=case.case.sf))
            assert runtime.ready and runtime.supports("ecs")
            await worker.tick()
            assert case.store.get(job["id"])["state"] == "running"
            assert (await Docker().inspect(ref))["State"]["Running"] is True
            with native_engine.begin() as connection:
                connection.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
            workspaces = WorkspaceRepository(case.case.sf)
            await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
            await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            async with case.case.sf() as session:
                task = await session.get(McpTaskRow, case.local_id)
                outboxes = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "mcp_stop"))).all()
                assert task.cancel_requested_at is not None and task.status == "working"
                assert len(outboxes) == 1 and outboxes[0].state == "pending"
                assert outboxes[0].payload["target"]["workspace_context"] == asdict(case.original)
                operation_id = outboxes[0].operation_id
            assert not case.store.get(job["id"]).get("cancel_requested"), "native SQL transaction performed external IO"
            now = datetime.now(UTC)
            await service.run_once(now=now)
            pending = case.store.get(job["id"])
            assert pending["cancel_requested"] is True and not pending.get("physical_stopped")
            async with case.case.sf() as session:
                assert (await session.get(McpTaskRow, case.local_id)).status == "working"
                assert (await session.get(WorkspaceOperationOutboxRow, operation_id)).state != "completed"
            await worker.tick()
            assert await Docker().inspect(ref) is None
            assert case.store.get(job["id"])["physical_stopped"] is True
            await service.run_once(now=now + timedelta(seconds=2))
            async with case.case.sf() as session:
                task = await session.get(McpTaskRow, case.local_id)
                operation = await session.get(WorkspaceOperationOutboxRow, operation_id)
                assert operation.state == "completed" and task.status == "cancelled"
                assert task.result is None and task.result_artifact is None
                assert task.workspace_context_json == asdict(case.original)
                parents = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "workspace_revoke"))).all()
                assert len(parents) == 2 and all(parent.state == "pending" for parent in parents), "unimplemented resource domains were declared revoked"
            await service.run_once(now=now + timedelta(seconds=3))
            assert case.store.get(job["id"])["state"] == "cancelled"
        finally:
            await service.stop()
            observation = await Docker().inspect(ref)
            if observation is not None:
                labels = observation["Config"].get("Labels") or {}
                assert labels.get("deerflow.execution.job") == job["id"] and labels.get("deerflow.execution.spec") == job["spec_digest"]
                await Docker().checked("rm", "-f", ref)
            assert not runtime.ready

    _exercise_native_tool_to_b(
        native_engine,
        executor_engine,
        tmp_path,
        monkeypatch,
        after_queue=control,
        execution_image=os.environ["TEST_SCOPE_EXECUTION_IMAGE"],
        execution_argv=["/bin/sh", "-c", "printf private-output > /output/report.md; sleep 60"],
        control_secret=secret,
        control_credential="control-only-credential",
        control_runtime=runtime,
    )


def test_user_queued_cancel_refuses_false_proof_and_stale_settlement(native_engine, executor_engine, tmp_path, monkeypatch):  # noqa: F811
    import httpx
    import sqlalchemy as sa
    from deerflow_extension_api import ExtensionData, ExtensionRuntimeDeps
    from ecs_executor.control import HEADER, PATH, ControlRoute, ExecutionControlService, _intent, _signed, _verified

    from deerflow.authz.workspace import set_current_workspace
    from deerflow.mcp.tasks.control import McpTaskControlUnavailable, TaskControlRuntime, TaskStopReceipt
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
    from deerflow.persistence.workspaces.execution_control import WorkspaceControlRepository
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow

    secret = b"synthetic-control-role-separated-secret-32-bytes"
    runtime = TaskControlRuntime()
    app_store = ExtensionData("control-boundary")
    app_store.set(runtime)

    async def control(case):
        now = datetime.now(UTC)
        set_current_workspace(case.original)
        request = dict(task_id=case.local_id, thread_id=case.run.thread_id, user_id="owner", thread_incarnation=case.run.thread_incarnation)
        with pytest.raises(McpTaskControlUnavailable):
            await case.tasks.cancel_task(**request, now=now)
        async with case.case.sf() as session:
            assert (await session.get(McpTaskRow, case.local_id)).cancel_requested_at is None
            assert not (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "mcp_stop"))).all()
        bad_proof = True
        transport = httpx.ASGITransport(app=case.control_app)

        async def request_transport(request):
            if bad_proof:
                return httpx.Response(200, json={"status": "stopped", "physical_stopped": True})
            return await transport.handle_async_request(request)

        service = ExecutionControlService(
            routes={"ecs": ControlRoute(url="http://127.0.0.1:8003", audience="B/control", credential="control-only-credential", secret=secret)},
            poll_seconds=3600,
            client_factory=lambda route: httpx.AsyncClient(transport=httpx.MockTransport(request_transport), base_url=route.url, timeout=30, trust_env=False),
        )
        try:
            await service.start(ExtensionRuntimeDeps(app_store=app_store, session_factory=case.case.sf))
            await case.tasks.cancel_task(**request, now=now)
            await case.tasks.cancel_task(**request, now=now)
            set_current_workspace(case.other)
            repository = WorkspaceControlRepository(case.case.sf)
            claims = await repository.claim(now=now, owner="abandoned-process", servers={"ecs"})
            assert len(claims) == 1
            old_claim = claims[0]
            assert await repository.claim(now=now + timedelta(seconds=119), owner="early-peer", servers={"ecs"}) == []
            future = now + timedelta(seconds=121)
            current = (await repository.claim(now=future, owner="replacement", servers={"ecs"}))[0]
            assert current.token != old_claim.token
            body = _intent(current.operation_id, current.target)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8003", timeout=30) as client:
                headers = {"Authorization": "Bearer control-only-credential", HEADER: _signed(secret, "B/control", "stop_receipt", body)}
                assert (await client.post(PATH, json=body, headers=headers)).status_code == 409
                assert (await client.post(PATH, json=body)).status_code == 404
                assert case.store.get(case.remote_id)["state"] == "queued"
                headers[HEADER] = _signed(secret, "B/control", "stop_intent", body, now=int(datetime.now(UTC).timestamp()) - 301)
                assert (await client.post(PATH, json=body, headers=headers)).status_code == 409
            assert await repository.defer(old_claim, now=future) is False
            assert await repository.defer(current, now=future) is True
            await service.run_once(now=future + timedelta(seconds=2))
            async with case.case.sf() as session:
                task = await session.get(McpTaskRow, case.local_id)
                assert task.status == "working" and task.result is None
                assert (await session.get(WorkspaceOperationOutboxRow, current.operation_id)).state == "pending"
            assert case.store.get(case.remote_id)["state"] == "queued"
            bad_proof = False
            # Obtain a genuine receipt independently, then prove an abandoned
            # native claimant cannot use it to overwrite the current lease.
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8003", timeout=30) as client:
                response = await client.post(PATH, json=body, headers={"Authorization": "Bearer control-only-credential", HEADER: _signed(secret, "B/control", "stop_intent", body)})
                proof = _verified(response.json()["receipt"], secret, "B/control", "stop_receipt")
            assert proof["evidence"] == "not_started" and proof["physical_stopped"] is True
            receipt = TaskStopReceipt(**{key: value for key, value in proof.items() if key not in ("physical_stopped", "observed_at")}, observed_at=datetime.fromisoformat(proof["observed_at"]))
            assert await repository.settle_stop(old_claim, receipt, now=future + timedelta(seconds=3)) is False
            async with case.case.sf() as session:
                assert (await session.get(McpTaskRow, case.local_id)).status == "working"
            await service.stop()
            assert not runtime.ready
            await service.start(ExtensionRuntimeDeps(app_store=app_store, session_factory=case.case.sf))
            await service.run_once(now=future + timedelta(seconds=8))
            async with case.case.sf() as session:
                task = await session.get(McpTaskRow, case.local_id)
                operation = await session.get(WorkspaceOperationOutboxRow, current.operation_id)
                assert task.status == "cancelled" and task.result is None and task.result_artifact is None
                assert operation.state == "completed" and operation.payload["receipt"]["evidence"] == "not_started"
                assert len((await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "mcp_stop"))).all()) == 1
            assert case.store.get(case.remote_id)["state"] == "cancelled"
            assert not case.store.get(case.remote_id).get("start_intent")
        finally:
            await service.stop()

    _exercise_native_tool_to_b(native_engine, executor_engine, tmp_path, monkeypatch, after_queue=control, control_secret=secret, control_credential="control-only-credential", control_runtime=runtime)


def test_existing_terminal_without_stop_is_observed_before_native_settlement(native_engine, executor_engine, tmp_path, monkeypatch):  # noqa: F811
    import httpx
    from deerflow_extension_api import ExtensionData, ExtensionRuntimeDeps
    from ecs_executor.control import ControlRoute, ExecutionControlService
    from ecs_executor.scope import mint_management_scope
    from ecs_executor.worker import LocalWorker

    from deerflow.authz.workspace import set_current_workspace
    from deerflow.mcp.tasks.control import TaskControlRuntime
    from deerflow.persistence.mcp_tasks.model import McpTaskRow

    secret = b"synthetic-control-role-separated-secret-32-bytes"
    runtime = TaskControlRuntime()
    app_store = ExtensionData("terminal-control")
    app_store.set(runtime)

    async def control(case):
        service = ExecutionControlService(
            routes={"ecs": ControlRoute(url="http://127.0.0.1:8003", audience="B/control", credential="control-only-credential", secret=secret)},
            poll_seconds=3600,
            client_factory=lambda route: httpx.AsyncClient(transport=httpx.ASGITransport(app=case.control_app), base_url=route.url, timeout=30, trust_env=False),
        )
        try:
            token = mint_management_scope(secret=case.jobs.secret, audience="B", user_id="owner", task_id=case.remote_id, operation="cancel", workspace_context=case.original)
            case.jobs.cancel("owner", token, {"task_id": case.remote_id})
            before = case.store.get(case.remote_id)
            assert before["state"] == "cancelled" and not before.get("physical_stopped")
            await service.start(ExtensionRuntimeDeps(app_store=app_store, session_factory=case.case.sf))
            set_current_workspace(case.original)
            await case.tasks.cancel_task(task_id=case.local_id, thread_id=case.run.thread_id, user_id="owner", thread_incarnation=case.run.thread_incarnation)
            set_current_workspace(case.other)
            now = datetime.now(UTC)
            await service.run_once(now=now)
            pending = case.store.get(case.remote_id)
            assert pending.get("cleanup_pending") is True and not pending.get("physical_stopped"), "terminal state without STOP has no durable observation retry"
            async with case.case.sf() as session:
                assert (await session.get(McpTaskRow, case.local_id)).status == "working"
            await LocalWorker(case.jobs).tick()
            assert case.store.get(case.remote_id)["physical_stopped"] is True
            await service.run_once(now=now + timedelta(seconds=2))
            async with case.case.sf() as session:
                assert (await session.get(McpTaskRow, case.local_id)).status == "cancelled"
        finally:
            await service.stop()

    _exercise_native_tool_to_b(native_engine, executor_engine, tmp_path, monkeypatch, after_queue=control, control_secret=secret, control_credential="control-only-credential", control_runtime=runtime)

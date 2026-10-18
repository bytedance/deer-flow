"""Native C staging preserves the original SQL admission across UI selection."""

import asyncio
from contextvars import Context
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("trigger", ["normal", "member", "queued_member", "assigned_member"])
def test_native_c_dispatch_preserves_original_workspace(native_engine, executor_engine, trigger):  # noqa: F811
    from ecs_executor.agent_dispatch import NativeDispatchHost
    from ecs_executor.job_store import _JOBS, JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import upgrade_schema
    from ecs_executor.scope import arguments_sha256
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver

    from app.gateway.native_admission import make_native_snapshot
    from app.gateway.run_models import RunCreateRequest
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config.app_config import AppConfig
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.run_control import NativeRunStopTarget
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager
    from deerflow.runtime.stream_bridge.base import END_SENTINEL
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    upgrade_schema(executor_engine)
    ledger = JobStore(executor_engine.url.render_as_string(hide_password=False))

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("native-c-stage", user_id="owner")
        store = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store, worker_id="native-central", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        user_token = set_current_user(principal)
        try:
            record = await manager.create_or_reject("native-c-stage", user_id="owner", kwargs={"input": {"messages": [{"role": "user", "content": "research report"}]}})
            config = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
            ctx = RunContext(checkpointer=MemorySaver(), thread_store=threads, workspace_context=case.original, app_config=config)
            app = SimpleNamespace(state=SimpleNamespace(thread_store=threads, run_manager=manager, run_store=store, stream_bridge=MemoryStreamBridge()))
            request = SimpleNamespace(app=app, url="https://deerflow.example.invalid/")
            node = Node(cpu_millis=4000, memory_mib=8192, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report"}, kinds={"C"})
            pool = Scheduling(ledger, nodes={"worker": node})
            host = NativeDispatchHost(app, pool, {"native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}, {"worker": "native-node-offline-fixture-32-bytes"})
            snapshots = []

            async def revoke_member():
                async with case.sf() as session:
                    await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                    await session.commit()
                spaces = WorkspaceRepository(case.sf)
                await spaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await spaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)

            async def snapshot_factory(**transport):
                value = await make_native_snapshot(
                    request,
                    record,
                    run_ctx=ctx,
                    body=RunCreateRequest(),
                    config={"configurable": {"thread_id": record.thread_id}},
                    graph_input={"messages": [HumanMessage(content="research report")]},
                    admitted_knowledge_scope=None,
                    scope_assistant_id=None,
                    scheduled_task_runtime=None,
                    require_existing_thread=True,
                    **transport,
                )
                snapshots.append(value)
                if trigger == "member":
                    await revoke_member()
                return value

            selected = set_current_workspace(case.other)
            try:
                if trigger == "member":
                    with pytest.raises(WorkspaceAccessDenied):
                        await host.admit_native(record, snapshot_factory)
                else:
                    assert await host.admit_native(record, snapshot_factory)
                assert get_current_workspace() == case.other
            finally:
                reset_current_workspace(selected)
            snapshot = snapshots[0]
            assert snapshot["workspace_context"] == asdict(case.original)
            assert snapshot["workspace_id"] == case.original.workspace_id
            assert snapshot["incarnation"] == record.thread_incarnation
            job = await asyncio.to_thread(ledger.find_request, namespace="native-C", request_key=record.run_id, spec_digest=arguments_sha256(snapshot))
            assert job["workspace_context"] == asdict(case.original)
            assert job["workspace_id"] == case.original.workspace_id
            assert job["native"] == snapshot
            if trigger == "member":
                assert job["state"] == "staged" and not job["physical_stopped"]
                assert not record.ownership_lost and record.task is None
                async with case.sf() as session:
                    raw = await session.get(RunRow, record.run_id)
                    assert raw.owner_worker_id == "native-central"
                assert await asyncio.to_thread(pool.claim, "worker", "old-worker", kind="C") is None
                return
            assert job["state"] == "queued"
            assert record.ownership_lost and record.task is None
            durable = await store.get(record.run_id, user_id="owner")
            assert durable["owner_worker_id"] == "dispatch:" + job["id"]
            assert durable["workspace_context_json"] == asdict(case.original)
            assert durable["thread_incarnation"] == record.thread_incarnation
            # Rebuild dispatcher process-local state and run it without a UI
            # workspace or principal. It must renew the original queued lease.
            app.state.run_manager = RunManager(store, worker_id="native-central-restarted", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
            restarted = NativeDispatchHost(app, pool, host.config, host.credentials)
            if trigger in ("queued_member", "assigned_member"):
                if trigger == "assigned_member":
                    job = await asyncio.to_thread(ledger.mutate, job["id"], lambda value: value.update(state="starting", node_id="worker", worker_owner="assigned-owner", generation="assignment-fixture", attempt=1))
                await revoke_member()
                await asyncio.wait_for(asyncio.create_task(restarted.maintain(), context=Context()), 15)
                after = await asyncio.to_thread(ledger.get, job["id"])
                assert after["cancel_requested"]
                async with case.sf() as session:
                    raw = await session.get(RunRow, record.run_id)
                    target = NativeRunStopTarget.from_row(raw)
                    lifetime = await session.get(WorkspaceOperationOutboxRow, target.execution_id)
                    stop = await session.get(WorkspaceOperationOutboxRow, target.operation_id)
                    if trigger == "assigned_member":
                        assert after["state"] == "starting" and not after["physical_stopped"]
                        assert raw.status == "pending" and lifetime.state == "open" and stop.state == "pending"
                        return
                    assert after["state"] == "cancelled" and after["physical_stopped"] and not after["settlement_pending"]
                    assert raw.status == "interrupted" and lifetime.state == "completed" and stop.state == "completed"
                    assert lifetime.payload["receipt"]["evidence"] == "native_not_started"
                stream = app.state.stream_bridge.subscribe(record.run_id)
                try:
                    assert await asyncio.wait_for(anext(stream), 2) is END_SENTINEL
                finally:
                    await stream.aclose()
                # A fresh host retries control without replaying graph or work.
                replay = NativeDispatchHost(app, pool, host.config, host.credentials)
                await asyncio.wait_for(asyncio.create_task(replay.maintain(), context=Context()), 15)
                assert await asyncio.to_thread(ledger.get, job["id"]) == after
                return
            await asyncio.wait_for(asyncio.create_task(restarted.maintain(), context=Context()), 15)
            renewed = await store.get(record.run_id, user_id="owner")
            assert datetime.fromisoformat(renewed["lease_expires_at"]) > datetime.fromisoformat(durable["lease_expires_at"])
            assert renewed["owner_worker_id"] == durable["owner_worker_id"]
            assert not app.state.run_manager._runs
            assert not await store.finish_dispatch_pending(record.run_id, owner_worker_id=durable["owner_worker_id"], error="legacy path cannot settle a scoped admission")
            with ledger.engine.connect() as connection:
                identity = connection.execute(sa.select(_JOBS.c.execution_identity).where(_JOBS.c.id == job["id"])).scalar_one()
                assert identity["kind"] == "C" and identity["workspace_id"] == case.original.workspace_id
                affinity = connection.execute(sa.text("SELECT workspace_id FROM ecs_native_affinities WHERE thread_id=:thread"), {"thread": record.thread_id}).scalar_one()
                assert affinity == case.original.workspace_id
            for field, value in (
                ("workspace_context", asdict(case.original) | {"membership_version": case.original.membership_version + 1}),
                ("native", deepcopy(snapshot) | {"execution": {"input": {"messages": []}}}),
                ("node_budget", job["node_budget"] | {"resident_cpu_millis": 1}),
                ("affinity_node", "other-worker"),
            ):
                with pytest.raises(ValueError, match="identity"):
                    await asyncio.to_thread(ledger.mutate, job["id"], lambda row: row.update({field: value}))
                assert await asyncio.to_thread(ledger.get, job["id"]) == job
            stripped = {key: value for key, value in deepcopy(job).items() if key not in {"workspace_id", "workspace_context"}}
            with pytest.raises(ValueError, match="identity"):
                await asyncio.to_thread(ledger.create, namespace="native-C", request_key="scope-stripped", spec_digest=job["spec_digest"], record=stripped)
            # Physical claim is the next explicit integration boundary. The old
            # unscoped pool must never execute this newly attributed admission.
            assert await asyncio.to_thread(pool.claim, "worker", "old-worker", kind="C") is None
        finally:
            reset_current_user(user_token)

    try:
        _in_workspace_case(native_engine, scenario)
    finally:
        ledger.engine.dispose()

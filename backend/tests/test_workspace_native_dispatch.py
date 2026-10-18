"""Native C staging preserves the original SQL admission across UI selection."""

import asyncio
from contextvars import Context
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
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


@pytest.mark.parametrize("withdrawn", [False, True])
def test_native_c_receiver_uses_original_sql_authority(native_engine, monkeypatch, withdrawn):  # noqa: F811
    from ecs_executor.agent_dispatch import _arguments, sign_native_launch, verify_native_launch
    from ecs_executor.scope import mint_execution_scope
    from langgraph.checkpoint.memory import MemorySaver

    from app.gateway import services
    from app.gateway.native_admission import adopt_native_run
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow
    from deerflow.persistence.workspaces.run_control import NativeRunStopTarget
    from deerflow.runtime import RunContext, RunManager
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("receiver-private", user_id="owner")
        store = RunRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120)
        central = RunManager(store, worker_id="central", run_ownership_config=ownership)
        worker = RunManager(store, worker_id="receiver", run_ownership_config=ownership)
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        owner_token = set_current_user(principal)
        try:
            record = await central.create_or_reject("receiver-private", user_id="owner")
            target = NativeRunStopTarget.from_record(record)
            native = {
                "run_id": record.run_id,
                "user_id": record.user_id,
                "thread_id": record.thread_id,
                "incarnation": record.thread_incarnation,
                "assistant_id": record.assistant_id,
                "kwargs": record.kwargs,
                "metadata": record.metadata,
                "goal": None,
                "workspace_id": case.original.workspace_id,
                "workspace_context": asdict(case.original),
                "created_at": target.created_at,
                "execution": {"input": None, "body": {}, "config": {}, "conversation_sources": [], "knowledge_scope": None, "scope_assistant_id": None, "scheduled_task_runtime": None, "dependency_continuation": None},
            }
            job = {"id": "receiver-job", "node_id": "worker", "generation": "assignment", "worker_owner": "worker-owner", "native": native, "workspace_id": case.original.workspace_id, "workspace_context": asdict(case.original)}
            await central.handoff_pending(record.run_id, owner_worker_id="dispatch:" + job["id"])
            app = SimpleNamespace(state=SimpleNamespace(run_manager=worker, run_store=store))
            ctx = RunContext(checkpointer=MemorySaver(), thread_store=threads)
            monkeypatch.setattr(services, "get_run_context", lambda request: ctx)

            async def owner(*args, **kwargs):
                return principal

            monkeypatch.setattr(services, "resolve_trusted_internal_owner_for_attribution", owner)
            monkeypatch.setattr(services, "resolve_agent_factory", lambda assistant_id: object())
            observed = []

            async def execute(request, adopted, **kwargs):
                observed.append((get_current_workspace(), kwargs["run_ctx"].workspace_context, adopted.workspace_context))

            monkeypatch.setattr(services, "execute_admitted_native_run", execute)
            secret = "native-node-offline-fixture-32-bytes"
            selected = set_current_workspace(case.other)
            try:
                legacy = mint_execution_scope(
                    secret=secret.encode(), audience="worker", user_id="owner", thread_id=record.thread_id, incarnation=record.thread_incarnation, run_id=record.run_id, operation="native_launch", arguments=_arguments(job)
                )
                with pytest.raises(ValueError, match="capability"):
                    verify_native_launch(job, legacy, secret)
                stripped = {key: value for key, value in job.items() if key not in ("workspace_id", "workspace_context")}
                stripped["native"] = {key: value for key, value in native.items() if key not in ("workspace_id", "workspace_context")}
                with pytest.raises(ValueError, match="capability"):
                    await adopt_native_run(app, stripped, sign_native_launch(stripped, secret), secret)
                token = sign_native_launch(job, secret, workspace_context=case.original)
                with pytest.raises(ValueError, match="capability"):
                    verify_native_launch(job, token, secret)
                if withdrawn:
                    async with case.sf() as session:
                        await session.execute(
                            sa.update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == "owner").values(version=WorkspaceMembershipRow.version + 1)
                        )
                        await session.commit()
                    with pytest.raises((ValueError, PermissionError)):
                        await adopt_native_run(app, job, token, secret)
                    assert not observed and not worker._runs
                else:
                    from deerflow.persistence.run.model import RunRow
                    from deerflow.runtime.runs.manager import RunStartupError

                    with native_engine.connect() as connection:
                        original_lease = connection.execute(sa.select(RunRow.lease_expires_at).where(RunRow.run_id == record.run_id)).scalar_one()

                    def expire_before_cas():
                        with native_engine.begin() as connection:
                            connection.execute(sa.update(RunRow).where(RunRow.run_id == record.run_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))

                    with pytest.raises(RunStartupError):
                        await adopt_native_run(app, job, token, secret, admission_check=expire_before_cas)
                    assert not observed and not worker._runs
                    with native_engine.begin() as connection:
                        connection.execute(sa.update(RunRow).where(RunRow.run_id == record.run_id).values(lease_expires_at=original_lease))
                    adopted = await adopt_native_run(app, job, token, secret)
                    await adopted.task
                    assert observed == [(case.original, case.original, case.original)]
                    assert adopted.owner_worker_id == "receiver"
                assert get_current_workspace() == case.other
            finally:
                reset_current_workspace(selected)
        finally:
            reset_current_user(owner_token)

    _in_workspace_case(native_engine, scenario)


@pytest.mark.parametrize("withdrawn", [False, True])
def test_native_c_pool_dispatch_executes_original_run(native_engine, executor_engine, monkeypatch, tmp_path, withdrawn):  # noqa: F811
    import httpx
    from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost, install_native_dispatch
    from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import SCHEMA_REVISION, upgrade_schema
    from fastapi import FastAPI
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from app.gateway import services
    from app.gateway.native_admission import adopt_native_run, make_native_snapshot
    from app.gateway.run_models import RunCreateRequest
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config.app_config import AppConfig
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    upgrade_schema(executor_engine)
    ledger = JobStore(executor_engine.url.render_as_string(hide_password=False))

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("pool-native-private", user_id="owner")
        store = RunRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120)
        central = RunManager(store, worker_id="pool-central", run_ownership_config=ownership)
        worker = RunManager(store, worker_id="pool-receiver", run_ownership_config=ownership)
        bridge = MemoryStreamBridge()
        ctx = RunContext(
            checkpointer=MemorySaver(),
            thread_store=threads,
            event_store=DbRunEventStore(case.sf, workspace_required=True),
            workspace_context=case.original,
            app_config=AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")),
        )
        app = FastAPI()
        app.state.run_manager, app.state.run_store, app.state.thread_store, app.state.stream_bridge = central, store, threads, bridge
        request = SimpleNamespace(app=app, url="https://deerflow.example.invalid/")
        node = Node(cpu_millis=4000, memory_mib=8192, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report"}, kinds={"C"})
        pool = Scheduling(ledger, nodes={"worker": node})
        secret = "native-node-offline-fixture-32-bytes"
        host = NativeDispatchHost(
            app, pool, {"artifact_root": str(tmp_path / "pool-native"), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}, {"worker": secret}
        )
        install_native_dispatch(app, host)

        async def worker_request(operation, **values):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://native-fixture") as client:
                response = await client.post(
                    f"/api/native-workers/worker/{operation}",
                    headers={"Authorization": "Bearer " + secret},
                    json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": host.mount_id, "owner": "outbound", **values},
                )
            assert response.status_code == 200, response.text
            return response.json()

        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        owner_token = set_current_user(principal)
        entered, release = asyncio.Event(), asyncio.Event()
        adopted = None
        try:
            record = await central.create_or_reject("pool-native-private", user_id="owner")
            graph_input = {"messages": [HumanMessage(content="research this synthetic document")]}

            async def snapshot_factory(**transport):
                return await make_native_snapshot(
                    request,
                    record,
                    run_ctx=ctx,
                    body=RunCreateRequest(stream_mode=["values"]),
                    config={"configurable": {"thread_id": record.thread_id}},
                    graph_input=graph_input,
                    admitted_knowledge_scope=None,
                    scope_assistant_id=None,
                    scheduled_task_runtime=None,
                    require_existing_thread=True,
                    **transport,
                )

            assert await host.admit_native(record, snapshot_factory)
            assert record.ownership_lost
            assert await asyncio.to_thread(pool.claim, "worker", "legacy-owner", kind="C") is None
            assert await asyncio.to_thread(pool.owned, "worker", "outbound", kind="C") == []
            selected = set_current_workspace(case.other)
            try:
                if withdrawn:
                    async with case.sf() as session:
                        await session.execute(
                            sa.update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == "owner").values(version=WorkspaceMembershipRow.version + 1)
                        )
                        await session.commit()
                polled = await worker_request("poll")
                if withdrawn:
                    assert polled["claim"] is None and not polled["owned"]
                    assert not worker._runs
                    assert (await asyncio.to_thread(ledger.list_active, kind="C"))[0]["cancel_requested"]
                    return
                envelope = polled["claim"]
                assert envelope is not None and not polled["owned"]
                job = envelope["job"]
                assert job["native"]["run_id"] == record.run_id and job["state"] == "starting" and job["attempt"] == 1
                assert job["workspace_context"] == asdict(case.original) and job["worker_owner"] == "outbound"
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                again = await worker_request("poll")
                assert again["claim"] is None and len(again["owned"]) == 1
                assert again["owned"][0]["job"]["generation"] == job["generation"]
                assert again["owned"][0]["capability"]
                control = await worker_request("get", job_id=job["id"], generation=job["generation"])
                assert not {"native", "spec", "error", "artifact", "workspace_context"}.intersection(control)
                reporter = NativeWorkerHost.__new__(NativeWorkerHost)
                reporter.request = worker_request
                job = await reporter.report(job, {"start_intent": True})
                assert job["start_intent"] and job["native"]["run_id"] == record.run_id
                started = await worker_request("get", job_id=job["id"], generation=job["generation"])
                assert started["start_intent"] and "native" not in started

                class HeldModel(BaseChatModel):
                    @property
                    def _llm_type(self):
                        return "deterministic-native-pool"

                    def _generate(self, *args, **kwargs):
                        raise AssertionError("native pool main must remain asynchronous")

                    async def _agenerate(self, *args, **kwargs):
                        assert get_current_workspace() == case.original
                        entered.set()
                        await release.wait()
                        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="private pooled research report", usage_metadata={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12}))])

                model = HeldModel()

                async def respond(state, config):
                    return {"messages": [await model.ainvoke(state["messages"], config=config)]}

                builder = StateGraph(MessagesState, context_schema=dict)
                builder.add_node("respond", respond)
                builder.add_edge(START, "respond")
                builder.add_edge("respond", END)
                graph = builder.compile()
                monkeypatch.setattr(services, "get_run_context", lambda request: ctx)
                monkeypatch.setattr(services, "resolve_agent_factory", lambda assistant_id: lambda **kwargs: graph)

                async def owner(*args, **kwargs):
                    return principal

                monkeypatch.setattr(services, "resolve_trusted_internal_owner_for_attribution", owner)
                app.state.run_manager = worker
                adopted = await adopt_native_run(app, job, envelope["capability"], secret)
                await asyncio.wait_for(entered.wait(), timeout=15)
                current = await worker_request("get", job_id=job["id"], generation=job["generation"])
                await worker_request("report", job_id=job["id"], generation=job["generation"], changes={"state": "running"}, expected=current)
                running = await worker_request("poll")
                assert running["claim"] is None and len(running["owned"]) == 1
                control = running["owned"][0]
                assert control["capability"] is None and "native" not in control["job"]
                assert control["job"]["id"] == job["id"] and not control["job"]["cancel_requested"]
                release.set()
                await asyncio.wait_for(adopted.task, timeout=20)
                async with case.sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    events = (await session.scalars(sa.select(RunEventRow).where(RunEventRow.run_id == record.run_id))).all()
                    assert row.status == "success" and row.last_ai_message == "private pooled research report" and row.total_tokens == 12
                    assert events and all(event.workspace_id == case.original.workspace_id and event.user_id == "owner" for event in events)
                    assert any("private pooled research report" in str(event.content) for event in events)
                current = await worker_request("get", job_id=job["id"], generation=job["generation"])
                # This fixture's in-process graph has drained; it creates no AIO
                # container and supplies no evidence about remote physical STOP.
                settled = await worker_request("report", job_id=job["id"], generation=job["generation"], changes={"state": "completed", "physical_stopped": True}, expected=current)
                assert settled["state"] == "completed" and "native" not in settled
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                settled_poll = await worker_request("poll")
                assert settled_poll["claim"] is None and not settled_poll["owned"]
                assert get_current_workspace() == case.other
            finally:
                reset_current_workspace(selected)
        finally:
            release.set()
            if adopted is not None and adopted.task is not None and not adopted.task.done():
                adopted.task.cancel()
                try:
                    await adopted.task
                except asyncio.CancelledError:
                    pass
            await worker.stop_heartbeat()
            await central.stop_heartbeat()
            reset_current_user(owner_token)

    try:
        _in_workspace_case(native_engine, scenario)
    finally:
        ledger.engine.dispose()

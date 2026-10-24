"""Native worker context identity boundaries; no model or runtime auth stubs."""

import asyncio
from contextvars import Context
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage
from langgraph.config import get_config
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import get_runtime
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401

from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.context_keys import RUN_OWNER_WORKER_CONTEXT_KEY
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

WORKSPACE_KEYS = {"workspace_id", "actor_user_id", "membership_version", "policy_version", "workspace_context"}


def test_native_worker_cannot_inherit_workspace_authority_from_caller_context():
    async def scenario():
        observed = {}
        observed_configurable = {}

        async def respond(state):
            observed.update(dict(get_runtime().context))
            observed_configurable.update(dict(get_config().get("configurable", {})))
            return {"messages": [AIMessage(content="deterministic report")]}

        graph = StateGraph(MessagesState, context_schema=dict)
        graph.add_node("respond", respond)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        compiled = graph.compile()
        manager = RunManager()
        record = await manager.create_or_reject("worker-context-main", user_id="alice")
        bridge = MemoryStreamBridge()
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=lambda **kwargs: compiled,
            graph_input={"messages": []},
            config={
                "configurable": {"thread_id": record.thread_id, **{key: "caller-spoof" for key in WORKSPACE_KEYS | {RUN_OWNER_WORKER_CONTEXT_KEY}}},
                "context": {key: "caller-spoof" for key in WORKSPACE_KEYS | {RUN_OWNER_WORKER_CONTEXT_KEY}},
            },
            stream_modes=["values"],
        )
        assert record.status == RunStatus.success, record.error
        assert observed, "the actual native graph must execute"
        assert not WORKSPACE_KEYS.intersection(observed), "caller identity survived the native worker boundary"
        assert not WORKSPACE_KEYS.intersection(observed_configurable), "caller identity survived in configurable"
        assert RUN_OWNER_WORKER_CONTEXT_KEY not in observed and RUN_OWNER_WORKER_CONTEXT_KEY not in observed_configurable
        assert observed["thread_id"] == record.thread_id and observed["run_id"] == record.run_id

    asyncio.run(scenario())


def test_native_sql_run_handoff_executes_with_its_original_workspace(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            workspaces = WorkspaceRepository(sf)
            service = WorkspaceService(workspaces)
            personal = await workspaces.provision_personal("owner")
            team = await workspaces.create_team("owner", "Native runtime", "native-runtime-main")
            original = await service.resolve_context("owner", team["id"])
            other = await service.resolve_context("owner", personal["id"])
            async with sf() as session:
                principal = await session.get(UserRow, "owner")
            user_token = set_current_user(principal)
            scope_token = set_current_workspace(original)
            try:
                threads = ThreadMetaRepository(sf, workspace_required=True)
                parent = await threads.create("runtime-scope", user_id="owner")
                runs = RunRepository(sf, workspace_required=True)
                ownership = RunOwnershipConfig(heartbeat_enabled=True)
                central = RunManager(store=runs, worker_id="runtime-central", run_ownership_config=ownership)
                worker = RunManager(store=runs, worker_id="runtime-worker", run_ownership_config=ownership)
                record = await central.create_or_reject("runtime-scope", user_id="owner", idempotency_key="runtime-main")
                set_current_workspace(other)
                await central.handoff_pending(record.run_id, owner_worker_id="runtime-dispatch")
                adopted = await worker.adopt_pending(record.run_id, thread_id=record.thread_id, user_id="owner", expected_owner_worker_id="runtime-dispatch", workspace_context=original)
                assert get_current_workspace() == other
                assert adopted.run_id == record.run_id and adopted.workspace_context == original
                observed = {}

                async def respond(state):
                    runtime = get_runtime().context
                    observed.update(dict(runtime))
                    assert get_current_workspace() == original
                    assert (await threads.get(record.thread_id, user_id="owner"))["status"] == "running"
                    return {"messages": [AIMessage(content="deterministic scoped report")]}

                graph = StateGraph(MessagesState, context_schema=dict)
                graph.add_node("respond", respond)
                graph.add_edge(START, "respond")
                graph.add_edge("respond", END)
                compiled = graph.compile()
                await run_agent(
                    MemoryStreamBridge(),
                    worker,
                    adopted,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=adopted.workspace_context),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": []},
                    config={"configurable": {"thread_id": record.thread_id}, "context": {key: "caller-spoof" for key in WORKSPACE_KEYS | {RUN_OWNER_WORKER_CONTEXT_KEY}}},
                    thread_incarnation=adopted.thread_incarnation,
                    stream_modes=["values"],
                )
                assert adopted.status == RunStatus.success, adopted.error
                assert observed["workspace_context"] == original
                assert observed["workspace_id"] == original.workspace_id and observed["actor_user_id"] == observed["user_id"] == "owner"
                assert observed["membership_version"] == original.membership_version and observed["policy_version"] == original.policy_version
                assert observed["thread_incarnation"] == parent["incarnation"]
                assert observed[RUN_OWNER_WORKER_CONTEXT_KEY] == "runtime-worker"
                assert get_current_workspace() == other, "worker scope leaked into its caller"
                async with sf() as session:
                    stored = await session.get(RunRow, record.run_id)
                    assert stored.status == "success" and stored.workspace_id == original.workspace_id
                    assert stored.thread_incarnation == parent["incarnation"] and stored.owner_worker_id == "runtime-worker"
                    assert await session.scalar(sa.select(sa.func.count()).select_from(RunRow).where(RunRow.thread_id == record.thread_id)) == 1
            finally:
                reset_current_workspace(scope_token)
                reset_current_user(user_token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_native_pending_transitions_refuse_revoked_or_recreated_scope(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime.runs.manager import RunStartupError

    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            workspaces = WorkspaceRepository(sf)
            service = WorkspaceService(workspaces)
            await workspaces.provision_personal("owner")
            team = await workspaces.create_team("owner", "Pending fences", "pending-fences")
            context = await service.resolve_context("owner", team["id"])
            token = set_current_workspace(context)
            try:
                threads = ThreadMetaRepository(sf, workspace_required=True)
                runs = RunRepository(sf, workspace_required=True)
                legacy = RunRepository(sf)
                ownership = RunOwnershipConfig(heartbeat_enabled=True)
                for phase in ("handoff", "adopt", "start"):
                    central = RunManager(store=runs, worker_id="central-" + phase, run_ownership_config=ownership)
                    worker = RunManager(store=runs, worker_id="worker-" + phase, run_ownership_config=ownership)
                    parent = await threads.create("pending-" + phase, user_id="owner")
                    record = await central.create_or_reject(parent["thread_id"], user_id="owner")
                    if phase != "handoff":
                        await central.handoff_pending(record.run_id, owner_worker_id="pending-dispatch")
                    if phase == "start":
                        record = await worker.adopt_pending(record.run_id, thread_id=record.thread_id, user_id="owner", expected_owner_worker_id="pending-dispatch", workspace_context=context)
                    async with sf() as session:
                        before = runs._row_to_dict(await session.get(RunRow, record.run_id))
                    # No unbound compatibility call may start/transfer a tenant row.
                    assert not await asyncio.create_task(legacy.start_run(record.run_id, owner_worker_id=before["owner_worker_id"]), context=Context())
                    assert not await asyncio.create_task(
                        legacy.transfer_pending(record.run_id, thread_id=record.thread_id, user_id="owner", expected_owner_worker_id=before["owner_worker_id"], owner_worker_id="legacy-spoof", lease_expires_at=None), context=Context()
                    )
                    for withdrawal in ("incarnation", "membership"):
                        async with sf() as session:
                            if withdrawal == "incarnation":
                                await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": "b" * 32, "id": record.thread_id})
                            else:
                                await session.execute(sa.text("UPDATE workspace_memberships SET version=version+1 WHERE workspace_id=:id AND user_id='owner'"), {"id": context.workspace_id})
                            await session.commit()
                        with pytest.raises((WorkspaceAccessDenied, RunStartupError)):
                            if phase == "handoff":
                                await central.handoff_pending(record.run_id, owner_worker_id="pending-dispatch")
                            elif phase == "adopt":
                                await worker.adopt_pending(record.run_id, thread_id=record.thread_id, user_id="owner", expected_owner_worker_id="pending-dispatch", workspace_context=context)
                            else:
                                await worker.try_start(record.run_id)
                        async with sf() as session:
                            assert runs._row_to_dict(await session.get(RunRow, record.run_id)) == before, "refused transition changed pending ownership/lease/capacity"
                            if withdrawal == "incarnation":
                                await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": parent["incarnation"], "id": record.thread_id})
                            else:
                                await session.execute(sa.text("UPDATE workspace_memberships SET version=:version WHERE workspace_id=:id AND user_id='owner'"), {"version": context.membership_version, "id": context.workspace_id})
                            await session.commit()
            finally:
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())

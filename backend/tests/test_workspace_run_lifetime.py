"""A terminal Run is not a closed native execution while finalizers remain."""

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("trigger", ["normal", "member", "user"])
def test_native_run_lifetime_covers_terminal_cleanup(native_engine, trigger):  # noqa: F811
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.authz.workspace import get_current_workspace, set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import CancelOutcome, ConflictError, MemoryStreamBridge, RunContext, RunManager, RunStatus, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        repository = RunRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0)
        manager = RunManager(store=repository, worker_id="lifetime-owner", run_ownership_config=ownership)
        peer = RunManager(store=repository, worker_id="lifetime-peer", run_ownership_config=ownership)
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        entered, release = asyncio.Event(), asyncio.Event()
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        token = set_current_user(principal)
        task = None
        try:
            await threads.create("lifetime-main", user_id="owner")
            record = await manager.create_or_reject("lifetime-main", user_id="owner")
            async with case.sf() as session:
                lifetimes = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_execution"))).all()
                assert len(lifetimes) == 1 and lifetimes[0].state == "open", "native admission has no durable execution lifetime"
                lifetime_id = lifetimes[0].operation_id

            async def respond(state):
                return {"messages": [AIMessage(content="deterministic native report")]}

            async def finalizer(finished):
                assert finished.status == RunStatus.success
                entered.set()
                await release.wait()

            graph = StateGraph(MessagesState, context_schema=dict)
            graph.add_node("respond", respond)
            graph.add_edge(START, "respond")
            graph.add_edge("respond", END)
            compiled = graph.compile()
            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, on_run_completed=finalizer),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": []},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await asyncio.wait_for(entered.wait(), timeout=10)
            async with case.sf() as session:
                assert (await session.get(RunRow, record.run_id)).status == "success"
                assert (await session.get(WorkspaceOperationOutboxRow, lifetime_id)).state == "open"
            with pytest.raises(ConflictError):
                await peer.create_or_reject(record.thread_id, user_id="owner")
            fresh = case.original
            if trigger == "member":
                with native_engine.begin() as connection:
                    connection.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                workspaces = WorkspaceRepository(case.sf)
                await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
                fresh = await case.service.resolve_context("owner", case.original.workspace_id)
                assert await manager.cancel(record.run_id, action="interrupt") == CancelOutcome.unknown, "withdrawn member reused local control cache"
                assert not record.abort_event.is_set()
            elif trigger == "user":
                set_current_workspace(case.other)
                assert await manager.cancel(record.run_id, action="interrupt") == CancelOutcome.unknown
                assert not record.abort_event.is_set()
                async with case.sf() as session:
                    assert (await session.get(RunRow, record.run_id)).cancel_action is None
                set_current_workspace(case.original)
                assert await peer.cancel(record.run_id, action="interrupt") in (CancelOutcome.cancelled, CancelOutcome.requested)
            set_current_workspace(case.other)
            await manager.start_heartbeat()
            await manager._renew_leases()
            assert not record.ownership_lost and not task.done()
            async with case.sf() as session:
                row = await session.get(RunRow, record.run_id)
                assert row.cancel_action == (None if trigger == "normal" else "interrupt")
                assert (await session.get(WorkspaceOperationOutboxRow, lifetime_id)).state == "open"
            set_current_workspace(fresh)
            with pytest.raises(ConflictError):
                await peer.create_or_reject(record.thread_id, user_id="owner")
            set_current_workspace(case.other)
            release.set()
            await asyncio.wait_for(task, timeout=10)
            await manager._renew_leases()
            async with case.sf() as session:
                row = await session.get(RunRow, record.run_id)
                lifetime = await session.get(WorkspaceOperationOutboxRow, lifetime_id)
                assert lifetime.state == "completed"
                assert row.status == ("success" if trigger == "normal" else "interrupted")
                assert row.workspace_context_json["membership_version"] == case.original.membership_version
                stops = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_stop"))).all()
                assert len(stops) == (0 if trigger == "normal" else 1)
                assert all(stop.state == "completed" for stop in stops)
            assert get_current_workspace() == case.other
            set_current_workspace(fresh)
            if trigger == "normal":
                assert await manager.cancel(record.run_id, action="interrupt") == CancelOutcome.not_cancellable
            replacement = await peer.create_or_reject(record.thread_id, user_id="owner")
            assert replacement.run_id != record.run_id and replacement.workspace_context == fresh
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=10)
                except asyncio.CancelledError:
                    pass
            await manager.stop_heartbeat()
            reset_current_user(token)

    _in_workspace_case(native_engine, scenario)


def test_owner_pending_rollback_never_restores_checkpoint(native_engine, tmp_path):  # noqa: F811
    import aiosqlite
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.runtime import CancelOutcome, MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("pending-checkpoint", user_id="owner")
        connection = await aiosqlite.connect(str(tmp_path / "pending-checkpoints.sqlite"))
        try:
            saver = AsyncSqliteSaver(connection)
            builder = StateGraph(MessagesState, context_schema=dict)
            builder.add_node("seed", lambda state: {"messages": [HumanMessage(content="preserve existing private conversation")]})
            builder.add_edge(START, "seed")
            builder.add_edge("seed", END)
            graph = builder.compile(checkpointer=saver)
            config = {"configurable": {"thread_id": "pending-checkpoint"}}
            await graph.ainvoke({"messages": []}, config=config)
            before = await saver.aget_tuple(config)
            assert before is not None
            repository = RunRepository(case.sf, workspace_required=True)
            manager = RunManager(store=repository, worker_id="pending-checkpoint-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
            record = await manager.create_or_reject("pending-checkpoint", user_id="owner")
            async with case.sf() as session:
                principal = await session.get(UserRow, "owner")
            token = set_current_user(principal)
            try:
                assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
                assert record.abort_action == "interrupt", "unstarted user rollback entered checkpoint restoration"
                await manager._renew_leases()
                assert record.workspace_stop_confirmed and record.workspace_lifetime_confirmed
                async with case.sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    assert row.status == "interrupted" and row.cancel_action == "rollback"
                    operations = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind.in_(("run_execution", "run_stop"))))).all()
                    assert len(operations) == 2 and all(operation.state == "completed" for operation in operations)
                # An already queued consumer may still receive the old record.
                # Exercise the real native worker's cancellation/cleanup path;
                # it must leave the previous durable checkpoint unchanged.
                await run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=saver, thread_store=threads, workspace_context=case.original),
                    agent_factory=lambda **kwargs: graph,
                    graph_input={"messages": []},
                    config=config,
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
                after = await saver.aget_tuple(config)
                assert after is not None and after.config == before.config and after.checkpoint == before.checkpoint
            finally:
                reset_current_user(token)
        finally:
            await connection.close()

    _in_workspace_case(native_engine, scenario)

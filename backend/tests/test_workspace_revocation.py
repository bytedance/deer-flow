"""Native graph cancellation, original owner control and durable cleanup barrier."""

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_membership_revocation_stops_native_run_after_finalizers(native_engine, cleanup_fails):  # noqa: F811
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
    from deerflow.runtime import ConflictError, MemoryStreamBridge, RunContext, RunManager, RunStatus, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        repository = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store=repository, worker_id="native-revocation-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        entered, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        finalizing, finish = asyncio.Event(), asyncio.Event()
        with native_engine.begin() as connection:
            connection.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        user_token = set_current_user(principal)
        task = None
        try:
            await threads.create("revocation-main", user_id="owner")
            record = await manager.create_or_reject("revocation-main", user_id="owner")

            async def work(state):
                assert get_current_workspace() == case.original
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopping.set()
                    await release.wait()
                return {"messages": [AIMessage(content="must not finish a revoked run")]}

            async def on_completed(finished):
                assert finished.status == RunStatus.interrupted
                finalizing.set()
                await finish.wait()
                if cleanup_fails:
                    raise RuntimeError("synthetic native finalizer failure; STOP remains uncertain")

            graph = StateGraph(MessagesState, context_schema=dict)
            graph.add_node("work", work)
            graph.add_edge(START, "work")
            graph.add_edge("work", END)
            compiled = graph.compile()
            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, on_run_completed=on_completed),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": []},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await asyncio.wait_for(entered.wait(), timeout=10)
            set_current_workspace(case.other)
            workspaces = WorkspaceRepository(case.sf)
            await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
            await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            async with case.sf() as session:
                row = await session.get(RunRow, record.run_id)
                assert row.cancel_action == "interrupt" and row.cancel_requested_at is not None, "membership mutation did not durably cancel native Run"
                operations = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_stop"))).all()
                assert len(operations) == 1 and operations[0].state == "pending"
                operation_id = operations[0].operation_id
                assert row.status == "running"
            await manager.start_heartbeat()
            await asyncio.wait_for(stopping.wait(), timeout=10)
            async with case.sf() as session:
                assert (await session.get(WorkspaceOperationOutboxRow, operation_id)).state == "pending"
            assert not task.done(), "native graph finalizer was not held"
            fresh = await case.service.resolve_context("owner", case.original.workspace_id)
            set_current_workspace(fresh)
            peer = RunManager(store=repository, worker_id="native-peer", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
            try:
                await peer.create_or_reject(record.thread_id, user_id="owner")
            except ConflictError:
                pass
            else:
                raise AssertionError("unconfirmed STOP released native admission")
            set_current_workspace(case.other)
            release.set()
            await asyncio.wait_for(finalizing.wait(), timeout=10)
            async with case.sf() as session:
                assert (await session.get(RunRow, record.run_id)).status == "interrupted"
                assert (await session.get(WorkspaceOperationOutboxRow, operation_id)).state == "pending"
            await manager._renew_leases()
            assert not record.ownership_lost and not task.done(), "terminal cleanup lost native ownership"
            async with case.sf() as session:
                assert (await session.get(WorkspaceOperationOutboxRow, operation_id)).state == "pending"
            set_current_workspace(fresh)
            try:
                await peer.create_or_reject(record.thread_id, user_id="owner")
            except ConflictError:
                pass
            else:
                raise AssertionError("terminal metadata released admission before native finalizers closed")
            set_current_workspace(case.other)
            finish.set()
            await asyncio.wait_for(task, timeout=10)
            await manager._renew_leases()
            if cleanup_fails:
                assert not record.workspace_execution_closed and not record.workspace_stop_confirmed, "failed finalizer produced a closed-execution proof"
                async with case.sf() as session:
                    assert (await session.get(WorkspaceOperationOutboxRow, operation_id)).state == "pending"
                set_current_workspace(fresh)
                with pytest.raises(ConflictError):
                    await peer.create_or_reject(record.thread_id, user_id="owner")
                set_current_workspace(case.other)
                return
            async with case.sf() as session:
                row = await session.get(RunRow, record.run_id)
                operation = await session.get(WorkspaceOperationOutboxRow, operation_id)
                assert row.status == "interrupted" and operation.state == "completed"
                assert operation.payload["target"]["workspace_context"]["membership_version"] == case.original.membership_version
                assert operation.payload["receipt"]["evidence"] == "native_worker_closed"
                parents = (await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "workspace_revoke"))).all()
                assert len(parents) == 2 and all(parent.state == "pending" for parent in parents)
            assert record.status == RunStatus.interrupted and get_current_workspace() == case.other
            set_current_workspace(fresh)
            replacement = await peer.create_or_reject(record.thread_id, user_id="owner")
            assert replacement.run_id != record.run_id and replacement.workspace_context == fresh
        finally:
            release.set()
            finish.set()
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=10)
                except asyncio.CancelledError:
                    pass
            await manager.stop_heartbeat()
            reset_current_user(user_token)

    _in_workspace_case(native_engine, scenario)


def test_pending_run_stop_preserves_first_intent_and_original_cleanup_binding(native_engine):  # noqa: F811
    from dataclasses import replace
    from datetime import timedelta

    from deerflow.authz.workspace import set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.run_control import NativeRunStopTarget
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import RunManager, RunStatus

    async def scenario(case):
        with native_engine.begin() as connection:
            connection.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
        repository = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store=repository, worker_id="pending-native-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        await ThreadMetaRepository(case.sf, workspace_required=True).create("pending-revocation", user_id="owner")
        record = await manager.create_or_reject("pending-revocation", user_id="owner")
        target = NativeRunStopTarget.from_record(record)
        assert await repository.request_cancel(record.run_id, action="rollback") == "rollback"
        workspaces = WorkspaceRepository(case.sf)
        await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
        await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
        set_current_workspace(case.other)
        async with case.sf() as session:
            row = await session.get(RunRow, record.run_id)
            assert row.status == "pending" and row.cancel_action == "rollback"
            original_lease = row.lease_expires_at
            operation = await session.get(WorkspaceOperationOutboxRow, target.operation_id)
            assert operation.state == "pending" and operation.payload["target"] == target.as_payload()
        for invalid in (
            replace(target, owner_worker_id="different-worker"),
            replace(target, thread_incarnation="e" * 32),
            replace(target, created_at=(datetime.fromisoformat(target.created_at) + timedelta(seconds=1)).isoformat()),
            replace(target, workspace_context=replace(target.workspace_context, membership_version=target.workspace_context.membership_version + 1)),
        ):
            assert not await repository.confirm_workspace_run_stop(invalid, evidence="native_not_started")
        async with case.sf() as session:
            await session.execute(sa.update(RunRow).where(RunRow.run_id == record.run_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=10)))
            await session.commit()
        assert not await repository.confirm_workspace_run_stop(target, evidence="native_not_started")
        assert not await repository.claim_for_takeover(record.run_id, grace_seconds=0, error="must not release uncertain execution")
        assert await repository.list_inflight_with_expired_lease(grace_seconds=0) == []
        assert await repository.list_inflight() == []
        async with case.sf() as session:
            assert (await session.get(WorkspaceOperationOutboxRow, target.operation_id)).state == "pending"
            assert (await session.get(RunRow, record.run_id)).status == "pending"
            # Restore only the isolated fault fixture; this is not runtime
            # takeover. Replace the private parent to prove cleanup does not
            # acquire authority over its new incarnation.
            await session.execute(sa.update(RunRow).where(RunRow.run_id == record.run_id).values(lease_expires_at=original_lease))
            await session.execute(sa.update(ThreadMetaRow).where(ThreadMetaRow.thread_id == record.thread_id).values(incarnation="f" * 32))
            await session.commit()
        await manager._renew_leases()
        assert record.status == RunStatus.interrupted and record.abort_action == "interrupt"
        assert record.workspace_stop_confirmed and record.task is None
        async with case.sf() as session:
            row = await session.get(RunRow, record.run_id)
            operation = await session.get(WorkspaceOperationOutboxRow, target.operation_id)
            assert row.status == "interrupted" and row.cancel_action == "rollback"
            assert row.thread_incarnation == target.thread_incarnation and row.workspace_context_json == target.as_payload()["workspace_context"]
            assert operation.state == "completed" and operation.payload["receipt"]["evidence"] == "native_not_started"
            assert (await session.get(ThreadMetaRow, record.thread_id)).incarnation == "f" * 32
        assert await repository.confirm_workspace_run_stop(target, evidence="native_not_started"), "matching cleanup replay is not idempotent"

    _in_workspace_case(native_engine, scenario)

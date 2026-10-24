"""Native worker checkpoint IO must retain its original execution authority."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("trigger", ["normal", "member", "cancel", "lease", "owner"])
def test_native_worker_fences_late_checkpoint(native_engine, tmp_path, trigger):  # noqa: F811
    import aiosqlite
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.authz.workspace import get_current_workspace, set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("checkpoint-main", user_id="owner")
        connection = await aiosqlite.connect(str(tmp_path / "worker-checkpoints.sqlite"))
        manager = RunManager(store=RunRepository(case.sf, workspace_required=True), worker_id="checkpoint-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        entered, release = asyncio.Event(), asyncio.Event()
        task = None
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        token = set_current_user(principal)
        try:
            initial_saved = asyncio.Event()

            class ObservedSaver(AsyncSqliteSaver):
                async def aput(self, config, checkpoint, metadata, new_versions):
                    result = await super().aput(config, checkpoint, metadata, new_versions)
                    if metadata.get("source") == "loop":
                        initial_saved.set()
                    return result

            saver = ObservedSaver(connection)
            config = {"configurable": {"thread_id": "checkpoint-main"}}
            seed = StateGraph(MessagesState, context_schema=dict)
            seed.add_node("seed", lambda state: {"messages": [AIMessage(content="existing private report")]})
            seed.add_edge(START, "seed")
            seed.add_edge("seed", END)
            await seed.compile(checkpointer=saver).ainvoke({"messages": []}, config=config)
            initial_saved.clear()
            record = await manager.create_or_reject("checkpoint-main", user_id="owner")

            async def respond(state):
                entered.set()
                await release.wait()
                return {"messages": [AIMessage(content="late private report")]}

            builder = StateGraph(MessagesState, context_schema=dict)
            builder.add_node("respond", respond)
            builder.add_edge(START, "respond")
            builder.add_edge("respond", END)
            graph = builder.compile()
            task = asyncio.create_task(
                run_agent(
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
            )
            record.task = task
            await asyncio.wait_for(entered.wait(), timeout=15)
            # Observe a real durable initial checkpoint, never a timing guess.
            await asyncio.wait_for(initial_saved.wait(), timeout=15)
            before = await saver.aget_tuple(config)
            assert before is not None
            assert "existing private report" in [m.content for m in before.checkpoint["channel_values"]["messages"]]
            if trigger == "member":
                async with case.sf() as session:
                    await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                    await session.commit()
                workspaces = WorkspaceRepository(case.sf)
                await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            elif trigger == "cancel":
                peer = RunManager(store=RunRepository(case.sf, workspace_required=True), worker_id="checkpoint-peer", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
                await peer.cancel(record.run_id, action="interrupt")
                async with case.sf() as session:
                    assert (await session.get(RunRow, record.run_id)).cancel_action == "interrupt"
            elif trigger in ("lease", "owner"):
                # Explicit durable ownership faults; no heartbeat test doubles.
                async with case.sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    if trigger == "lease":
                        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    else:
                        row.owner_worker_id = "replacement-owner"
                    await session.commit()
            # UI selection changes cannot retarget a captured worker.
            set_current_workspace(case.other)
            release.set()
            await asyncio.wait_for(task, timeout=15)
            after = await saver.aget_tuple(config)
            contents = [m.content for m in after.checkpoint["channel_values"]["messages"]]
            if trigger == "normal":
                assert "late private report" in contents
            else:
                assert "late private report" not in contents, "stale or cancelled native worker wrote its late model result"
                assert after.config == before.config
                assert after.checkpoint == before.checkpoint
                assert after.pending_writes == before.pending_writes
            if trigger in ("lease", "owner"):
                async with case.sf() as session:
                    lifetime = await session.scalar(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_execution"))
                    assert lifetime.state == "open", "lost ownership was treated as acknowledged cleanup"
            assert get_current_workspace() == case.other
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=15)
                except asyncio.CancelledError:
                    pass
            await manager.stop_heartbeat()
            reset_current_user(token)
            await connection.close()

    _in_workspace_case(native_engine, scenario)

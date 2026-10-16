"""Actual native model callbacks, journal SQL and Run metadata need one owner."""

import asyncio
import json
from contextvars import Context
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


@pytest.mark.parametrize("trigger", ["normal", "member", "cancel", "lease", "owner"])
def test_native_journal_and_completion_keep_execution_authority(native_engine, trigger):  # noqa: F811
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.authz.workspace import get_current_workspace, set_current_workspace
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("effects-main", user_id="owner")
        repository = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store=repository, worker_id="effects-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        entered, release = asyncio.Event(), asyncio.Event()
        task = None
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        token = set_current_user(principal)
        try:
            record = await manager.create_or_reject("effects-main", user_id="owner")

            class HeldModel(BaseChatModel):
                @property
                def _llm_type(self):
                    return "deterministic-native-held"

                def _generate(self, *args, **kwargs):
                    raise AssertionError("native main must remain asynchronous")

                async def _agenerate(self, *args, **kwargs):
                    entered.set()
                    await release.wait()
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content="late private research report", usage_metadata={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12}))])

            model = HeldModel()

            async def respond(state, config):
                message = await model.ainvoke(state["messages"], config=config)
                return {"messages": [message]}

            builder = StateGraph(MessagesState, context_schema=dict)
            builder.add_node("respond", respond)
            builder.add_edge(START, "respond")
            builder.add_edge("respond", END)
            graph = builder.compile()
            bridge = MemoryStreamBridge()
            task = asyncio.create_task(
                run_agent(
                    bridge,
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, event_store=DbRunEventStore(case.sf, workspace_required=True), thread_store=threads, workspace_context=case.original),
                    agent_factory=lambda **kwargs: graph,
                    graph_input={"messages": [HumanMessage(content="research this synthetic document")]},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await asyncio.wait_for(entered.wait(), timeout=15)
            if trigger == "normal":

                async def unbound_attempts():
                    legacy = RunRepository(case.sf)
                    assert not await legacy.update_status(record.run_id, "error", error="unbound-writer")
                    assert not await legacy.update_run_completion(record.run_id, status="success", last_ai_message="unbound-writer", total_tokens=999)
                    await legacy.update_run_progress(record.run_id, last_ai_message="unbound-writer", total_tokens=999)
                    await legacy.update_model_name(record.run_id, "unbound-writer")
                    result = await legacy.finalize_if_not_cancelled(record.run_id, status="error")
                    assert not result.finalized
                    assert not await legacy.update_lease(record.run_id, owner_worker_id=record.owner_worker_id, lease_expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
                    with pytest.raises(WorkspaceAccessDenied):
                        await DbRunEventStore(case.sf).put(thread_id=record.thread_id, run_id=record.run_id, event_type="unbound-writer", category="message", content="unbound-writer")

                # No ambient principal/workspace can be used to infer authority.
                await asyncio.create_task(unbound_attempts(), context=Context())
                async with case.sf() as session:
                    current = await session.get(RunRow, record.run_id)
                    assert current.status == "running" and current.last_ai_message is None and current.total_tokens == 0
                    assert current.model_name != "unbound-writer"
            if trigger == "member":
                async with case.sf() as session:
                    await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                    await session.commit()
                workspaces = WorkspaceRepository(case.sf)
                await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            elif trigger == "cancel":
                peer = RunManager(store=repository, worker_id="effects-peer", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
                await peer.cancel(record.run_id, action="interrupt")
                async with case.sf() as session:
                    assert (await session.get(RunRow, record.run_id)).cancel_action == "interrupt"
            elif trigger in ("lease", "owner"):
                async with case.sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    if trigger == "lease":
                        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    else:
                        row.owner_worker_id = "replacement-owner"
                    parent = await session.get(ThreadMetaRow, record.thread_id)
                    parent.status, parent.display_name = "idle", "replacement-owner-title"
                    await session.commit()
            set_current_workspace(case.other)
            release.set()
            await asyncio.wait_for(task, timeout=20)
            frames = []
            ended = False
            async for item in bridge.subscribe(record.run_id, heartbeat_interval=0.01):
                if item.event == "__end__":
                    ended = True
                    break
                if item.event == "__heartbeat__":
                    break
                frames.append(item)
            late_frames = [item for item in frames if "late private research report" in json.dumps(item.data, default=str)]
            if trigger == "normal":
                assert late_frames and ended, "normal native stream was suppressed or did not end"
            else:
                assert not late_frames, "stale worker queued a late private response for replay"
                assert ended == (trigger not in ("lease", "owner")), "old owner terminated a stream it no longer owns"
            async with case.sf() as session:
                events = (await session.scalars(sa.select(RunEventRow).where(RunEventRow.run_id == record.run_id))).all()
                row = await session.get(RunRow, record.run_id)
                lifetime = await session.scalar(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_execution"))
                late = [e for e in events if "late private research report" in e.content]
                if trigger == "normal":
                    assert late, "real native model callback did not reach SQL journal"
                    assert row.last_ai_message == "late private research report"
                    assert row.total_tokens == 12 and row.status == "success"
                    assert all(e.workspace_id == case.original.workspace_id and e.user_id == "owner" for e in events), "native journal rows lost their original workspace"
                else:
                    assert not late, "withdrawn worker persisted a late private response"
                    assert row.last_ai_message is None and row.total_tokens == 0, "withdrawn worker mutated durable completion/progress"
                    assert row.status == ("running" if trigger in ("lease", "owner") else "interrupted")
                assert lifetime.state == ("open" if trigger in ("lease", "owner") else "completed"), "denied effects confused cleanup acknowledgement with ownership loss"
                parent = await session.get(ThreadMetaRow, record.thread_id)
                assert parent.status == ("idle" if trigger in ("normal", "lease", "owner") else "interrupted"), "old worker overwrote current thread status"
                if trigger in ("lease", "owner"):
                    assert parent.display_name == "replacement-owner-title"
            assert get_current_workspace() == case.other
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=20)
                except asyncio.CancelledError:
                    pass
            await manager.stop_heartbeat()
            reset_current_user(token)

    _in_workspace_case(native_engine, scenario)

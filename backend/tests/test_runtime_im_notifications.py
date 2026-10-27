"""Stage 2 ordinary run / goal / human_input_request IM notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from app.scheduler.notification_delivery import NotificationDeliveryWorker
from app.scheduler.service import ScheduledTaskService
from deerflow.agents.human_input import (
    HUMAN_INPUT_RESPONSE_KEY,
    extract_unanswered_human_input_request,
)
from deerflow.persistence.base import Base
from deerflow.persistence.channel_connections.model import ChannelConnectionRow
from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository
from deerflow.persistence.notification_deliveries.model import NotificationDeliveryRow
from deerflow.persistence.user.im_notifications import ImNotificationPreferencesRepository
from deerflow.persistence.user.model import UserRow
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/runtime_notices.db")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        session.add(UserRow(id="alice", email="alice@example.com"))
        for provider in ("feishu", "wecom", "wechat", "qq"):
            session.add(
                ChannelConnectionRow(
                    id=f"personal-{provider}",
                    owner_user_id="alice",
                    provider=provider,
                    status="connected",
                    external_account_id=f"{provider}-user",
                    workspace_id="app:c2c" if provider == "qq" else "private",
                    metadata_json={"chat_type": "c2c" if provider == "qq" else "p2p"},
                )
            )
        session.add(
            ChannelConnectionRow(
                id="qq-group-conn",
                owner_user_id="alice",
                provider="qq",
                status="connected",
                external_account_id="qq-group-member",
                workspace_id="app:group:grp-1",
                metadata_json={"chat_type": "group", "chat_id": "grp-1", "group_openid": "grp-1"},
            )
        )

    preferences = ImNotificationPreferencesRepository(sessions)
    deliveries = NotificationDeliveryRepository(sessions)
    service = ScheduledTaskService(
        task_repo=SimpleNamespace(session_factory=sessions),
        task_run_repo=SimpleNamespace(session_factory=sessions),
        launch_run=None,
        connection_repo=object(),
        notification_repo=deliveries,
        poll_interval_seconds=5,
        lease_seconds=30,
        max_concurrent_runs=1,
    )
    try:
        yield sessions, preferences, deliveries, service
    finally:
        await engine.dispose()


def _make_run(
    *,
    run_id: str = "run-101",
    thread_id: str = "thread-101",
    status: RunStatus = RunStatus.success,
    metadata: dict | None = None,
    goal_verdict: dict | None = None,
    human_input_request: dict | None = None,
    error: str | None = None,
) -> RunRecord:
    base_meta = {"owner": "alice", "title": "Prepare quarterly roadmap"}
    if metadata:
        base_meta.update(metadata)
    return RunRecord(
        run_id=run_id,
        thread_id=thread_id,
        assistant_id="lead_agent",
        status=status,
        on_disconnect=DisconnectMode.continue_,
        user_id="alice",
        metadata=base_meta,
        error=error,
        goal_verdict=goal_verdict,
        human_input_request=human_input_request,
    )


def test_extract_unanswered_human_input_request_distinguishes_pending_and_answered():
    pending_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call-ask-1",
                "name": "ask_clarification",
                "args": {
                    "question": "Which region should we deploy to first?",
                    "clarification_type": "missing_info",
                    "options": ["us-east", "eu-west"],
                },
            }
        ],
    )
    prompt_tool = ToolMessage(
        content="Which region should we deploy to first?",
        tool_call_id="call-ask-1",
        name="ask_clarification",
        artifact={
            "human_input": {
                "version": 1,
                "kind": "human_input_request",
                "source": "ask_clarification",
                "request_id": "req-ask-1",
                "question": "Which region should we deploy to first?",
            }
        },
    )
    extracted = extract_unanswered_human_input_request([HumanMessage(content="Deploy it"), pending_ai, prompt_tool])
    assert extracted == {
        "kind": "human_input_request",
        "request_id": "req-ask-1",
        "question": "Which region should we deploy to first?",
        "source": "ask_clarification",
    }

    # Answered by a structured human_input_response -> no longer pending.
    answered_user = HumanMessage(
        content="us-east",
        additional_kwargs={
            HUMAN_INPUT_RESPONSE_KEY: {
                "version": 1,
                "kind": "human_input_response",
                "source": "ask_clarification",
                "request_id": "req-ask-1",
                "response_kind": "text",
                "value": "us-east",
            }
        },
    )
    assert extract_unanswered_human_input_request([HumanMessage(content="Deploy it"), pending_ai, prompt_tool, answered_user]) is None

    # Followed by a plain user message in the conversation -> no longer pending.
    assert extract_unanswered_human_input_request([HumanMessage(content="Deploy it"), pending_ai, prompt_tool, HumanMessage(content="Use us-east")]) is None


@pytest.mark.anyio
async def test_ordinary_run_notifications_are_opt_in_by_default(env):
    sessions, _, _, service = env
    await service.handle_run_completion(_make_run(status=RunStatus.success))
    await service.handle_run_completion(_make_run(run_id="run-102", status=RunStatus.error, error="boom"))
    await service.handle_run_completion(
        _make_run(
            run_id="run-103",
            status=RunStatus.success,
            human_input_request={"tool_call_id": "call-1", "question": "Confirm?", "clarification_type": "approach_choice"},
        )
    )
    async with sessions() as session:
        assert (await session.scalars(select(NotificationDeliveryRow))).all() == []


@pytest.mark.anyio
async def test_human_input_request_check_precedes_success_and_never_emits_false_completion(env):
    sessions, preferences, _, service = env
    await preferences.patch(
        "alice",
        {"run_completed": True, "run_failed": True, "human_input_requested": True},
    )
    record = _make_run(
        run_id="run-clarify",
        status=RunStatus.success,
        human_input_request={
            "tool_call_id": "call-clarify-1",
            "question": "Should we overwrite the existing staging table?",
            "clarification_type": "risk_confirmation",
        },
    )
    await service.handle_run_completion(record)

    async with sessions() as session:
        rows = (await session.scalars(select(NotificationDeliveryRow))).all()
    assert len(rows) == 4
    assert {row.provider for row in rows} == {"feishu", "wecom", "wechat", "qq"}
    assert all(row.event == "human_input_requested" for row in rows)
    assert all(row.source_kind == "human_input_request" for row in rows)
    assert all(row.source_key == "thread-101:call-clarify-1" for row in rows)
    assert all(row.task_id is None and row.task_run_id is None for row in rows)
    assert all(row.target != "qq-group-member" for row in rows)
    assert all(row.payload_json["question"] == "Should we overwrite the existing staging table?" for row in rows)


@pytest.mark.anyio
async def test_ordinary_run_completed_and_explicit_group_target_selection(env):
    sessions, preferences, _, service = env
    await preferences.patch("alice", {"run_completed": True})
    record = _make_run(
        run_id="run-goal-ok",
        status=RunStatus.success,
        metadata={"notification_group_connection_id": "qq-group-conn"},
        goal_verdict={"satisfied": True, "relied_on_assumption": True, "reason_code": None},
    )
    await service.handle_run_completion(record)

    async with sessions() as session:
        rows = (await session.scalars(select(NotificationDeliveryRow))).all()
    assert len(rows) == 5
    personal = [r for r in rows if r.payload_json.get("target_type") != "group"]
    group = [r for r in rows if r.payload_json.get("target_type") == "group"]
    assert {r.provider for r in personal} == {"feishu", "wecom", "wechat", "qq"}
    assert [(r.provider, r.target) for r in group] == [("qq", "qq-group-conn")]
    assert all(r.event == "run_completed" and r.source_kind == "run" and r.source_key == "run-goal-ok" for r in rows)
    assert all(r.payload_json.get("relied_on_assumption") is True for r in rows)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reason_code",
    [
        "max_continuations_reached",
        "no_progress_detected",
        "token_capped",
        "evaluator_failed",
        "blocked:needs_user_input",
    ],
)
async def test_ordinary_goal_unmet_stand_down_without_human_input_card_does_not_emit_false_notice(env, reason_code):
    sessions, preferences, _, service = env
    await preferences.patch(
        "alice",
        {"run_completed": True, "run_failed": True, "human_input_requested": True},
    )
    record = _make_run(
        run_id=f"run-unmet-{reason_code}",
        status=RunStatus.success,
        goal_verdict={"satisfied": False, "reason_code": reason_code, "relied_on_assumption": False},
        human_input_request=None,
    )
    await service.handle_run_completion(record)
    async with sessions() as session:
        assert (await session.scalars(select(NotificationDeliveryRow))).all() == []


@pytest.mark.anyio
async def test_interrupted_and_im_originated_runs_do_not_enqueue_runtime_notifications(env):
    sessions, preferences, _, service = env
    await preferences.patch(
        "alice",
        {"run_completed": True, "run_failed": True, "human_input_requested": True},
    )
    await service.handle_run_completion(_make_run(run_id="run-int", status=RunStatus.interrupted))
    await service.handle_run_completion(
        _make_run(
            run_id="run-im",
            status=RunStatus.success,
            metadata={"deerflow_origin": {"kind": "im_channel", "provider": "feishu"}},
        )
    )
    await service.handle_run_completion(
        _make_run(
            run_id="run-err",
            status=RunStatus.error,
            error="model timeout",
        )
    )
    async with sessions() as session:
        rows = (await session.scalars(select(NotificationDeliveryRow))).all()
    assert {r.run_id for r in rows} == {"run-err"}
    assert all(r.event == "run_failed" for r in rows)


@pytest.mark.anyio
async def test_worker_rechecks_human_input_pending_and_drops_resolved_requests(env):
    sessions, preferences, deliveries, service = env
    await preferences.patch(
        "alice",
        {"human_input_requested": True, "wecom": False, "wechat": False, "qq": False},
    )
    await service.handle_run_completion(
        _make_run(
            run_id="run-stale-ask",
            thread_id="thread-stale-ask",
            status=RunStatus.success,
            human_input_request={"tool_call_id": "call-stale-1", "question": "Still need this?"},
        )
    )
    (claimed,) = await deliveries.claim_due_deliveries(now=datetime.now(UTC), limit=10)
    sent_messages = []

    class FakeChannel:
        is_running = True

        async def send_notification_for_owner(self, **kwargs):
            sent_messages.append(kwargs)

    async def already_resolved(thread_id: str, tool_call_id: str | None) -> bool:
        assert (thread_id, tool_call_id) == ("thread-stale-ask", "call-stale-1")
        return False

    worker = NotificationDeliveryWorker(
        delivery_repo=deliveries,
        resolve_channel=lambda _: FakeChannel(),
        resolve_notification_preferences=preferences.get,
        resolve_notification_event_preferences=preferences.get_event_preferences,
        resolve_human_input_pending=already_resolved,
    )
    await worker._deliver(claimed)
    assert sent_messages == []
    async with sessions() as session:
        row = await session.get(NotificationDeliveryRow, claimed["id"])
        assert (row.status, row.last_error) == ("failed", "human_input_request_already_resolved")

    # Still-pending request delivers normally.
    await service.handle_run_completion(
        _make_run(
            run_id="run-live-ask",
            thread_id="thread-live-ask",
            status=RunStatus.success,
            human_input_request={"tool_call_id": "call-live-1", "question": "Approve production deploy?"},
        )
    )
    (claimed_live,) = await deliveries.claim_due_deliveries(now=datetime.now(UTC), limit=10)

    async def still_pending(thread_id: str, tool_call_id: str | None) -> bool:
        assert (thread_id, tool_call_id) == ("thread-live-ask", "call-live-1")
        return True

    worker_live = NotificationDeliveryWorker(
        delivery_repo=deliveries,
        resolve_channel=lambda _: FakeChannel(),
        resolve_notification_preferences=preferences.get,
        resolve_notification_event_preferences=preferences.get_event_preferences,
        resolve_human_input_pending=still_pending,
    )
    await worker_live._deliver(claimed_live)
    assert len(sent_messages) == 1
    assert "Question: Approve production deploy?" in sent_messages[0]["text_markdown"]
    async with sessions() as session:
        row = await session.get(NotificationDeliveryRow, claimed_live["id"])
        assert row.status == "sent"


@pytest.mark.anyio
async def test_unpersisted_terminal_status_does_not_emit_premature_success_notification(env):
    from deerflow.persistence.run.model import RunRow
    from deerflow.runtime.runs.manager import RunManager

    sessions, preferences, _, service = env
    await preferences.patch(
        "alice",
        {"run_completed": True, "human_input_requested": True},
    )

    # Case 1: in-memory RunRecord explicitly marked terminal_status_persisted=False.
    unpersisted_record = _make_run(run_id="run-unpersisted-flag", status=RunStatus.success)
    unpersisted_record.terminal_status_persisted = False
    await service.handle_run_completion(unpersisted_record)

    # Case 2: durable RunRow still says "running" because terminal persistence failed.
    async with sessions() as session, session.begin():
        session.add(
            RunRow(
                run_id="run-still-running-in-db",
                thread_id="thread-101",
                assistant_id="lead_agent",
                user_id="alice",
                status="running",
            )
        )
    stale_db_record = _make_run(run_id="run-still-running-in-db", status=RunStatus.success)
    await service.handle_run_completion(stale_db_record)

    async with sessions() as session:
        assert (await session.scalars(select(NotificationDeliveryRow))).all() == []

    # Case 3: RunManager.set_status marks terminal_status_persisted=False when store write fails.
    class FailingRunStore:
        async def put(self, run_id, **kwargs):
            return None

        async def update_status(self, run_id, status, **kwargs):
            raise RuntimeError("db write failed")

    manager = RunManager(store=FailingRunStore())
    created = await manager.create(thread_id="thread-101", assistant_id="lead_agent", user_id="alice")
    await manager.set_status(created.run_id, RunStatus.success, persist=True)
    assert created.terminal_status_persisted is False


@pytest.mark.anyio
@pytest.mark.parametrize("completion_recovers", [False, True])
@pytest.mark.parametrize("outcome", ["completed", "human_input", "failed"])
async def test_worker_notifies_only_after_terminal_status_is_confirmed(env, completion_recovers, outcome):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.agents.thread_state import ThreadState
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.runs.worker import RunContext, run_agent

    sessions, preferences, _, service = env
    await preferences.patch(
        "alice",
        {"run_completed": True, "run_failed": True, "human_input_requested": True, "wecom": False, "wechat": False, "qq": False},
    )

    class FailingTerminalStore(MemoryRunStore):
        async def update_status(self, run_id, status, **kwargs):
            if status not in {"pending", "running"}:
                raise RuntimeError("terminal status write unavailable")
            return await super().update_status(run_id, status, **kwargs)

        async def update_run_completion(self, run_id, *, status, **kwargs):
            if not completion_recovers:
                raise RuntimeError("completion fallback unavailable")
            return await super().update_run_completion(run_id, status=status, **kwargs)

    store = FailingTerminalStore()
    manager = RunManager(store=store)
    record = await manager.create(f"thread-{outcome}-{completion_recovers}", user_id="alice")
    checkpointer = InMemorySaver()

    def fixed_node(state):
        if outcome == "failed":
            raise RuntimeError("fixed execution failure")
        if outcome == "human_input":
            call = {"id": "call-confirm", "name": "ask_clarification", "args": {"question": "Which environment?"}, "type": "tool_call"}
            request = ClarificationMiddleware()._handle_clarification(SimpleNamespace(tool_call=call))
            return {"messages": [AIMessage(content="", tool_calls=[call]), *request.update["messages"]]}
        return {"messages": [AIMessage(content="Fixed completed answer")]}

    builder = StateGraph(ThreadState)
    builder.add_node("fixed", fixed_node)
    builder.add_edge(START, "fixed")
    builder.add_edge("fixed", END)
    graph = builder.compile(checkpointer=checkpointer)
    completion_hook = AsyncMock(wraps=service.handle_run_completion)
    await run_agent(
        SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock()),
        manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, event_store=MemoryRunEventStore(), on_run_completed=completion_hook),
        agent_factory=lambda *, config: graph,
        graph_input={"messages": [HumanMessage(content="Run the fixed task")]},
        config={"configurable": {"thread_id": record.thread_id}},
    )

    stored = await store.get(record.run_id, user_id="alice")
    async with sessions() as session:
        rows = (await session.scalars(select(NotificationDeliveryRow))).all()
    assert record.terminal_status_persisted is completion_recovers
    if completion_recovers:
        assert stored["status"] == record.status.value
        completion_hook.assert_awaited_once_with(record)
        expected_event = {"completed": "run_completed", "human_input": "human_input_requested", "failed": "run_failed"}[outcome]
        assert [(row.run_id, row.event) for row in rows] == [(record.run_id, expected_event)]
    else:
        assert stored["status"] == "running"
        completion_hook.assert_not_awaited()
        assert rows == []


@pytest.mark.anyio
async def test_sqlite_lock_owner_materializes_rows_and_serializes_opt_out(env):
    import asyncio

    from deerflow.persistence.user.im_notifications import ImNotificationPreferenceRow

    sessions, preferences, _, service = env
    # Before any patch, get_in_session(lock_owner=True) on SQLite materializes the 4 provider rows
    # so SQLite acquires an immediate write lock on the transaction's first statement.
    async with sessions() as session, session.begin():
        locked = await ImNotificationPreferencesRepository.get_in_session(
            session,
            "bob",
            lock_owner=True,
            include_events=True,
        )
        assert locked["feishu"] is True
        assert locked["run_completed"] is False
    async with sessions() as session:
        bob_rows = (await session.scalars(select(ImNotificationPreferenceRow).where(ImNotificationPreferenceRow.owner_user_id == "bob"))).all()
        assert len(bob_rows) == 4

    await preferences.patch("alice", {"run_completed": True})
    await asyncio.gather(
        service.handle_run_completion(_make_run(run_id="run-concurrent-optout", status=RunStatus.success)),
        preferences.patch("alice", {"run_completed": False}),
    )
    # After opt-out completes, re-enabling must never leave a pending row from before opt-out
    # if the opt-out ran after enqueue, nor enqueue a row if opt-out ran before enqueue.
    final_events = await preferences.get_event_preferences("alice")
    assert final_events["run_completed"] is False
    async with sessions() as session:
        pending = (
            await session.scalars(
                select(NotificationDeliveryRow).where(
                    NotificationDeliveryRow.run_id == "run-concurrent-optout",
                    NotificationDeliveryRow.status == "pending",
                )
            )
        ).all()
        assert pending == []


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_gateway_notification_delivery_human_input_closure_works_in_both_checkpoint_modes(
    env,
    mode,
    monkeypatch,
):
    from fastapi import FastAPI
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import StateGraph
    from langgraph.store.memory import InMemoryStore

    import app.channels.service as channel_service_mod
    import app.gateway.app as gateway_app_mod
    import app.gateway.deps as gateway_deps
    import app.gateway.services as gateway_services
    from deerflow.agents.thread_state import get_thread_state_schema
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode

    sessions, preferences, deliveries, service = env
    await preferences.patch(
        "alice",
        {"human_input_requested": True, "wecom": False, "wechat": False, "qq": False},
    )

    checkpointer = InMemorySaver()
    store = InMemoryStore()
    thread_store = MemoryThreadMetaStore(store)
    await thread_store.create("thread-gw-ask", assistant_id="lead_agent", user_id="alice")

    state_schema = get_thread_state_schema(mode)

    def _noop_node(state):
        return {}

    builder = StateGraph(state_schema)
    builder.add_node("agent", _noop_node)
    builder.set_entry_point("agent")
    builder.set_finish_point("agent")
    graph = builder.compile(checkpointer=checkpointer)

    monkeypatch.setattr(
        gateway_services,
        "resolve_agent_factory",
        lambda assistant_id=None: lambda config: graph,
    )
    monkeypatch.setattr(gateway_deps, "get_config", lambda: SimpleNamespace(models=[]))

    pending_ai = AIMessage(
        content="",
        id="ai-gw-1",
        tool_calls=[
            {
                "id": "call-gw-1",
                "name": "ask_clarification",
                "args": {"question": "Proceed with migration?", "clarification_type": "confirmation"},
            }
        ],
    )
    prompt_tool = ToolMessage(
        content="Proceed with migration?",
        id="tool-gw-1",
        tool_call_id="call-gw-1",
        name="ask_clarification",
        artifact={
            "human_input": {
                "version": 1,
                "kind": "human_input_request",
                "source": "ask_clarification",
                "request_id": "req-gw-1",
                "question": "Proceed with migration?",
            }
        },
    )
    config = {"configurable": {"thread_id": "thread-gw-ask", "checkpoint_ns": ""}}
    inject_checkpoint_mode(config, mode)
    await graph.ainvoke(
        {"messages": [HumanMessage(content="Start", id="h-gw-1"), pending_ai, prompt_tool]},
        config,
    )

    sent_messages = []

    class FakeChannel:
        is_running = True

        async def send_notification_for_owner(self, **kwargs):
            sent_messages.append(kwargs)

    fake_channel_service = SimpleNamespace(
        get_channel=lambda provider: FakeChannel() if provider == "feishu" else None,
        notification_excluded_providers=lambda: frozenset(),
    )
    monkeypatch.setattr(channel_service_mod, "get_channel_service", lambda: fake_channel_service)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: sessions)

    app = FastAPI()
    app.state.scheduled_task_service = service
    app.state.checkpointer = checkpointer
    app.state.store = store
    app.state.thread_store = thread_store
    app.state.run_event_store = SimpleNamespace()
    app.state.checkpoint_channel_mode = mode
    app.state.checkpoint_snapshot_frequency = None

    startup_config = SimpleNamespace(
        scheduler=SimpleNamespace(poll_interval_seconds=60),
        channel_connections=SimpleNamespace(notification_locale="en-US"),
    )
    conn_repo = SimpleNamespace(
        list_connections=lambda user_id: [
            {
                "id": "personal-feishu",
                "owner_user_id": user_id,
                "provider": "feishu",
                "status": "connected",
                "external_account_id": "feishu-user",
            }
        ]
    )

    await gateway_app_mod._start_scheduled_task_notification_delivery(
        app,
        startup_config,
        deliveries,
        conn_repo,
    )
    worker = app.state.notification_delivery_worker
    try:
        # 1. Unanswered request in checkpoint -> gateway closure returns True and delivers.
        await service.handle_run_completion(
            _make_run(
                run_id=f"run-gw-live-{mode}",
                thread_id="thread-gw-ask",
                status=RunStatus.success,
                human_input_request={"request_id": "req-gw-1", "question": "Proceed with migration?"},
            )
        )
        await worker.run_once(now=datetime.now(UTC))
        assert len(sent_messages) == 1

        # 2. User answers in checkpoint -> gateway closure returns False and marks terminal failed.
        answer_msg = HumanMessage(
            content="Yes",
            id="h-gw-2",
            additional_kwargs={
                HUMAN_INPUT_RESPONSE_KEY: {
                    "version": 1,
                    "kind": "human_input_response",
                    "request_id": "req-gw-1",
                }
            },
        )
        await graph.ainvoke({"messages": [answer_msg]}, config)
        await service.handle_run_completion(
            _make_run(
                run_id=f"run-gw-answered-{mode}",
                thread_id="thread-gw-ask",
                status=RunStatus.success,
                human_input_request={"request_id": "req-gw-2", "question": "Proceed with migration?"},
            )
        )
        await worker.run_once(now=datetime.now(UTC))
        assert len(sent_messages) == 1
        async with sessions() as session:
            rows = (await session.scalars(select(NotificationDeliveryRow).where(NotificationDeliveryRow.run_id == f"run-gw-answered-{mode}"))).all()
            assert len(rows) == 1
            assert (rows[0].status, rows[0].last_error) == ("failed", "human_input_request_already_resolved")
    finally:
        await worker.stop()

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

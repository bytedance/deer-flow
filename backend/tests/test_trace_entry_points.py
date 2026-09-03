"""Trace binding at the entry points that no ASGI middleware can reach.

``TraceMiddleware`` covers Gateway HTTP traffic (``test_trace_middleware.py``)
and ``DeerFlowClient.stream`` covers embedded callers
(``test_client_langfuse_metadata.py``). The remaining ways work enters DeerFlow
hold no HTTP request at all: the scheduled-task poller, MCP task notification
runs, and IM channels, which keep long-lived provider connections. Each must
bind a trace id of its own, scoped to one unit of work, or everything
downstream falls back to an unattributed id.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import ChannelStore
from app.scheduler.service import ScheduledTaskService
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.trace_context import get_current_trace_id, request_trace_context

# --------------------------------------------------------------------------
# Scheduled tasks
# --------------------------------------------------------------------------


class _StubTaskRepo:
    def __init__(self, rows):
        self.rows = rows
        self.claimed = False

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return self.rows

    async def claim_dispatch_lease(self, task_id, **_kwargs):
        return next((dict(row) for row in self.rows if row["id"] == task_id), None)

    async def release_queued_admission_lease(self, task_id):
        return False

    async def release_dispatch_lease(self, task_id, **_kwargs):
        return True

    async def get_internal(self, task_id):
        row = next((item for item in self.rows if item["id"] == task_id), None)
        return dict(row) if row is not None else None

    async def update_after_launch(self, *_args, **_kwargs):
        return None


class _StubRunRepo:
    async def list_queued_runs(self, *, limit):
        return []

    async def expire_queued_runs(self, **_kwargs):
        return []

    async def recover_expired_launch_claims(self, **_kwargs):
        return 0

    async def get_active_run(self, task_id):
        return None

    async def claim_queued_run(self, run_record_id, **_kwargs):
        return {"id": run_record_id, "status": "launching"}

    async def create(self, **kwargs):
        return {"id": kwargs["run_record_id"]}

    async def reconcile_launched_run(self, run_record_id, **_kwargs):
        return True

    async def update_status(self, run_record_id, **_kwargs):
        return True


def _scheduled_task(task_id: str) -> dict:
    return {
        "id": task_id,
        "user_id": "user-1",
        "thread_id": f"thread-{task_id}",
        "context_mode": "reuse_thread",
        "assistant_id": "lead_agent",
        "prompt": "Summarize thread",
        "schedule_type": "once",
        "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
        "timezone": "UTC",
    }


def _make_service(rows, launch_run) -> ScheduledTaskService:
    return ScheduledTaskService(
        task_repo=_StubTaskRepo(rows),
        task_run_repo=_StubRunRepo(),
        launch_run=launch_run,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )


@pytest.mark.asyncio
async def test_scheduled_launch_runs_under_a_bound_trace_id():
    launched: list[str | None] = []

    async def fake_launch(**kwargs):
        launched.append(get_current_trace_id())
        return {"run_id": "run-1", "thread_id": kwargs["thread_id"]}

    service = _make_service([_scheduled_task("task-1")], fake_launch)

    await service.run_once(now=datetime.now(UTC) + timedelta(days=1))

    assert launched == [launched[0]]
    assert launched[0], "a scheduled occurrence must not launch without a trace id"


@pytest.mark.asyncio
async def test_each_scheduled_occurrence_gets_its_own_trace_id():
    """One id per poll cycle would merge unrelated tasks into a single trace."""
    launched: list[str | None] = []

    async def fake_launch(**kwargs):
        launched.append(get_current_trace_id())
        return {"run_id": "run-1", "thread_id": kwargs["thread_id"]}

    service = _make_service([_scheduled_task("task-1"), _scheduled_task("task-2")], fake_launch)

    await service.run_once(now=datetime.now(UTC) + timedelta(days=1))

    assert len(launched) == 2
    assert all(launched)
    assert launched[0] != launched[1]


@pytest.mark.asyncio
async def test_scheduled_trace_scope_closes_after_the_occurrence():
    """The poller task is long-lived, so a leaked binding would attribute every
    later cycle to the first occurrence it ever ran."""

    async def fake_launch(**kwargs):
        return {"run_id": "run-1", "thread_id": kwargs["thread_id"]}

    service = _make_service([_scheduled_task("task-1")], fake_launch)

    await service.run_once(now=datetime.now(UTC) + timedelta(days=1))

    assert get_current_trace_id() is None


@pytest.mark.asyncio
async def test_manual_trigger_keeps_the_requesting_trace():
    """A manual trigger arrives inside a Gateway request, so the launched run
    stays correlated with the call that asked for it."""
    launched: list[str | None] = []

    async def fake_launch(**kwargs):
        launched.append(get_current_trace_id())
        return {"run_id": "run-1", "thread_id": kwargs["thread_id"]}

    task = _scheduled_task("task-1")
    service = _make_service([task], fake_launch)

    with request_trace_context("gateway-request-1"):
        await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")

    assert launched == ["gateway-request-1"]


# --------------------------------------------------------------------------
# IM channels
# --------------------------------------------------------------------------


def _inbound(index: int) -> InboundMessage:
    return InboundMessage(
        channel_name="slack",
        chat_id="C1",
        user_id="U1",
        text=f"message-{index}",
        metadata={},
    )


@pytest.mark.asyncio
async def test_inbound_messages_are_handled_under_distinct_trace_scopes(tmp_path: Path):
    """Channels hold long-lived provider connections, so no ASGI middleware
    ever runs for them, and one worker task serves many messages in sequence."""
    bus = MessageBus(inbound_queue_maxsize=4)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=1,
    )
    seen: list[str | None] = []

    async def capture_handler(msg: InboundMessage) -> None:
        seen.append(get_current_trace_id())

    manager._handle_message = capture_handler  # type: ignore[method-assign]
    await manager.start()
    try:
        await bus.publish_inbound(_inbound(0))
        await bus.publish_inbound(_inbound(1))
        async with asyncio.timeout(2):
            while len(seen) < 2:
                await asyncio.sleep(0)
    finally:
        await manager.stop()

    assert all(seen), "an inbound message must not be handled without a trace id"
    assert seen[0] != seen[1], "each message is its own unit of work"
    assert get_current_trace_id() is None


# --------------------------------------------------------------------------
# Gateway run launchers
# --------------------------------------------------------------------------


@pytest.fixture
def _stub_app_config():
    """Keep the launchers independent from a developer-local config.yaml."""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


@pytest.fixture
def launcher_traces(monkeypatch):
    """Capture the trace id bound around each ``start_run`` the launchers make."""
    seen: list[str | None] = []

    async def fake_start_run(_body, thread_id, _request, **_kwargs):
        seen.append(get_current_trace_id())
        return SimpleNamespace(run_id="run-1", thread_id=thread_id)

    monkeypatch.setattr("app.gateway.services.start_run", fake_start_run)
    return seen


@pytest.mark.asyncio
async def test_scheduled_launcher_binds_a_trace_context(_stub_app_config, launcher_traces):
    from app.gateway.services import launch_scheduled_thread_run

    await launch_scheduled_thread_run(
        app=SimpleNamespace(),
        thread_id="thread-sched",
        assistant_id="lead_agent",
        prompt="Summarize thread",
        owner_user_id="user-1",
        metadata={"scheduled_task_run_id": "run-row-1"},
    )

    assert launcher_traces[0], "a scheduled launch must not reach start_run untraced"
    assert get_current_trace_id() is None


@pytest.mark.asyncio
async def test_mcp_notification_launcher_binds_a_trace_context(_stub_app_config, launcher_traces):
    """Driven from the MCP task service's own background loop, so one scope per
    notification keeps every delivery attempt separately correlatable."""
    from app.gateway.services import launch_mcp_task_notification_run

    for attempt in (1, 2):
        await launch_mcp_task_notification_run(
            app=SimpleNamespace(),
            thread_id="thread-mcp",
            assistant_id="lead_agent",
            owner_user_id="user-1",
            task_id="task-1",
            dispatch_version=1,
            dispatch_attempt=attempt,
            event={"status": "completed"},
        )

    assert all(launcher_traces)
    assert launcher_traces[0] != launcher_traces[1]
    assert get_current_trace_id() is None


@pytest.mark.asyncio
async def test_launcher_keeps_the_requesting_trace(_stub_app_config, launcher_traces):
    """Reached from inside a Gateway request -- a manual scheduled trigger --
    the launched run stays correlated with the call that asked for it."""
    from app.gateway.services import launch_scheduled_thread_run

    with request_trace_context("gateway-request-1"):
        await launch_scheduled_thread_run(
            app=SimpleNamespace(),
            thread_id="thread-sched",
            assistant_id="lead_agent",
            prompt="Summarize thread",
            owner_user_id="user-1",
        )

    assert launcher_traces == ["gateway-request-1"]

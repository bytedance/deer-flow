"""Exercise task snapshots and notification commits through the real scheduler."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.scheduler.notification_delivery import render_notification_text
from app.scheduler.service import ScheduledTaskService
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.channel_connections.model import ChannelConnectionRow
from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository, NotificationDeliveryRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.runtime import RunStatus


@pytest.fixture
async def scheduler(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    tasks, occurrences = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    deliveries, connections = NotificationDeliveryRepository(sf), ChannelConnectionRepository(sf)
    launches = []

    async def launch(**kwargs):
        launches.append(kwargs)
        run_id = f"run-{len(launches)}"
        async with sf() as session:
            session.add(RunRow(run_id=run_id, thread_id=kwargs["thread_id"], user_id=kwargs["owner_user_id"], status="running", metadata_json=kwargs["metadata"]))
            await session.commit()
        return {"run_id": run_id, "thread_id": kwargs["thread_id"]}

    service = ScheduledTaskService(task_repo=tasks, task_run_repo=occurrences, launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=3, connection_repo=connections, notification_repo=deliveries)
    try:
        yield sf, tasks, occurrences, service, launches, deliveries
    finally:
        await close_engine()


async def create_task(tasks, **extra):
    return await tasks.create(
        task_id="task-a",
        user_id="owner",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Meeting preparation",
        prompt="Read the supplied materials and prepare the meeting.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=datetime.now(UTC),
        origin_thread_id="origin",
        **extra,
    )


async def finish(sf, service, launch, result, *, verdict=None):
    async with sf() as session:
        row = await session.get(RunRow, result["run_id"])
        row.status = "success"
        row.goal_verdict = verdict
        await session.commit()
    record = SimpleNamespace(run_id=result["run_id"], user_id="owner", metadata=launch["metadata"], status=RunStatus.success, error=None, goal_verdict=verdict)
    await service.handle_run_completion(record)


async def dispatch_scheduled(tasks, service):
    now = datetime.now(UTC)
    await tasks.update("task-a", user_id="owner", updates={"next_run_at": now})
    claimed = await tasks.claim_due_tasks(now=now, lease_owner=service._lease_owner, lease_seconds=120, limit=1)
    assert len(claimed) == 1
    return await service.dispatch_task(claimed[0], now=now, trigger="scheduled")


@pytest.mark.anyio
async def test_launch_snapshots_goal_and_explicit_task_notes(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    task = await create_task(tasks, goal_objective="Meeting preparation is complete", standing_notes=["Use the develop branch"])
    result = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    assert result["outcome"] == "launched"
    assert "Use the develop branch" in launches[0]["prompt"]
    assert launches[0]["metadata"]["scheduled_goal_objective"] == task["goal_objective"]
    async with sf() as session:
        rows = list((await session.scalars(select(NotificationDeliveryRow))).all())
        assert rows == []


@pytest.mark.anyio
async def test_next_fresh_occurrence_carries_only_the_previous_executed_thread(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    task = await create_task(tasks)
    first = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    await finish(sf, service, launches[0], first)
    current = await tasks.get("task-a", user_id="owner")
    second = await service.dispatch_task(current, now=datetime.now(UTC), trigger="manual")
    assert second["outcome"] == "launched"
    assert launches[1]["metadata"]["scheduled_previous_thread_id"] == first["thread_id"]
    assert second["thread_id"] != first["thread_id"]


@pytest.mark.anyio
async def test_auto_pause_and_notice_share_the_completion_transaction(scheduler, monkeypatch):
    sf, tasks, _occurrences, service, launches, deliveries = scheduler
    await create_task(tasks, goal_objective="Meeting preparation is complete")
    async with sf() as session:
        session.add(ChannelConnectionRow(id="owner-connection", owner_user_id="owner", provider="wecom", external_account_id="owner-wecom", status="connected"))
        session.add(ChannelConnectionRow(id="foreign-connection", owner_user_id="foreign", provider="wecom", external_account_id="foreign-wecom", status="connected"))
        await session.commit()
    verdict = {"satisfied": False, "blocker": "needs_user_input", "reason": "Required materials are missing", "relied_on_assumption": False, "stand_down_reason": "blocked:needs_user_input"}
    for _ in range(2):
        result = await dispatch_scheduled(tasks, service)
        await finish(sf, service, launches[-1], result, verdict=verdict)
    result = await dispatch_scheduled(tasks, service)
    original = deliveries.enqueue_in_session

    async def fail_notice(*args, **kwargs):
        if kwargs["event"] == "task_paused":
            raise RuntimeError("outbox temporarily unavailable")
        return await original(*args, **kwargs)

    monkeypatch.setattr(deliveries, "enqueue_in_session", fail_notice)
    with pytest.raises(RuntimeError, match="outbox temporarily unavailable"):
        await finish(sf, service, launches[-1], result, verdict=verdict)
    assert (await tasks.get("task-a", user_id="owner"))["status"] == "enabled"
    monkeypatch.setattr(deliveries, "enqueue_in_session", original)
    await finish(sf, service, launches[-1], result, verdict=verdict)
    assert (await tasks.get("task-a", user_id="owner"))["status"] == "paused"
    async with sf() as session:
        rows = list((await session.scalars(select(NotificationDeliveryRow))).all())
        assert [row.event for row in rows].count("task_paused") == 1
        assert {row.target for row in rows} == {"owner-wecom"}


def test_unmet_and_pause_notifications_have_distinct_safe_text():
    unmet = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": "blocked:needs_user_input", "error": "private raw failure"}})
    paused = render_notification_text({"event": "task_paused", "task_id": "task-a", "payload": {"reason_code": "consecutive_unmet", "latest_reason_code": "blocked:needs_user_input"}})
    assert "Ran, but the goal wasn't met: it needs your input." in unmet
    assert "needs_user_input" not in unmet
    assert "private raw failure" not in unmet
    assert "Paused after 3 runs in a row missed the goal: it needs your input." in paused
    assert "consecutive_unmet" not in paused
    assert "Finished a run" not in unmet + paused


def test_assumption_marker_is_visible_without_forwarding_raw_error_text():
    text = render_notification_text({"event": "run_completed", "task_id": "task-a", "payload": {"relied_on_assumption": True, "result_summary": "Report is ready"}})
    assert "Goal met, with an assumption." in text


@pytest.mark.anyio
async def test_end_reached_at_atomic_admission_reports_completed(scheduler, monkeypatch):
    _sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks)
    now = datetime.now(UTC)
    claimed = await tasks.claim_due_tasks(now=now, lease_owner=service._lease_owner, lease_seconds=120, limit=1)
    assert len(claimed) == 1
    # The preliminary check observed a live task; its deadline changes before
    # occurrence admission takes the authoritative parent lock.
    await tasks.update("task-a", user_id="owner", updates={"end_at": now - timedelta(seconds=1)})

    async def preliminary_check(*_args, **_kwargs):
        return False

    monkeypatch.setattr(tasks, "complete_if_ended", preliminary_check)
    result = await service.dispatch_task(claimed[0], now=now, trigger="scheduled")
    assert result["outcome"] == "completed"
    assert launches == []
    assert (await tasks.get("task-a", user_id="owner"))["status"] == "completed"


@pytest.mark.anyio
@pytest.mark.parametrize("outcomes", [("external_wait",) * 3, ("goal_not_met_yet", "goal_not_met_yet", "external_wait", "goal_not_met_yet")])
async def test_external_wait_does_not_advance_unmet_streak(scheduler, outcomes):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    for index, blocker in enumerate(outcomes):
        result = await dispatch_scheduled(tasks, service)
        verdict = {"satisfied": False, "blocker": blocker, "reason": "synthetic independent dependency", "stand_down_reason": f"blocked:{blocker}", "relied_on_assumption": False}
        await finish(sf, service, launches[-1], result, verdict=verdict)
        status = (await tasks.get("task-a", user_id="owner"))["status"]
        assert status == ("paused" if index == 3 else "enabled")


@pytest.mark.parametrize(
    ("reason", "readable"),
    [
        ("token_capped", "the token budget was reached"),
        ("no_durable_end_of_turn", "no final reply was saved"),
        ("thread_changed_after_evaluation", "the conversation changed during the goal check"),
        ("thread_changed_before_continuation", "the conversation changed during the goal check"),
        ("blocked:missing_evidence", "the goal check found evidence missing"),
        ("missing_evidence", "the goal check found evidence missing"),
        ("no_verdict", "no goal verdict was recorded"),
    ],
)
def test_known_host_stand_down_reasons_are_reported_readably(reason, readable):
    text = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": reason}})
    assert f"Ran, but the goal wasn't met: {readable}." in text
    assert reason not in text


def test_unknown_reason_code_is_not_forwarded():
    text = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": "provider said: secret"}})
    # An unrecognized code adds nothing: the reason-less sentence.
    assert "Ran, but the goal wasn't met." in text.splitlines()
    assert "secret" not in text


UNMET = {"satisfied": False, "blocker": "goal_not_met_yet", "reason": "not yet", "stand_down_reason": "blocked:goal_not_met_yet", "relied_on_assumption": False}


def unmet_verdict(code="blocked:goal_not_met_yet"):
    return {**UNMET, "stand_down_reason": code}


async def create_page_task(tasks, **extra):
    """A task created on the tasks page: no originating conversation."""
    return await tasks.create(
        task_id="task-a",
        user_id="owner",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Meeting preparation",
        prompt="Read the supplied materials and prepare the meeting.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=datetime.now(UTC),
        **extra,
    )


async def scheduled_miss(sf, tasks, service, launches, verdict=None):
    result = await dispatch_scheduled(tasks, service)
    await finish(sf, service, launches[-1], result, verdict=verdict or UNMET)
    return (await tasks.get("task-a", user_id="owner"))["status"]


async def streak_boundary(sf):
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

    async with sf() as session:
        row = await session.get(ScheduledTaskRow, "task-a")
        return row.unmet_streak_after_seq, row.last_occurrence_seq


@pytest.mark.anyio
async def test_goal_edit_moves_streak_boundary(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    assert [await scheduled_miss(sf, tasks, service, launches) for _ in range(2)] == ["enabled", "enabled"]
    await tasks.update("task-a", user_id="owner", updates={"goal_objective": "report is ready and reviewed"}, require_mutable=True)
    assert await scheduled_miss(sf, tasks, service, launches) == "enabled"
    assert await scheduled_miss(sf, tasks, service, launches) == "enabled"
    assert await scheduled_miss(sf, tasks, service, launches) == "paused"


@pytest.mark.anyio
async def test_prompt_and_note_changes_move_boundary(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    for _ in range(2):
        await scheduled_miss(sf, tasks, service, launches)
    await tasks.update("task-a", user_id="owner", updates={"prompt": "Prepare the meeting from the new folder."}, require_mutable=True)
    for _ in range(2):
        assert await scheduled_miss(sf, tasks, service, launches) == "enabled"
    await tasks.append_standing_note("task-a", user_id="owner", note="Use the develop branch")
    for _ in range(2):
        assert await scheduled_miss(sf, tasks, service, launches) == "enabled"
    assert await scheduled_miss(sf, tasks, service, launches) == "paused"


@pytest.mark.anyio
async def test_stop_condition_change_moves_boundary(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    for value in ("every item is checked", "the release shipped", None):
        await scheduled_miss(sf, tasks, service, launches)
        await tasks.update("task-a", user_id="owner", updates={"stop_condition": value}, require_mutable=True)
        boundary, last_seq = await streak_boundary(sf)
        assert boundary == last_seq
    assert (await tasks.get("task-a", user_id="owner"))["stop_condition"] is None


@pytest.mark.anyio
async def test_noop_edit_keeps_boundary(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready", stop_condition="every item is checked")
    await scheduled_miss(sf, tasks, service, launches)
    await tasks.update("task-a", user_id="owner", updates={"goal_objective": "report is ready", "stop_condition": "every item is checked", "title": "Renamed"}, require_mutable=True)
    assert (await streak_boundary(sf))[0] is None


@pytest.mark.anyio
async def test_resume_does_not_reset_streak(scheduler):
    from app.gateway.scheduled_task_validation import prepare_resume_updates
    from deerflow.persistence.scheduled_task_runs.finalization import AUTO_PAUSE_LAST_ERROR

    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    assert [await scheduled_miss(sf, tasks, service, launches) for _ in range(3)] == ["enabled", "enabled", "paused"]
    paused = await tasks.get("task-a", user_id="owner")
    assert paused["last_error"] == AUTO_PAUSE_LAST_ERROR
    updates = prepare_resume_updates(paused, {}, used=3, now=datetime.now(UTC))
    resumed = await tasks.update("task-a", user_id="owner", updates=updates, require_mutable=True)
    assert resumed["status"] == "enabled"
    assert resumed["last_error"] is None
    assert await scheduled_miss(sf, tasks, service, launches) == "paused"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (("evaluator_failed",) * 3, ["enabled"] * 3),
        (("unmet", "unmet", "evaluator_failed", "unmet"), ["enabled", "enabled", "enabled", "paused"]),
        (("no_durable_end_of_turn", "thread_changed_after_evaluation", "thread_changed_before_continuation"), ["enabled"] * 3),
    ],
)
async def test_goal_check_failures_neither_count_nor_reset(scheduler, outcomes, expected):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    statuses = [await scheduled_miss(sf, tasks, service, launches, unmet_verdict() if outcome == "unmet" else unmet_verdict(outcome)) for outcome in outcomes]
    assert statuses == expected


@pytest.mark.anyio
async def test_page_created_goal_task_is_evaluated(scheduler):
    sf, tasks, occurrences, service, launches, _deliveries = scheduler
    task = await create_page_task(tasks, goal_objective="Meeting preparation is complete")
    result = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    assert result["outcome"] == "launched"
    metadata = launches[0]["metadata"]
    assert metadata["scheduled_goal_objective"] == "Meeting preparation is complete"
    assert metadata["scheduled_context_mode"] == "fresh_thread_per_run"
    assert "scheduled_tool_created" not in metadata
    await finish(sf, service, launches[0], result, verdict={"satisfied": True, "relied_on_assumption": False, "reason": "done"})
    assert (await occurrences.list_by_task("task-a"))[0]["status"] == "success"


@pytest.mark.anyio
async def test_page_created_task_gets_previous_reference_and_notes(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    task = await create_page_task(tasks, standing_notes=["Use the develop branch", "Cite every source"])
    first = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    await finish(sf, service, launches[0], first)
    second = await service.dispatch_task(await tasks.get("task-a", user_id="owner"), now=datetime.now(UTC), trigger="manual")
    assert second["outcome"] == "launched"
    assert launches[1]["metadata"]["scheduled_previous_thread_id"] == first["thread_id"]
    assert launches[1]["prompt"] == "Read the supplied materials and prepare the meeting.\n\n<standing_notes>\n- Use the develop branch\n- Cite every source\n</standing_notes>"


@pytest.mark.anyio
@pytest.mark.parametrize("marker_kind", ["agent_stop", "auto_pause"])
@pytest.mark.parametrize("trial_outcome", ["success", "failure", "launch_failure"])
async def test_trial_on_paused_task_keeps_pause_marker(scheduler, marker_kind, trial_outcome):
    from deerflow.persistence.scheduled_task_runs.finalization import AGENT_STOP_LAST_ERROR_PREFIX, AUTO_PAUSE_LAST_ERROR

    sf, tasks, occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks)
    marker = f"{AGENT_STOP_LAST_ERROR_PREFIX}run-earlier" if marker_kind == "agent_stop" else AUTO_PAUSE_LAST_ERROR
    paused = await tasks.update("task-a", user_id="owner", updates={"status": "paused", "last_error": marker})
    if trial_outcome == "launch_failure":

        async def failing_launch(**_kwargs):
            raise RuntimeError("model provider unavailable")

        service._launch_run = failing_launch
    result = await service.dispatch_task(paused, now=datetime.now(UTC), trigger="manual")
    if trial_outcome == "launch_failure":
        assert result["outcome"] == "failed"
    else:
        assert result["outcome"] == "launched"
        assert (await tasks.get("task-a", user_id="owner"))["last_error"] == marker
        if trial_outcome == "success":
            await finish(sf, service, launches[-1], result)
        else:
            record = SimpleNamespace(run_id=result["run_id"], user_id="owner", metadata=launches[-1]["metadata"], status=RunStatus.error, error="boom", goal_verdict=None)
            await service.handle_run_completion(record)
    current = await tasks.get("task-a", user_id="owner")
    assert current["status"] == "paused"
    assert current["last_error"] == marker
    run = (await occurrences.list_by_task("task-a"))[0]
    assert run["trigger"] == "manual"
    assert run["status"] == {"success": "success", "failure": "failed", "launch_failure": "failed"}[trial_outcome]


def _live_scheduler_config(monkeypatch, *, tool_enabled):
    from deerflow.config import app_config

    live = SimpleNamespace(scheduler=SimpleNamespace(enabled=True, tool_enabled=tool_enabled))
    monkeypatch.setattr(app_config, "get_app_config", lambda: live)
    return live


@pytest.mark.anyio
async def test_launch_appends_stop_rule_only_at_launch(scheduler, monkeypatch):
    from deerflow.scheduler.stop_rule import STOP_RULE_PREFIX

    _live_scheduler_config(monkeypatch, tool_enabled=True)
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    stored_prompt = "Read the supplied materials and prepare the meeting."
    task = await create_page_task(tasks, stop_condition="every item on the checklist is checked")
    await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    assert launches[0]["prompt"] == f"{stored_prompt}\n\n{STOP_RULE_PREFIX}every item on the checklist is checked"
    stored = await tasks.get("task-a", user_id="owner")
    assert stored["prompt"] == stored_prompt
    assert stored["stop_condition"] == "every item on the checklist is checked"
    await finish(sf, service, launches[0], {"run_id": "run-1"})
    await tasks.update("task-a", user_id="owner", updates={"stop_condition": None}, require_mutable=True)
    await service.dispatch_task(await tasks.get("task-a", user_id="owner"), now=datetime.now(UTC), trigger="manual")
    assert launches[1]["prompt"] == stored_prompt


@pytest.mark.anyio
async def test_launch_prompt_without_own_stop(scheduler):
    from deerflow.scheduler.stop_rule import STOP_RULE_NO_TOOL_PREFIX

    _sf, tasks, occurrences, service, launches, _deliveries = scheduler
    without_tool = ScheduledTaskService(task_repo=tasks, task_run_repo=occurrences, launch_run=service._launch_run, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=3, own_stop_available=False)
    task = await create_page_task(tasks, stop_condition="the release shipped")
    await without_tool.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    assert launches[0]["prompt"].endswith(f"\n\n{STOP_RULE_NO_TOOL_PREFIX}the release shipped")
    assert "stop_scheduled_task" not in launches[0]["prompt"]


@pytest.mark.anyio
async def test_stop_rule_phrasing_follows_the_live_tool_setting(scheduler, monkeypatch):
    from deerflow.scheduler.stop_rule import STOP_RULE_NO_TOOL_PREFIX, STOP_RULE_PREFIX

    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    live = _live_scheduler_config(monkeypatch, tool_enabled=True)
    task = await create_page_task(tasks, stop_condition="the release shipped")
    await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    assert launches[0]["prompt"].endswith(f"\n\n{STOP_RULE_PREFIX}the release shipped")
    await finish(sf, service, launches[0], {"run_id": "run-1"})
    # A config reload turns the tool off: the next launch must not mention it.
    live.scheduler.tool_enabled = False
    await service.dispatch_task(await tasks.get("task-a", user_id="owner"), now=datetime.now(UTC), trigger="manual")
    assert launches[1]["prompt"].endswith(f"\n\n{STOP_RULE_NO_TOOL_PREFIX}the release shipped")
    assert "stop_scheduled_task" not in launches[1]["prompt"]

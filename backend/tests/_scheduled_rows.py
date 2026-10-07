"""Row builders shared by the scheduled-task repository listing tests."""

from datetime import UTC, datetime, timedelta

from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow

BASE = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)


async def create_task(repo, task_id="task-1", *, user_id="user-1", origin_thread_id=None, thread_id=None, context_mode="fresh_thread_per_run", **extra):
    return await repo.create(
        task_id=task_id,
        user_id=user_id,
        thread_id=thread_id,
        context_mode=context_mode,
        assistant_id="lead_agent",
        title=task_id,
        prompt="Summarize the notifications.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=BASE,
        origin_thread_id=origin_thread_id,
        **extra,
    )


def occurrence(record_id, task_id="task-1", *, seq, trigger="scheduled", status="success", accounted=True, thread_id=None, run_id=None, error=None, goal_verdict=None):
    created_at = BASE + timedelta(minutes=seq if seq is not None else 0)
    return ScheduledTaskRunRow(
        id=record_id,
        task_id=task_id,
        occurrence_seq=seq,
        launch_accounted=accounted,
        thread_id=thread_id or f"thread-{record_id}",
        run_id=run_id,
        scheduled_for=created_at,
        trigger=trigger,
        status=status,
        error=error,
        goal_verdict=goal_verdict,
        created_at=created_at,
    )


def durable_run(run_id, *, thread_id, user_id="user-1", total_tokens=0, last_ai_message=None):
    return RunRow(run_id=run_id, thread_id=thread_id, user_id=user_id, status="success", total_tokens=total_tokens, last_ai_message=last_ai_message)

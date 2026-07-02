from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from deerflow.scheduler import core as scheduler_core
from deerflow.scheduler.core import ExecutionResult, Scheduler
from deerflow.scheduler.triggers import CronTrigger


def _cron_job(job_id: str, *, next_run_at: datetime) -> dict[str, Any]:
    return {
        "id": job_id,
        "user_id": f"user-{job_id}",
        "trigger_type": "cron",
        "trigger_data": {"kind": "cron", "expr": "0 * * * *", "tz": "UTC"},
        "next_run_at": next_run_at.isoformat(),
        "consecutive_errors": 0,
        "delete_after_run": False,
    }


class _RecordingRepo:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def list_all_enabled_jobs(self) -> list[dict[str, Any]]:
        return list(self.jobs)

    async def list_due_jobs(self, *, now: datetime, limit: int = 200) -> list[dict[str, Any]]:
        return list(self.jobs)

    async def update_scheduling_state(self, job_id: str, **kwargs: Any) -> dict[str, Any] | None:
        self.updates.append((job_id, kwargs))
        return None

    async def delete_job(self, job_id: str, *, user_id: str | None = None) -> bool:
        return True

    async def disable_job(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        self.updates.append((job_id, {"enabled": False, "user_id": user_id}))
        return None


class _BlockingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.done = asyncio.Event()

    async def execute(self, job: dict[str, Any]) -> ExecutionResult:
        self.started.set()
        await self.release.wait()
        self.done.set()
        return ExecutionResult(status="ok")


@pytest.mark.asyncio
async def test_recover_missed_runs_uses_job_id_for_cron_stagger(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    monkeypatch.setattr(scheduler_core, "_utc_now", lambda: now)
    repo = _RecordingRepo(
        [
            _cron_job("job-a", next_run_at=now - timedelta(hours=2)),
            _cron_job("job-b", next_run_at=now - timedelta(hours=2)),
        ]
    )
    scheduler = Scheduler(repo, _BlockingExecutor())

    await scheduler._recover_missed_runs()

    expected_a = CronTrigger("0 * * * *", tz="UTC").compute_next(now, now=now, job_id="job-a")
    expected_b = CronTrigger("0 * * * *", tz="UTC").compute_next(now, now=now, job_id="job-b")
    assert repo.updates == [
        ("job-a", {"next_run_at": expected_a, "user_id": None}),
        ("job-b", {"next_run_at": expected_b, "user_id": None}),
    ]
    assert expected_a != expected_b


@pytest.mark.asyncio
async def test_tick_tentative_bump_uses_job_id_for_cron_stagger(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    monkeypatch.setattr(scheduler_core, "_utc_now", lambda: now)
    repo = _RecordingRepo([_cron_job("job-a", next_run_at=now - timedelta(minutes=1))])
    executor = _BlockingExecutor()
    scheduler = Scheduler(repo, executor)

    await scheduler._tick()
    await asyncio.wait_for(executor.started.wait(), timeout=1)

    expected = CronTrigger("0 * * * *", tz="UTC").compute_next(now, now=now, job_id="job-a")
    assert repo.updates[0] == ("job-a", {"next_run_at": expected, "user_id": None})

    executor.release.set()
    await asyncio.wait_for(executor.done.wait(), timeout=1)
    for _ in range(10):
        if len(repo.updates) >= 2:
            break
        await asyncio.sleep(0)


def _every_job(job_id: str, *, next_run_at: datetime, every_seconds: int = 120) -> dict[str, Any]:
    return {
        "id": job_id,
        "user_id": f"user-{job_id}",
        "trigger_type": "every",
        "trigger_data": {"kind": "every", "every_seconds": every_seconds},
        "next_run_at": next_run_at.isoformat(),
        "consecutive_errors": 0,
        "delete_after_run": False,
    }


@pytest.mark.asyncio
async def test_finalise_every_job_anchors_next_run_on_fired_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unanchored ``every`` jobs must keep a strict interval.

    The job was scheduled to fire at 00:00:00 but finished at 00:00:10
    (10s execution). The next run must be 00:02:00 (fired_at + every),
    NOT 00:02:10 (finish + every) — otherwise the cadence drifts by the
    execution duration every cycle. See scheduler/core.py _finalise.
    """
    fired_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    finish_at = fired_at + timedelta(seconds=10)
    monkeypatch.setattr(scheduler_core, "_utc_now", lambda: finish_at)

    repo = _RecordingRepo([])
    scheduler = Scheduler(repo, _BlockingExecutor())
    job = _every_job("job-e", next_run_at=fired_at, every_seconds=120)

    await scheduler._finalise(job, ExecutionResult(status="ok"), finish_at)

    expected_next = fired_at + timedelta(seconds=120)
    assert repo.updates == [
        (
            "job-e",
            {
                "next_run_at": expected_next,
                "last_run_at": finish_at,
                "last_status": "ok",
                "consecutive_errors": 0,
                "next_retry_at": None,
                "user_id": None,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_tick_tentative_bump_anchors_on_fired_slot_for_every(monkeypatch: pytest.MonkeyPatch) -> None:
    """The optimistic bump also anchors on the fired slot, so the
    fallback next_run_at (used if _finalise fails to persist) is
    drift-free for unanchored ``every`` jobs."""
    fired_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    tick_at = fired_at + timedelta(seconds=5)  # picked up 5s late
    monkeypatch.setattr(scheduler_core, "_utc_now", lambda: tick_at)

    repo = _RecordingRepo([_every_job("job-e", next_run_at=fired_at, every_seconds=120)])
    executor = _BlockingExecutor()
    scheduler = Scheduler(repo, executor)

    await scheduler._tick()
    await asyncio.wait_for(executor.started.wait(), timeout=1)

    # Bump = fired_at + every (00:02:00), NOT tick_at + every (00:02:05).
    expected = fired_at + timedelta(seconds=120)
    assert repo.updates[0] == ("job-e", {"next_run_at": expected, "user_id": None})

    executor.release.set()
    await asyncio.wait_for(executor.done.wait(), timeout=1)


@pytest.mark.asyncio
async def test_finalise_swallows_repo_error_without_propagating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repo write failure during _finalise must not propagate.

    _finalise is best-effort: it logs the failure and leaves next_run_at
    at its optimistic tentative value (set by _tick), which self-heals on
    the next slot or scheduler restart. Propagating would otherwise trip
    _run_job_safely's except branch and re-finalise the same run with an
    error status (double-counting the failure and leaving last_status stale).
    """
    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(scheduler_core, "_utc_now", lambda: now)

    class _ExplodingRepo(_RecordingRepo):
        async def update_scheduling_state(self, job_id: str, **kwargs: Any) -> dict[str, Any] | None:
            raise RuntimeError("db locked")

    repo = _ExplodingRepo([])
    scheduler = Scheduler(repo, _BlockingExecutor())
    job = _every_job("job-x", next_run_at=now, every_seconds=60)

    # Must not raise.
    await scheduler._finalise(job, ExecutionResult(status="ok"), now)

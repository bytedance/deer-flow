from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

from deerflow.scheduler.schedules import next_run_at


class ScheduledTaskService:
    def __init__(
        self,
        *,
        task_repo,
        task_run_repo,
        launch_run,
        poll_interval_seconds: int,
        lease_seconds: int,
        max_concurrent_runs: int,
    ) -> None:
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._launch_run = launch_run
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_runs = max_concurrent_runs
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run_once(self, *, now: datetime) -> None:
        claimed = await self._task_repo.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_runs,
        )
        for task in claimed:
            await self.dispatch_task(task, now=now, trigger="scheduled")

    async def dispatch_task(self, task: dict[str, Any], *, now: datetime, trigger: str) -> None:
        execution_thread_id = task.get("thread_id")
        if task.get("context_mode") == "fresh_thread_per_run" or not execution_thread_id:
            execution_thread_id = str(uuid.uuid4())
        task_run_id = f"task-run-{uuid.uuid4().hex}"
        await self._task_run_repo.create(
            run_record_id=task_run_id,
            task_id=task["id"],
            thread_id=execution_thread_id,
            scheduled_for=now,
            trigger=trigger,
            status="queued",
        )
        try:
            result = await self._launch_run(
                thread_id=execution_thread_id,
                assistant_id=task.get("assistant_id"),
                prompt=task["prompt"],
                owner_user_id=task.get("user_id"),
                metadata={
                    "scheduled_task_id": task["id"],
                    "scheduled_trigger": trigger,
                },
            )
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            if task["schedule_type"] == "once":
                task_status = "completed"
            elif trigger == "manual" and task.get("status") == "paused":
                task_status = "paused"
            else:
                task_status = "enabled"
            await self._task_run_repo.update_status(
                task_run_id,
                status="running",
                run_id=result["run_id"],
                started_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=result["run_id"],
                last_thread_id=result["thread_id"],
                last_error=None,
                increment_run_count=True,
            )
        except Exception as exc:
            if task["schedule_type"] == "once":
                task_status = "failed"
            elif trigger == "manual" and task.get("status") == "paused":
                task_status = "paused"
            else:
                task_status = "enabled"
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            await self._task_run_repo.update_status(
                task_run_id,
                status="failed",
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=None,
                last_thread_id=execution_thread_id,
                last_error=str(exc),
                increment_run_count=False,
            )

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self.run_once(now=datetime.now(UTC))
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

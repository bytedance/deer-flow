from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskReference, TaskSnapshot, TaskSubmitRequest
from deerflow.persistence.mcp_tasks import DuplicateMcpRemoteTaskError

logger = logging.getLogger(__name__)

_MAX_POLL_ERROR_CHARS = 4000


class McpTaskService:
    """Persist and poll long-running MCP tasks outside the Agent loop."""

    def __init__(
        self,
        *,
        repository,
        drivers: McpTaskDriverRegistry,
        poll_interval_seconds: int,
        lease_seconds: int,
        max_concurrent_polls: int,
    ) -> None:
        self._repository = repository
        self._drivers = drivers
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_polls = max_concurrent_polls
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def drivers(self) -> McpTaskDriverRegistry:
        return self._drivers

    async def submit(
        self,
        *,
        driver_name: str,
        request: TaskSubmitRequest,
        now: datetime | None = None,
    ) -> dict:
        """Submit through one driver and persist the remote handle before returning."""
        driver = self._drivers.get(driver_name)
        if driver is None:
            raise LookupError(f"No MCP task driver registered as {driver_name!r}")

        submitted_at = now or datetime.now(UTC)
        local_task_id = request.local_task_id or f"mcp-task-{uuid.uuid4().hex}"
        driver_request = replace(request, local_task_id=local_task_id)
        submission = await driver.submit(driver_request)
        snapshot = submission.snapshot
        next_poll_at = self._next_poll_at(snapshot, now=submitted_at)
        driver_data = {**request.driver_data, **submission.driver_data}
        task_reference = TaskReference(
            local_task_id=local_task_id,
            user_id=request.user_id,
            thread_id=request.thread_id,
            server_name=request.server_name,
            remote_task_id=submission.remote_task_id,
            driver_data=driver_data,
        )
        try:
            return await self._repository.create(
                task_id=local_task_id,
                user_id=request.user_id,
                thread_id=request.thread_id,
                run_id=request.run_id,
                tool_call_id=request.tool_call_id,
                server_name=request.server_name,
                driver_name=driver_name,
                remote_task_id=submission.remote_task_id,
                task_name=request.task_name,
                status=snapshot.status.value,
                result=snapshot.result,
                error=snapshot.error,
                input_required=snapshot.input_required,
                next_poll_at=next_poll_at,
                driver_data=driver_data,
            )
        except DuplicateMcpRemoteTaskError:
            # This handle already has a durable owner. Cancelling it as
            # compensation would terminate the pre-existing tracked task.
            raise
        except Exception:
            try:
                await driver.cancel(task_reference)
            except Exception:  # noqa: BLE001 - preserve the original persistence failure
                logger.exception(
                    "Failed to cancel untracked MCP task after persistence failure (task_id=%s, driver=%s, remote_task_id=%s)",
                    local_task_id,
                    driver_name,
                    submission.remote_task_id,
                )
            raise

    async def run_once(self, *, now: datetime) -> None:
        claimed = await self._repository.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_polls,
        )
        if not claimed:
            return
        results = await asyncio.gather(
            *(self._poll_one(task, now=now) for task in claimed),
            return_exceptions=True,
        )
        for record, result in zip(claimed, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "Unexpected MCP task poll failure (task_id=%s); the lease will expire for recovery",
                    record.get("id"),
                    exc_info=(type(result), result, result.__traceback__),
                )

    async def _poll_one(self, record: dict, *, now: datetime) -> None:
        driver_name = str(record.get("driver_name") or "")
        driver = self._drivers.get(driver_name)
        if driver is None:
            await self._release_after_error(
                record,
                now=now,
                error=f"No MCP task driver registered as {driver_name!r}",
            )
            return

        try:
            snapshot = await driver.get_status(TaskReference.from_record(record))
        except Exception as exc:  # noqa: BLE001 - driver boundary; retry on the next poll
            polled_at = datetime.now(UTC)
            logger.warning(
                "MCP task status poll failed (task_id=%s, driver=%s); retrying",
                record.get("id"),
                driver_name,
                exc_info=True,
            )
            await self._release_after_error(record, now=polled_at, error=str(exc) or type(exc).__name__)
            return

        polled_at = datetime.now(UTC)
        applied = await self._repository.apply_snapshot(
            record["id"],
            lease_owner=self._lease_owner,
            status=snapshot.status.value,
            result=snapshot.result,
            error=snapshot.error,
            input_required=snapshot.input_required,
            next_poll_at=self._next_poll_at(snapshot, now=polled_at),
            polled_at=polled_at,
        )
        if not applied:
            logger.info(
                "Discarded MCP task poll result after lease ownership changed or expired (task_id=%s)",
                record.get("id"),
            )

    def _next_poll_at(self, snapshot: TaskSnapshot, *, now: datetime) -> datetime | None:
        if not snapshot.is_pollable:
            return None
        interval = snapshot.poll_after_seconds or self._poll_interval_seconds
        return now + timedelta(seconds=interval)

    async def _release_after_error(self, record: dict, *, now: datetime, error: str) -> None:
        await self._repository.release_claim(
            record["id"],
            lease_owner=self._lease_owner,
            next_poll_at=now + timedelta(seconds=self._poll_interval_seconds),
            error=error[:_MAX_POLL_ERROR_CHARS],
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="deerflow-mcp-task-poller")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                # The first pass runs immediately. Expired leases therefore
                # recover at startup without a separate destructive sweep.
                await self.run_once(now=datetime.now(UTC))
            except Exception:
                logger.exception("MCP task poll failed; retrying next interval")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

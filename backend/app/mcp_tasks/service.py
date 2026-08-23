from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from app.mcp_tasks.errors import PermanentNotificationError
from deerflow.constants import (
    MCP_TASK_POLL_AFTER_MAX_SECONDS,
    MCP_TASK_REMOTE_ID_MAX_LENGTH,
    MCP_TASK_RESULT_ARTIFACT_MAX_BYTES,
)
from deerflow.mcp.tasks import (
    McpTaskDriverRegistry,
    McpTaskProtocolError,
    TaskReference,
    TaskSnapshot,
    TaskStatus,
    TaskSubmitRequest,
)
from deerflow.persistence.mcp_tasks import DuplicateMcpRemoteTaskError
from deerflow.runtime.runs.manager import ConflictError
from deerflow.runtime.runs.schemas import RunStatus

logger = logging.getLogger(__name__)

_MAX_PERSISTED_ERROR_CHARS = 4_000
_MAX_INPUT_REQUIRED_BYTES = 65_536
_MAX_NOTIFICATION_ATTEMPTS = 5


def _bound_error(error: str | None) -> str | None:
    if error is None:
        return None
    return error[:_MAX_PERSISTED_ERROR_CHARS]


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
        max_poll_backoff_seconds: int = 300,
        input_required_poll_interval_seconds: int = 60,
        tracking_degraded_after_errors: int = 3,
        max_result_bytes: int = 65_536,
        result_preview_max_chars: int = 2_000,
        launch_notification: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        get_run: Callable[..., Awaitable[Any | None]] | None = None,
    ) -> None:
        self._repository = repository
        self._drivers = drivers
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_polls = max_concurrent_polls
        self._max_poll_backoff_seconds = max_poll_backoff_seconds
        self._input_required_poll_interval_seconds = input_required_poll_interval_seconds
        self._tracking_degraded_after_errors = tracking_degraded_after_errors
        self._max_result_bytes = max_result_bytes
        self._result_preview_max_chars = result_preview_max_chars
        self._launch_notification = launch_notification
        self._get_run = get_run
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def drivers(self) -> McpTaskDriverRegistry:
        return self._drivers

    @property
    def tracking_degraded_after_errors(self) -> int:
        return self._tracking_degraded_after_errors

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
            if len(submission.remote_task_id) > MCP_TASK_REMOTE_ID_MAX_LENGTH:
                raise McpTaskProtocolError(f"MCP task remote_task_id must not exceed {MCP_TASK_REMOTE_ID_MAX_LENGTH} characters")
            snapshot = self._normalize_snapshot(submission.snapshot)
            next_poll_at = self._next_poll_at(snapshot, now=submitted_at)
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
                result_preview=snapshot.result_preview,
                result_truncated=snapshot.result_truncated,
                result_artifact=snapshot.result_artifact,
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
        await self._run_cancellations(now=now)

        claimed = await self._repository.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_polls,
        )
        if claimed:
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

        await self._run_notifications(now=datetime.now(UTC))

    async def list_tasks(
        self,
        *,
        thread_id: str,
        user_id: str,
        limit: int = 50,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        return await self._repository.list_by_thread(
            thread_id,
            user_id=user_id,
            limit=limit,
            active_only=active_only,
        )

    async def cancel_task(
        self,
        *,
        task_id: str,
        thread_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        return await self._repository.request_cancel(
            task_id,
            user_id=user_id,
            thread_id=thread_id,
            requested_at=now or datetime.now(UTC),
        )

    async def cancel_matching_task(
        self,
        *,
        thread_id: str,
        user_id: str,
        task: str | None = None,
    ) -> dict[str, Any]:
        active = await self.list_tasks(thread_id=thread_id, user_id=user_id, active_only=True)
        if task:
            normalized = task.casefold().strip()
            matches = [item for item in active if item["id"] == task or str(item.get("task_name") or "").casefold() == normalized]
        else:
            matches = active
        if not matches:
            raise LookupError("No active background task matches this request")
        if len(matches) > 1:
            names = ", ".join(str(item.get("task_name") or item["id"]) for item in matches[:5])
            raise ValueError(f"More than one active background task matches; specify one task name: {names}")
        result = await self.cancel_task(
            task_id=matches[0]["id"],
            thread_id=thread_id,
            user_id=user_id,
        )
        if result is None:
            raise LookupError("The selected background task no longer exists")
        return result

    async def _run_cancellations(self, *, now: datetime) -> None:
        claim = getattr(self._repository, "claim_cancel_requests", None)
        if claim is None:
            return
        records = await claim(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_polls,
        )
        if records:
            results = await asyncio.gather(
                *(self._cancel_one(record) for record in records),
                return_exceptions=True,
            )
            for record, result in zip(records, results, strict=True):
                if isinstance(result, BaseException):
                    logger.error(
                        "Unexpected MCP task cancellation failure (task_id=%s); the lease will expire for recovery",
                        record.get("id"),
                        exc_info=(type(result), result, result.__traceback__),
                    )

    async def _cancel_one(self, record: dict[str, Any]) -> None:
        driver_name = str(record.get("driver_name") or "")
        driver = self._drivers.get(driver_name)
        try:
            if driver is None:
                raise LookupError(f"No MCP task driver registered as {driver_name!r}")
            snapshot = self._normalize_snapshot(await driver.cancel(TaskReference.from_record(record)))
            if snapshot.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                raise McpTaskProtocolError("MCP task cancellation must return a terminal status")
            await self._repository.apply_cancel_snapshot(
                record["id"],
                lease_owner=self._lease_owner,
                status=snapshot.status.value,
                result=snapshot.result,
                result_preview=snapshot.result_preview,
                result_truncated=snapshot.result_truncated,
                result_artifact=snapshot.result_artifact,
                error=snapshot.error,
                input_required=snapshot.input_required,
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001 - remote cancellation is retryable
            attempts = max(0, int(record.get("cancel_attempt_count") or 1) - 1)
            retry_seconds = min(self._poll_interval_seconds * (2 ** min(attempts, 16)), self._max_poll_backoff_seconds)
            failed_at = datetime.now(UTC)
            await self._repository.release_cancel_claim(
                record["id"],
                lease_owner=self._lease_owner,
                next_cancel_at=failed_at + timedelta(seconds=retry_seconds),
                error=_bound_error(str(exc) or type(exc).__name__),
            )

    async def _run_notifications(self, *, now: datetime) -> None:
        if self._launch_notification is None or self._get_run is None:
            return
        records = await self._repository.claim_notification_work(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_polls,
            tracking_degraded_after_errors=self._tracking_degraded_after_errors,
        )
        if records:
            results = await asyncio.gather(
                *(self._notify_one(record, now=now) for record in records),
                return_exceptions=True,
            )
            for record, result in zip(records, results, strict=True):
                if not isinstance(result, BaseException):
                    continue
                error = _bound_error(str(result) or type(result).__name__) or type(result).__name__
                logger.error(
                    "Unexpected MCP task notification failure (task_id=%s)",
                    record.get("id"),
                    exc_info=(type(result), result, result.__traceback__),
                )
                try:
                    await self._repository.release_notification_lease(
                        record["id"],
                        lease_owner=self._lease_owner,
                        next_notification_at=now + timedelta(seconds=self._notification_retry_seconds(record)),
                        error=error,
                        count_failure=True,
                    )
                except Exception:  # noqa: BLE001 - retain the original task-scoped failure
                    logger.exception(
                        "Failed to release MCP task notification lease (task_id=%s)",
                        record.get("id"),
                    )

    async def _notify_one(self, record: dict[str, Any], *, now: datetime) -> None:
        task_id = record["id"]
        dispatch_version = int(record.get("dispatch_version") or 0)
        notification_attempts = max(0, int(record.get("notification_attempt_count") or 0))
        if notification_attempts >= _MAX_NOTIFICATION_ATTEMPTS:
            previous_error = record.get("notification_error") or "delivery failed"
            await self._repository.dead_letter_notification(
                task_id,
                lease_owner=self._lease_owner,
                dispatch_version=dispatch_version,
                error=_bound_error(f"Notification delivery stopped after {notification_attempts} failed attempts: {previous_error}"),
                count_failure=False,
                now=now,
            )
            return

        if record.get("notification_status") == "dispatched":
            run = await self._get_run(record.get("notification_run_id"), user_id=record["user_id"])
            status = getattr(run, "status", None)
            if run is None:
                run_id = record.get("notification_run_id")
                await self._repository.finish_notification_run(
                    task_id,
                    lease_owner=self._lease_owner,
                    dispatch_version=dispatch_version,
                    delivered=False,
                    next_notification_at=now + timedelta(seconds=self._notification_retry_seconds(record)),
                    error=_bound_error(f"Notification run {run_id!r} was not found"),
                    now=now,
                )
            elif status == RunStatus.success:
                await self._repository.finish_notification_run(
                    task_id,
                    lease_owner=self._lease_owner,
                    dispatch_version=dispatch_version,
                    delivered=True,
                    next_notification_at=None,
                    error=None,
                    now=now,
                )
            elif status in {RunStatus.error, RunStatus.timeout, RunStatus.interrupted}:
                await self._repository.finish_notification_run(
                    task_id,
                    lease_owner=self._lease_owner,
                    dispatch_version=dispatch_version,
                    delivered=False,
                    next_notification_at=now + timedelta(seconds=self._notification_retry_seconds(record)),
                    error=_bound_error(getattr(run, "error", None) or f"Notification run ended with {status}"),
                    now=now,
                )
            else:
                await self._repository.defer_dispatched_notification(
                    task_id,
                    lease_owner=self._lease_owner,
                    dispatch_version=dispatch_version,
                    next_notification_at=now + timedelta(seconds=self._poll_interval_seconds),
                    now=now,
                )
            return

        source_run = await self._get_run(record.get("run_id"), user_id=record["user_id"]) if record.get("run_id") else None
        try:
            result = await self._launch_notification(
                thread_id=record["thread_id"],
                assistant_id=getattr(source_run, "assistant_id", None),
                owner_user_id=record["user_id"],
                task_id=task_id,
                dispatch_version=dispatch_version,
                dispatch_attempt=int(record.get("dispatch_attempt") or 0),
                event=dict(record.get("dispatch_event") or {}),
            )
        except PermanentNotificationError as exc:
            await self._repository.dead_letter_notification(
                task_id,
                lease_owner=self._lease_owner,
                dispatch_version=dispatch_version,
                error=_bound_error(str(exc) or type(exc).__name__),
                count_failure=True,
                now=now,
            )
            return
        except ConflictError as exc:
            await self._repository.release_notification_claim(
                task_id,
                lease_owner=self._lease_owner,
                next_notification_at=now + timedelta(seconds=self._poll_interval_seconds),
                error=_bound_error(str(exc)),
                replace_with_latest=True,
            )
            return
        except Exception as exc:  # noqa: BLE001 - retry the same idempotency key
            await self._repository.release_notification_claim(
                task_id,
                lease_owner=self._lease_owner,
                next_notification_at=now + timedelta(seconds=self._notification_retry_seconds(record)),
                error=_bound_error(str(exc) or type(exc).__name__),
                replace_with_latest=True,
                count_failure=True,
            )
            return
        await self._repository.mark_notification_dispatched(
            task_id,
            lease_owner=self._lease_owner,
            dispatch_version=dispatch_version,
            run_id=result["run_id"],
            now=now,
        )

    def _notification_retry_seconds(self, record: dict[str, Any]) -> int:
        failures = max(0, int(record.get("notification_attempt_count") or 0))
        return min(
            self._poll_interval_seconds * (2 ** min(failures, 16)),
            self._max_poll_backoff_seconds,
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
            snapshot = self._normalize_snapshot(await driver.get_status(TaskReference.from_record(record)))
        except McpTaskProtocolError as exc:
            logger.error(
                "MCP task status contract failed permanently (task_id=%s, driver=%s): %s",
                record.get("id"),
                driver_name,
                exc,
            )
            await self._apply_snapshot(
                record,
                TaskSnapshot(status=TaskStatus.FAILED, error=_bound_error(str(exc))),
                polled_at=datetime.now(UTC),
            )
            return
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
        await self._apply_snapshot(record, snapshot, polled_at=polled_at)

    async def _apply_snapshot(
        self,
        record: dict,
        snapshot: TaskSnapshot,
        *,
        polled_at: datetime,
    ) -> None:
        applied = await self._repository.apply_snapshot(
            record["id"],
            lease_owner=self._lease_owner,
            status=snapshot.status.value,
            result=snapshot.result,
            result_preview=snapshot.result_preview,
            result_truncated=snapshot.result_truncated,
            result_artifact=snapshot.result_artifact,
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
        if snapshot.status == TaskStatus.INPUT_REQUIRED:
            interval = max(interval, self._input_required_poll_interval_seconds)
        interval = min(interval, MCP_TASK_POLL_AFTER_MAX_SECONDS)
        return now + timedelta(seconds=interval)

    async def _release_after_error(self, record: dict, *, now: datetime, error: str) -> None:
        consecutive_errors = max(0, int(record.get("consecutive_poll_error_count") or 0))
        retry_seconds = min(
            self._poll_interval_seconds * (2 ** min(consecutive_errors, 16)),
            self._max_poll_backoff_seconds,
        )
        bounded_error = _bound_error(error)
        assert bounded_error is not None
        await self._repository.release_claim(
            record["id"],
            lease_owner=self._lease_owner,
            next_poll_at=now + timedelta(seconds=retry_seconds),
            error=bounded_error,
            tracking_degraded_after_errors=self._tracking_degraded_after_errors,
        )

    def _normalize_snapshot(self, snapshot: TaskSnapshot) -> TaskSnapshot:
        """Bound remote payloads without ever storing truncated JSON."""
        snapshot = replace(snapshot, error=_bound_error(snapshot.error))
        if snapshot.result_artifact is not None:
            encoded_artifact = self._encode_json_payload(
                snapshot.result_artifact,
                field_name="result_artifact",
            )
            if len(encoded_artifact) > MCP_TASK_RESULT_ARTIFACT_MAX_BYTES:
                raise McpTaskProtocolError(f"MCP task result_artifact payload exceeds the {MCP_TASK_RESULT_ARTIFACT_MAX_BYTES}-byte limit")
        if snapshot.input_required is not None:
            encoded_input = self._encode_json_payload(
                snapshot.input_required,
                field_name="input_required",
            )
            if len(encoded_input) > _MAX_INPUT_REQUIRED_BYTES:
                raise McpTaskProtocolError(f"MCP task input_required payload exceeds the {_MAX_INPUT_REQUIRED_BYTES}-byte limit")
        if snapshot.result is None:
            return snapshot
        encoded = self._encode_json_payload(snapshot.result, field_name="result")
        if len(encoded) <= self._max_result_bytes:
            return snapshot

        if isinstance(snapshot.result, str):
            preview_source = snapshot.result
        else:
            preview_source = encoded.decode("utf-8", errors="replace")
        return replace(
            snapshot,
            result=None,
            result_preview=preview_source[: self._result_preview_max_chars],
            result_truncated=True,
        )

    @staticmethod
    def _encode_json_payload(value, *, field_name: str) -> bytes:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise McpTaskProtocolError(f"MCP task {field_name} is not valid JSON: {exc}") from exc

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

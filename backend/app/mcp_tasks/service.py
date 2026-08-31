from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
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
from deerflow.runtime.cancellation import wait_for_task_until
from deerflow.runtime.runs.manager import ConflictError
from deerflow.runtime.runs.schemas import RunStatus

logger = logging.getLogger(__name__)

_MAX_PERSISTED_ERROR_CHARS = 4_000
_MAX_INPUT_REQUIRED_BYTES = 65_536
_MAX_NOTIFICATION_ATTEMPTS = 5
_CANCELLATION_DRAIN_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class _BatchRecordState:
    record: dict[str, Any]
    ordinary_release_task: asyncio.Future[Any] | None = None
    ordinary_release_terminal: bool = False
    cancellation_release_task: asyncio.Future[Any] | None = None
    cancellation_release_terminal: bool = False


@dataclass(slots=True)
class _BatchState:
    cancellation_requested: bool = False


@dataclass(slots=True)
class _ClaimOwner:
    claim_task: asyncio.Future[list[dict[str, Any]]]
    handoff_task: asyncio.Task[None] | None = None


_current_batch_record: ContextVar[_BatchRecordState | None] = ContextVar(
    "mcp_task_current_batch_record",
    default=None,
)


def _bound_error(error: str | None) -> str | None:
    if error is None:
        return None
    return error[:_MAX_PERSISTED_ERROR_CHARS]


def _consume_task_error(task: asyncio.Future[Any]) -> BaseException | None:
    try:
        return task.exception()
    except asyncio.CancelledError as exc:
        return exc


def _task_has_cancelled_terminal_state(task: asyncio.Future[Any]) -> bool:
    if not task.done():
        return False
    if task.cancelled():
        return True
    return isinstance(_consume_task_error(task), asyncio.CancelledError)


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
        self._stopping_task: asyncio.Task[None] | None = None
        self._stop_deadline: float | None = None
        self._stop_timeout_logged = False
        self._compensation_tasks: set[asyncio.Future[Any]] = set()
        self._claim_owners: dict[str, _ClaimOwner] = {}
        self._stop = asyncio.Event()

    @property
    def drivers(self) -> McpTaskDriverRegistry:
        return self._drivers

    @property
    def tracking_degraded_after_errors(self) -> int:
        return self._tracking_degraded_after_errors

    def _observe_batch_release_task(
        self,
        state: _BatchRecordState,
        task: asyncio.Future[Any],
        *,
        ordinary: bool,
        action: str,
    ) -> None:
        terminal_field = "ordinary_release_terminal" if ordinary else "cancellation_release_terminal"
        if getattr(state, terminal_field) or not task.done():
            return
        setattr(state, terminal_field, True)
        error = _consume_task_error(task)
        if error is None:
            return
        self._log_batch_release_error(
            error,
            action=action,
            task_id=state.record.get("id"),
        )

    @staticmethod
    def _log_batch_release_error(error: BaseException, *, action: str, task_id: Any) -> None:
        logger.error(
            "MCP task batch release failed (%s, task_id=%s): %s",
            action,
            task_id,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )

    @staticmethod
    def _log_claim_error(error: BaseException, *, action: str) -> None:
        logger.error(
            "MCP task claim operation failed (%s, task_id=batch): %s",
            action,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )

    def _track_batch_release_task(
        self,
        state: _BatchRecordState,
        task: asyncio.Future[Any],
        *,
        ordinary: bool,
        action: str,
    ) -> None:
        def finalize(completed: asyncio.Future[Any]) -> None:
            self._observe_batch_release_task(
                state,
                completed,
                ordinary=ordinary,
                action=action,
            )

        task.add_done_callback(finalize)

    def _retain_batch_release_task(self, task: asyncio.Future[Any]) -> None:
        """Transfer a timed-out ordinary release to service ownership."""
        if task in self._compensation_tasks:
            return
        self._compensation_tasks.add(task)
        task.add_done_callback(self._compensation_tasks.discard)

    async def _release_ordinary_batch_record(
        self,
        record: dict[str, Any],
        *,
        release: Callable[[], Awaitable[Any]],
        action: str,
    ) -> None:
        state = _current_batch_record.get()
        if state is None:
            release_task = asyncio.ensure_future(release())
            try:
                await asyncio.wait_for(
                    asyncio.shield(release_task),
                    timeout=_CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                if not release_task.done():
                    release_task.cancel()
                raise
            except TimeoutError:
                self._track_compensation_task(
                    release_task,
                    action=action,
                    task_id=str(record.get("id") or "unknown"),
                )
                logger.warning(
                    "Timed out after %.1f seconds waiting for MCP task release; it continues in the background (%s, task_id=%s)",
                    _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                    action,
                    record.get("id"),
                )
            return

        if state.cancellation_release_task is not None:
            self._observe_batch_release_task(
                state,
                state.cancellation_release_task,
                ordinary=False,
                action="cancellation release",
            )
            return

        task = state.ordinary_release_task
        if task is None:
            task = asyncio.create_task(
                release(),
                name=f"mcp-{action.replace(' ', '-')}-ordinary-release-{record.get('id', 'unknown')}",
            )
            state.ordinary_release_task = task
            self._track_batch_release_task(
                state,
                task,
                ordinary=True,
                action=action,
            )
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=_CANCELLATION_DRAIN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            # The release is still in flight past the drain deadline on the
            # uncancelled path; it stays tracked by the batch state and settles
            # in the background instead of blocking the poller.
            self._retain_batch_release_task(task)
            self._observe_batch_release_task(state, task, ordinary=True, action=action)
            logger.warning(
                "Timed out after %.1f seconds waiting for MCP task release; it continues in the background (%s, task_id=%s)",
                _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                action,
                record.get("id"),
            )
            return
        except asyncio.CancelledError:
            self._observe_batch_release_task(state, task, ordinary=True, action=action)
            if state.ordinary_release_terminal and not asyncio.current_task().cancelling():
                # The release cancelled itself and the caller is not cancelling:
                # consume it once and return without re-raising.
                return
            raise
        except Exception:
            self._observe_batch_release_task(state, task, ordinary=True, action=action)
            raise
        else:
            self._observe_batch_release_task(state, task, ordinary=True, action=action)

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
        except asyncio.CancelledError:
            # Cancellation can race with a successful database commit. If it
            # did, the durable row will converge to cancelled on its next poll;
            # compensating is safer than leaving a live remote task untracked.
            await self._cancel_untracked_task(
                driver=driver,
                task_reference=task_reference,
                driver_name=driver_name,
                reason="caller cancellation during local persistence",
            )
            raise
        except Exception:
            await self._cancel_untracked_task(
                driver=driver,
                task_reference=task_reference,
                driver_name=driver_name,
                reason="local submission finalization failure",
            )
            raise

    async def _cancel_untracked_task(
        self,
        *,
        driver,
        task_reference: TaskReference,
        driver_name: str,
        reason: str,
    ) -> None:
        compensation = asyncio.create_task(
            driver.cancel(task_reference),
            name=f"mcp-submit-compensation-{task_reference.local_task_id}",
        )
        self._compensation_tasks.add(compensation)

        def finalize(task: asyncio.Future[Any]) -> None:
            self._compensation_tasks.discard(task)
            error = _consume_task_error(task)
            if error is None:
                return
            logger.error(
                "Failed to cancel untracked MCP task after %s (task_id=%s, driver=%s, remote_task_id=%s)",
                reason,
                task_reference.local_task_id,
                driver_name,
                task_reference.remote_task_id,
                exc_info=(type(error), error, error.__traceback__),
            )

        compensation.add_done_callback(finalize)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS
        if not await wait_for_task_until(compensation, deadline=deadline):
            logger.warning(
                "Timed out after %.1f seconds waiting for untracked MCP task compensation after %s; cancellation continues in the background (task_id=%s, driver=%s, remote_task_id=%s)",
                _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                reason,
                task_reference.local_task_id,
                driver_name,
                task_reference.remote_task_id,
            )

    def _track_compensation_task(self, task: asyncio.Future[Any], *, action: str, task_id: str) -> None:
        if task in self._compensation_tasks:
            return
        self._compensation_tasks.add(task)

        def finalize(completed: asyncio.Future[Any]) -> None:
            self._compensation_tasks.discard(completed)
            error = _consume_task_error(completed)
            if error is None:
                return
            logger.error(
                "MCP task cancellation operation failed (%s, task_id=%s): %s",
                action,
                task_id,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

        task.add_done_callback(finalize)

    async def _drain_cancellation_task(
        self,
        task: asyncio.Future[Any],
        *,
        action: str,
        task_id: str,
        deadline: float,
    ) -> tuple[bool, Any]:
        if not await wait_for_task_until(task, deadline=deadline):
            self._track_compensation_task(task, action=action, task_id=task_id)
            logger.warning(
                "Timed out after %.1f seconds waiting for MCP task cancellation operation; it continues in the background (%s, task_id=%s)",
                _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                action,
                task_id,
            )
            return False, None

        error = _consume_task_error(task)
        if error is not None:
            logger.error(
                "MCP task cancellation operation failed (%s, task_id=%s): %s",
                action,
                task_id,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
            return False, None
        return True, task.result()

    async def _drain_cancellation_compensation(
        self,
        compensation: Awaitable[Any],
        *,
        action: str,
        task_id: str,
        settle: bool = False,
    ) -> tuple[bool, Any]:
        task = asyncio.ensure_future(compensation)
        if settle:
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                self._track_compensation_task(task, action=action, task_id=task_id)
                raise
            error = _consume_task_error(task)
            if error is not None:
                logger.error(
                    "MCP task cancellation operation failed (%s, task_id=%s): %s",
                    action,
                    task_id,
                    error,
                    exc_info=(type(error), error, error.__traceback__),
                )
                return False, None
            return True, task.result()
        deadline = asyncio.get_running_loop().time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS
        return await self._drain_cancellation_task(
            task,
            action=action,
            task_id=task_id,
            deadline=deadline,
        )

    async def _release_owned_batch_record(
        self,
        state: _BatchRecordState,
        *,
        release: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        ordinary_task = state.ordinary_release_task
        if ordinary_task is not None:
            self._observe_batch_release_task(
                state,
                ordinary_task,
                ordinary=True,
                action="ordinary retry release",
            )
            return

        task = state.cancellation_release_task
        if task is None:
            task = asyncio.create_task(
                release(state.record),
                name=f"mcp-cancellation-release-{state.record.get('id', 'unknown')}",
            )
            state.cancellation_release_task = task
            self._track_batch_release_task(
                state,
                task,
                ordinary=False,
                action="cancellation release",
            )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            self._observe_batch_release_task(
                state,
                task,
                ordinary=False,
                action="cancellation release",
            )
        except Exception:
            self._observe_batch_release_task(
                state,
                task,
                ordinary=False,
                action="cancellation release",
            )
        else:
            self._observe_batch_release_task(
                state,
                task,
                ordinary=False,
                action="cancellation release",
            )

    async def _finish_cancelled_batch(
        self,
        supervisor: asyncio.Task[list[Any]],
        children: list[asyncio.Task[Any]],
        states: list[_BatchRecordState],
        *,
        release: Callable[[dict[str, Any]], Awaitable[None]],
        action: str,
    ) -> None:
        # The handoff owns both the supervisor and every release task. Keeping
        # all of them in this frame lets a timed-out handoff finish safely in
        # the background without starting a second release.
        async def release_uncompleted(state: _BatchRecordState) -> None:
            if state.ordinary_release_task is not None:
                try:
                    await state.ordinary_release_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                self._observe_batch_release_task(
                    state,
                    state.ordinary_release_task,
                    ordinary=True,
                    action="ordinary retry release",
                )
                return
            await self._release_owned_batch_record(state, release=release)

        release_tasks = [
            asyncio.create_task(
                release_uncompleted(state),
                name=f"mcp-{action.replace(' ', '-')}-release-{index}-{state.record.get('id', 'unknown')}",
            )
            for index, state in enumerate(states)
        ]
        results = await asyncio.gather(supervisor, *release_tasks, return_exceptions=True)
        supervisor_result = results[0]
        if isinstance(supervisor_result, BaseException):
            logger.error(
                "MCP task batch supervisor failed during cancellation handoff (action=%s): %s",
                action,
                supervisor_result,
                exc_info=(type(supervisor_result), supervisor_result, supervisor_result.__traceback__),
            )
        for state, child in zip(states, children, strict=True):
            if child.done():
                error = _consume_task_error(child)
                if error is None or isinstance(error, asyncio.CancelledError):
                    continue
                failure_action = "cancellation" if action == "cancel" else action
                lease_suffix = "; the lease will expire for recovery" if action in {"poll", "cancel"} else ""
                logger.error(
                    "Unexpected MCP task %s failure (task_id=%s)%s",
                    failure_action,
                    state.record.get("id"),
                    lease_suffix,
                    exc_info=(type(error), error, error.__traceback__),
                )

    async def _run_claimed_batch(
        self,
        records: list[dict[str, Any]],
        *,
        operation: Callable[[dict[str, Any]], Awaitable[Any]],
        release: Callable[[dict[str, Any]], Awaitable[None]],
        action: str,
    ) -> tuple[list[_BatchRecordState], list[Any]]:
        states = [_BatchRecordState(record) for record in records]
        batch_state = _BatchState()
        parent_task = asyncio.current_task()

        async def run_one(state: _BatchRecordState) -> Any:
            context_token = _current_batch_record.set(state)
            try:
                if parent_task is not None and parent_task.cancelling():
                    batch_state.cancellation_requested = True
                if batch_state.cancellation_requested:
                    return None
                return await operation(state.record)
            except asyncio.CancelledError:
                await self._release_owned_batch_record(state, release=release)
                raise
            finally:
                _current_batch_record.reset(context_token)
                if batch_state.cancellation_requested:
                    await self._release_owned_batch_record(state, release=release)

        task_prefix = action.replace(" ", "-")
        tasks = [
            asyncio.create_task(
                run_one(state),
                name=f"mcp-{task_prefix}-{index}-{state.record.get('id', 'unknown')}",
            )
            for index, state in enumerate(states)
        ]

        async def supervise() -> list[Any]:
            return await asyncio.gather(*tasks, return_exceptions=True)

        supervisor = asyncio.create_task(
            supervise(),
            name=f"mcp-{task_prefix}-supervisor",
        )
        try:
            results = await asyncio.shield(supervisor)
        except asyncio.CancelledError as original_cancel:
            batch_state.cancellation_requested = True
            for task in tasks:
                task.cancel()
            handoff = asyncio.create_task(
                self._finish_cancelled_batch(
                    supervisor,
                    tasks,
                    states,
                    release=release,
                    action=action,
                ),
                name=f"mcp-{task_prefix}-cancellation-handoff",
            )
            await self._drain_cancellation_task(
                handoff,
                action=f"finish {action} batch handoff",
                task_id="batch",
                deadline=asyncio.get_running_loop().time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
            )
            # A task that was cancelled before entering this handler stores a
            # special cancelled state; raising that same exception object can
            # make asyncio discard its message when the task is awaited.
            # Recreate it with the first cancellation's args instead.
            raise asyncio.CancelledError(*original_cancel.args)

        return states, results

    async def run_once(self, *, now: datetime) -> None:
        await self._run_cancellations(now=now)

        claimed = await self._claim_with_cancellation_release(
            lambda: self._repository.claim_due_tasks(
                now=now,
                lease_owner=self._lease_owner,
                lease_seconds=self._lease_seconds,
                limit=self._max_concurrent_polls,
            ),
            phase="poll",
            action="poll claim",
            release=self._release_poll_after_cancellation,
        )
        if claimed:
            states, results = await self._run_claimed_batch(
                claimed,
                operation=lambda record: self._poll_one_claimed(record, now=now),
                release=self._release_poll_after_cancellation,
                action="poll",
            )
            for state, result in zip(states, results, strict=True):
                if isinstance(result, BaseException):
                    logger.error(
                        "Unexpected MCP task poll failure (task_id=%s); the lease will expire for recovery",
                        state.record.get("id"),
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
        records = await self._claim_with_cancellation_release(
            lambda: claim(
                now=now,
                lease_owner=self._lease_owner,
                lease_seconds=self._lease_seconds,
                limit=self._max_concurrent_polls,
            ),
            phase="cancel",
            action="cancel claim",
            release=self._release_cancel_after_cancellation,
        )
        if records:
            states, results = await self._run_claimed_batch(
                records,
                operation=self._cancel_one_claimed,
                release=self._release_cancel_after_cancellation,
                action="cancel",
            )
            for state, result in zip(states, results, strict=True):
                if isinstance(result, BaseException):
                    logger.error(
                        "Unexpected MCP task cancellation failure (task_id=%s); the lease will expire for recovery",
                        state.record.get("id"),
                        exc_info=(type(result), result, result.__traceback__),
                    )

    async def _cancel_one(self, record: dict[str, Any]) -> None:
        try:
            await self._cancel_one_claimed(record)
        except asyncio.CancelledError:
            await self._release_cancel_after_cancellation(record)
            raise

    async def _cancel_one_claimed(self, record: dict[str, Any]) -> None:
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
                lease_token=record["lease_token"],
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
            retry_error = _bound_error(str(exc) or type(exc).__name__)
            await self._release_ordinary_batch_record(
                record,
                release=lambda: self._repository.release_cancel_claim(
                    record["id"],
                    lease_owner=self._lease_owner,
                    lease_token=record["lease_token"],
                    next_cancel_at=failed_at + timedelta(seconds=retry_seconds),
                    error=retry_error,
                ),
                action="release cancel retry",
            )

    async def _run_notifications(self, *, now: datetime) -> None:
        if self._launch_notification is None or self._get_run is None:
            return
        records = await self._claim_with_cancellation_release(
            lambda: self._repository.claim_notification_work(
                now=now,
                lease_owner=self._lease_owner,
                lease_seconds=self._lease_seconds,
                limit=self._max_concurrent_polls,
                tracking_degraded_after_errors=self._tracking_degraded_after_errors,
            ),
            phase="notification",
            action="notification claim",
            release=self._release_notification_after_cancellation,
        )
        if records:
            states, results = await self._run_claimed_batch(
                records,
                operation=lambda record: self._notify_one_claimed(record, now=now),
                release=self._release_notification_after_cancellation,
                action="notification",
            )
            for state, result in zip(states, results, strict=True):
                if not isinstance(result, BaseException) or isinstance(result, asyncio.CancelledError):
                    continue
                record = state.record
                error = _bound_error(str(result) or type(result).__name__) or type(result).__name__
                logger.error(
                    "Unexpected MCP task notification failure (task_id=%s)",
                    record.get("id"),
                    exc_info=(type(result), result, result.__traceback__),
                )
                await self._release_notification_failure(record, now=now, error=error)

    async def _notify_one(self, record: dict[str, Any], *, now: datetime) -> None:
        try:
            await self._notify_one_claimed(record, now=now)
        except asyncio.CancelledError:
            await self._release_notification_after_cancellation(record)
            raise

    async def _notify_one_claimed(self, record: dict[str, Any], *, now: datetime) -> None:
        task_id = record["id"]
        dispatch_version = int(record.get("dispatch_version") or 0)
        notification_attempts = max(0, int(record.get("notification_attempt_count") or 0))
        if notification_attempts >= _MAX_NOTIFICATION_ATTEMPTS:
            previous_error = record.get("notification_error") or "delivery failed"
            await self._repository.dead_letter_notification(
                task_id,
                lease_owner=self._lease_owner,
                notification_lease_token=record["notification_lease_token"],
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
                    notification_lease_token=record["notification_lease_token"],
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
                    notification_lease_token=record["notification_lease_token"],
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
                    notification_lease_token=record["notification_lease_token"],
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
                    notification_lease_token=record["notification_lease_token"],
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
                notification_lease_token=record["notification_lease_token"],
                dispatch_version=dispatch_version,
                error=_bound_error(str(exc) or type(exc).__name__),
                count_failure=True,
                now=now,
            )
            return
        except ConflictError as exc:
            retry_error = _bound_error(str(exc))
            await self._release_ordinary_batch_record(
                record,
                release=lambda: self._repository.release_notification_claim(
                    task_id,
                    lease_owner=self._lease_owner,
                    notification_lease_token=record["notification_lease_token"],
                    next_notification_at=now + timedelta(seconds=self._poll_interval_seconds),
                    error=retry_error,
                    replace_with_latest=True,
                ),
                action="release notification conflict retry",
            )
            return
        except Exception as exc:  # noqa: BLE001 - retry the same idempotency key
            retry_error = _bound_error(str(exc) or type(exc).__name__)
            await self._release_ordinary_batch_record(
                record,
                release=lambda: self._repository.release_notification_claim(
                    task_id,
                    lease_owner=self._lease_owner,
                    notification_lease_token=record["notification_lease_token"],
                    next_notification_at=now + timedelta(seconds=self._notification_retry_seconds(record)),
                    error=retry_error,
                    replace_with_latest=True,
                    count_failure=True,
                ),
                action="release notification retry",
            )
            return
        await self._repository.mark_notification_dispatched(
            task_id,
            lease_owner=self._lease_owner,
            notification_lease_token=record["notification_lease_token"],
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
        try:
            await self._poll_one_claimed(record, now=now)
        except asyncio.CancelledError:
            await self._release_poll_after_cancellation(record)
            raise

    async def _claim_with_cancellation_release(
        self,
        claim: Callable[[], Awaitable[list[dict[str, Any]]]],
        *,
        phase: str,
        action: str,
        release: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> list[dict[str, Any]]:
        if phase in self._claim_owners:
            logger.warning(
                "Skipping MCP %s claim because the previous claim/handoff is still unresolved",
                phase,
            )
            return []

        claim_task = asyncio.ensure_future(claim())
        owner = _ClaimOwner(claim_task=claim_task)
        self._claim_owners[phase] = owner
        try:
            records = await asyncio.wait_for(
                asyncio.shield(claim_task),
                timeout=_CANCELLATION_DRAIN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            self._start_claim_owner_handoff(
                owner,
                phase=phase,
                action=action,
                release=release,
            )
            logger.warning(
                "Timed out after %.1f seconds waiting for MCP task claim; it continues in the background (%s, task_id=batch)",
                _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                action,
            )
            return []
        except asyncio.CancelledError:
            caller_cancelling = asyncio.current_task().cancelling()
            claim_cancelled = _task_has_cancelled_terminal_state(claim_task)
            if claim_cancelled and not caller_cancelling:
                error = _consume_task_error(claim_task)
                if error is not None:
                    self._log_claim_error(error, action=action)
                if self._claim_owners.get(phase) is owner:
                    self._claim_owners.pop(phase, None)
                return []
            handoff = self._start_claim_owner_handoff(
                owner,
                phase=phase,
                action=action,
                release=release,
            )
            loop = asyncio.get_running_loop()
            await self._drain_cancellation_task(
                handoff,
                action=f"finish {action} handoff",
                task_id="batch",
                deadline=loop.time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
            )
            raise
        except Exception:
            if self._claim_owners.get(phase) is owner:
                self._claim_owners.pop(phase, None)
            raise
        else:
            if self._claim_owners.get(phase) is owner:
                self._claim_owners.pop(phase, None)
            return records

    def _start_claim_owner_handoff(
        self,
        owner: _ClaimOwner,
        *,
        phase: str,
        action: str,
        release: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> asyncio.Task[None]:
        if owner.handoff_task is None:
            owner.handoff_task = asyncio.create_task(
                self._finish_cancelled_claim_handoff(
                    owner.claim_task,
                    owner=owner,
                    phase=phase,
                    action=action,
                    release=release,
                ),
                name=f"mcp-{action.replace(' ', '-')}-handoff",
            )
            self._track_compensation_task(owner.handoff_task, action=f"finish {action} handoff", task_id="batch")
        return owner.handoff_task

    async def _finish_cancelled_claim_handoff(
        self,
        claim_task: asyncio.Future[list[dict[str, Any]]],
        *,
        owner: _ClaimOwner,
        phase: str,
        action: str,
        release: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        try:
            try:
                records = await claim_task
            except asyncio.CancelledError:
                logger.error("MCP task claim operation was cancelled (%s, task_id=batch)", action)
                return
            except Exception as exc:  # noqa: BLE001 - claim recovery is best-effort
                logger.error(
                    "MCP task claim operation failed (%s, task_id=batch): %s",
                    action,
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                return
            if records:
                await self._release_claimed_records(records, release=release, settle=True)
        finally:
            if self._claim_owners.get(phase) is owner:
                self._claim_owners.pop(phase, None)

    async def _release_claimed_records(
        self,
        records: list[dict[str, Any]],
        *,
        release: Callable[..., Awaitable[None]],
        settle: bool = False,
    ) -> None:
        async def release_one(record: dict[str, Any]) -> None:
            try:
                if settle:
                    await release(record, settle=True)
                else:
                    await release(record)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - release every record in the claimed batch
                logger.exception(
                    "Unexpected MCP task claim release failure (task_id=%s)",
                    record.get("id"),
                )

        release_tasks = [
            asyncio.create_task(
                release_one(record),
                name=f"mcp-release-claimed-{record.get('id', 'unknown')}",
            )
            for record in records
        ]
        completion = asyncio.gather(*release_tasks, return_exceptions=True)
        if settle:
            await completion
        else:
            deadline = asyncio.get_running_loop().time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS
            if not await wait_for_task_until(completion, deadline=deadline):
                self._track_compensation_task(
                    completion,
                    action="release claimed MCP task batch",
                    task_id="batch",
                )
                logger.warning(
                    "Timed out after %.1f seconds waiting for MCP task claim releases; they continue in the background",
                    _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                )
                return
        results = completion.result()
        for record, result in zip(records, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                logger.error(
                    "MCP task claim release was cancelled (task_id=%s)",
                    record.get("id"),
                )

    async def _release_notification_failure(
        self,
        record: dict[str, Any],
        *,
        now: datetime,
        error: str,
    ) -> None:
        task = asyncio.create_task(
            self._repository.release_notification_lease(
                record["id"],
                lease_owner=self._lease_owner,
                notification_lease_token=record["notification_lease_token"],
                next_notification_at=now + timedelta(seconds=self._notification_retry_seconds(record)),
                error=error,
                count_failure=True,
            ),
            name=f"mcp-release-notification-failure-{record.get('id', 'unknown')}",
        )
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=_CANCELLATION_DRAIN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            self._track_compensation_task(
                task,
                action="release notification failure",
                task_id=record["id"],
            )
            logger.warning(
                "Timed out after %.1f seconds waiting for MCP task notification release; it continues in the background (task_id=%s)",
                _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
                record["id"],
            )
            return
        except asyncio.CancelledError:
            caller_cancelling = asyncio.current_task().cancelling()
            release_cancelled = _task_has_cancelled_terminal_state(task)
            if release_cancelled and not caller_cancelling:
                error = _consume_task_error(task)
                if error is not None:
                    self._log_batch_release_error(
                        error,
                        action="release notification failure",
                        task_id=record["id"],
                    )
                return
            await self._drain_cancellation_task(
                task,
                action="release notification failure",
                task_id=record["id"],
                deadline=asyncio.get_running_loop().time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
            )
            raise
        except Exception:  # noqa: BLE001 - retain the task-scoped failure
            logger.exception(
                "Failed to release MCP task notification lease (task_id=%s)",
                record.get("id"),
            )

    async def _release_cancel_after_cancellation(self, record: dict[str, Any], *, settle: bool = False) -> None:
        await self._drain_cancellation_compensation(
            self._repository.release_cancel_claim(
                record["id"],
                lease_owner=self._lease_owner,
                lease_token=record["lease_token"],
                next_cancel_at=datetime.now(UTC),
                error=record.get("last_cancel_error"),
            ),
            action="release cancel claim",
            task_id=record["id"],
            settle=settle,
        )

    async def _release_notification_after_cancellation(
        self,
        record: dict[str, Any],
        *,
        settle: bool = False,
    ) -> None:
        task_id = record["id"]
        if record.get("notification_status") == "dispatched":
            compensation = self._repository.release_notification_lease(
                task_id,
                lease_owner=self._lease_owner,
                notification_lease_token=record["notification_lease_token"],
                next_notification_at=datetime.now(UTC),
                error=record.get("notification_error"),
                count_failure=False,
            )
            action = "release dispatched notification lease"
        else:
            compensation = self._repository.release_notification_claim(
                task_id,
                lease_owner=self._lease_owner,
                notification_lease_token=record["notification_lease_token"],
                next_notification_at=datetime.now(UTC),
                error=record.get("notification_error"),
                replace_with_latest=False,
            )
            action = "release notification claim"
        await self._drain_cancellation_compensation(
            compensation,
            action=action,
            task_id=task_id,
            settle=settle,
        )

    async def _release_poll_after_cancellation(self, record: dict[str, Any], *, settle: bool = False) -> None:
        await self._drain_cancellation_compensation(
            self._repository.release_poll_claim_after_cancellation(
                record["id"],
                lease_owner=self._lease_owner,
                lease_token=record["lease_token"],
            ),
            action="release poll claim",
            task_id=record["id"],
            settle=settle,
        )

    async def _poll_one_claimed(self, record: dict, *, now: datetime) -> None:
        driver_name = str(record.get("driver_name") or "")
        driver = self._drivers.get(driver_name)
        if driver is None:
            await self._release_ordinary_batch_record(
                record,
                release=lambda: self._release_after_error(
                    record,
                    now=now,
                    error=f"No MCP task driver registered as {driver_name!r}",
                ),
                action="release poll retry",
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
            retry_error = str(exc) or type(exc).__name__
            await self._release_ordinary_batch_record(
                record,
                release=lambda: self._release_after_error(
                    record,
                    now=polled_at,
                    error=retry_error,
                ),
                action="release poll retry",
            )
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
            lease_token=record["lease_token"],
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
            lease_token=record["lease_token"],
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
        self._stopping_task = None
        self._stop_deadline = None
        self._stop_timeout_logged = False
        task = asyncio.create_task(self._run_loop(), name="deerflow-mcp-task-poller")
        self._task = task
        task.add_done_callback(self._poller_done)

    def _poller_done(self, task: asyncio.Task[None]) -> None:
        if self._task is task:
            self._task = None
            self._stopping_task = None
            self._stop_deadline = None
            self._stop_timeout_logged = False
        error = _consume_task_error(task)
        if error is None or isinstance(error, asyncio.CancelledError):
            return
        logger.error(
            "MCP task poller failed: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
        )

    def _log_stop_timeout(self, task: asyncio.Task[None]) -> None:
        if self._stopping_task is not task or self._stop_timeout_logged:
            return
        self._stop_timeout_logged = True
        logger.warning(
            "Timed out after %.1f seconds waiting for MCP task poller cleanup; cleanup continues in the background",
            _CANCELLATION_DRAIN_TIMEOUT_SECONDS,
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        loop = asyncio.get_running_loop()
        if self._stopping_task is not task:
            self._stopping_task = task
            self._stop_deadline = loop.time() + _CANCELLATION_DRAIN_TIMEOUT_SECONDS
            self._stop_timeout_logged = False
            task.cancel()
        self._stop.set()
        deadline = self._stop_deadline
        assert deadline is not None
        try:
            done, _ = await asyncio.wait(
                {task},
                timeout=max(0.0, deadline - loop.time()),
            )
        except asyncio.CancelledError:
            if not await wait_for_task_until(task, deadline=deadline):
                self._log_stop_timeout(task)
            raise
        if task not in done:
            self._log_stop_timeout(task)

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

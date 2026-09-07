from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents.batch_acceptance import check_batch_acceptance
from deerflow.subagents.batch_runtime import BatchSubmitRequest
from deerflow.subagents.capacity import SubagentExecutionCapacity
from deerflow.subagents.config import SubagentConfig, resolve_subagent_model_name
from deerflow.subagents.executor import (
    SubagentExecutor,
    SubagentStatus,
    cleanup_background_task,
    get_background_task_result,
    request_cancel_background_task,
)

logger = logging.getLogger(__name__)
_SHUTDOWN_DEADLINE_SECONDS = 4.75
_FATAL_SHUTDOWN_CLEANUP_GRACE_SECONDS = 0.1
_CANCELLED_SHUTDOWN_DRAIN_SECONDS = 0.1
_LEASE_OWNER_MAX_CHARS = 128
_CLAIM_TOKEN_CHARS = 16


def _usage(records: list[dict[str, Any]] | None) -> dict[str, int] | None:
    if not records:
        return None
    return {
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in records),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in records),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in records),
    }


class SubagentBatchService:
    """Lease, execute, and recover durable native-subagent batch items."""

    def __init__(
        self,
        *,
        repository,
        config: SubagentBatchesConfig,
        runtime_config: SubagentRuntimeConfig,
        app_config: AppConfig | None = None,
        execution_capacity: SubagentExecutionCapacity | None = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._runtime_config = runtime_config
        self._app_config = app_config
        self._execution_capacity = execution_capacity
        host_budget = _LEASE_OWNER_MAX_CHARS - 2 - 32 - _CLAIM_TOKEN_CHARS
        self._lease_owner = f"{socket.gethostname()[:host_budget]}:{uuid.uuid4().hex}"
        self._stop = asyncio.Event()
        self._poller: asyncio.Task[None] | None = None
        self._executions: dict[str, asyncio.Task[None]] = {}
        self._claim_recoveries: set[asyncio.Task[None]] = set()
        self._execution_ids: dict[str, str] = {}
        self._item_batches: dict[str, str] = {}
        self._shutdown_execution_ids: set[str] = set()
        self._first_fatal: BaseException | None = None

    def _record_fatal(self, exc: BaseException | None) -> None:
        """Retain the first non-cancellation fatal from any service task."""
        if exc is None or isinstance(exc, (asyncio.CancelledError, Exception)):
            return
        if self._first_fatal is None:
            self._first_fatal = exc

    def _poller_done(self, task: asyncio.Task[None]) -> None:
        """Observe poller fatals at completion so source ordering is preserved."""
        if task.cancelled():
            return
        self._record_fatal(task.exception())

    def _execution_done(
        self,
        item_id: str,
        task: asyncio.Task[None],
    ) -> None:
        """Forget a detached item task without losing a fatal exception."""
        self._executions.pop(item_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        self._record_fatal(exc)

    def _claim_recovery_done(self, task: asyncio.Task[None]) -> None:
        """Observe and forget a reclaimed-item fencing task."""
        self._claim_recoveries.discard(task)
        if task.cancelled():
            return
        self._record_fatal(task.exception())

    def _abandoned_cleanup_done(
        self,
        task: asyncio.Task[BaseException | None],
    ) -> None:
        """Consume a cleanup left running after its bounded cancellation drain."""
        if task.cancelled():
            return
        try:
            fatal = task.result()
        except BaseException as exc:
            fatal = exc
        self._record_fatal(fatal)
        if fatal is not None and not isinstance(
            fatal,
            (asyncio.CancelledError, Exception),
        ):
            logger.critical(
                "Detached subagent batch cleanup completed with a fatal error",
                exc_info=(type(fatal), fatal, fatal.__traceback__),
            )

    async def start(self) -> None:
        if self._poller is not None:
            return
        self._stop.clear()
        self._poller = asyncio.create_task(self._run(), name="subagent-batch-poller")
        self._poller.add_done_callback(self._poller_done)

    async def stop(self) -> None:
        loop = asyncio.get_running_loop()
        shutdown_deadline = loop.time() + _SHUTDOWN_DEADLINE_SECONDS
        cleanup = asyncio.create_task(
            self._stop_and_cleanup(),
            name="subagent-batch-stop-cleanup",
        )
        # Leave room inside the service-owned deadline for the same fatal
        # grace and bounded cancellation drain used when an outer caller
        # cancels shutdown. This keeps direct SubagentRuntime.stop() bounded;
        # Gateway's five-second wait_for remains a last-resort guard.
        reserved_cleanup_budget = min(
            _FATAL_SHUTDOWN_CLEANUP_GRACE_SECONDS + _CANCELLED_SHUTDOWN_DRAIN_SECONDS,
            _SHUTDOWN_DEADLINE_SECONDS / 2,
        )
        initial_wait_timeout = max(
            0.0,
            _SHUTDOWN_DEADLINE_SECONDS - reserved_cleanup_budget,
        )
        try:
            pending_fatal = await asyncio.wait_for(
                asyncio.shield(cleanup),
                timeout=initial_wait_timeout,
            )
        except (TimeoutError, asyncio.CancelledError):
            # Preserve both the service-owned and caller-owned shutdown
            # deadlines. Once either expires, cancel the cleanup owner and
            # surface an already-observed fatal instead of converting it into
            # an ordinary timeout/cancellation.
            pending_fatal = self._first_fatal
            if pending_fatal is not None:
                fatal_grace = min(
                    _FATAL_SHUTDOWN_CLEANUP_GRACE_SECONDS,
                    max(0.0, shutdown_deadline - loop.time()),
                )
                try:
                    if fatal_grace <= 0:
                        raise TimeoutError
                    cleanup_fatal = await asyncio.wait_for(asyncio.shield(cleanup), timeout=fatal_grace)
                except (TimeoutError, asyncio.CancelledError):
                    pass
                except BaseException as exc:
                    self._record_fatal(exc)
                else:
                    pending_fatal = pending_fatal or cleanup_fatal
                    self._record_fatal(cleanup_fatal)
                # A detached item can report a new fatal while cleanup gets its
                # short grace period. Preserve first-observed ordering.
                pending_fatal = pending_fatal or self._first_fatal
            if not cleanup.done():
                cleanup.cancel()
            drain_timeout = min(
                _CANCELLED_SHUTDOWN_DRAIN_SECONDS,
                max(0.0, shutdown_deadline - loop.time()),
            )
            try:
                if drain_timeout <= 0:
                    raise TimeoutError
                cleanup_fatal = await asyncio.wait_for(asyncio.shield(cleanup), timeout=drain_timeout)
            except TimeoutError:
                cleanup.add_done_callback(self._abandoned_cleanup_done)
                logger.critical(
                    "Subagent batch cleanup resisted cancellation past the drain deadline; detaching it",
                )
            except asyncio.CancelledError:
                # A completed, cancelled cleanup has been fully observed.
                # Otherwise another caller cancellation interrupted the drain,
                # so leave the same result-consuming callback behind.
                if not cleanup.done():
                    cleanup.add_done_callback(self._abandoned_cleanup_done)
            except BaseException as exc:
                self._record_fatal(exc)
            else:
                pending_fatal = pending_fatal or cleanup_fatal
                self._record_fatal(cleanup_fatal)
            pending_fatal = pending_fatal or self._first_fatal
            if pending_fatal is not None:
                self._first_fatal = None
                raise pending_fatal
            raise
        except BaseException as exc:
            self._record_fatal(exc)
            pending_fatal = self._first_fatal or exc
        if pending_fatal is not None:
            raise pending_fatal

    async def _stop_and_cleanup(self) -> BaseException | None:
        # Freeze ownership before waking item pollers.  Their cancellation
        # cleanup removes entries from both maps, but shutdown must still wait
        # for every admitted background execution to finish teardown.
        tasks = {
            id(task): task
            for task in (
                *self._executions.values(),
                *self._claim_recoveries,
            )
        }
        self._shutdown_execution_ids.update(self._execution_ids.values())
        self._stop.set()
        poller = self._poller
        self._poller = None
        if poller is not None:
            poller.cancel()
            poller_results = await asyncio.gather(poller, return_exceptions=True)
            for poller_result in poller_results:
                if isinstance(poller_result, BaseException):
                    self._record_fatal(poller_result)
        # A repository may finish a claim transaction while cancellation is
        # being delivered.  Reconcile once the sole task producer has stopped.
        tasks.update(
            {
                id(task): task
                for task in (
                    *self._executions.values(),
                    *self._claim_recoveries,
                )
            }
        )
        self._shutdown_execution_ids.update(self._execution_ids.values())
        for execution_id in tuple(self._shutdown_execution_ids):
            request_cancel_background_task(execution_id)
        for task in tasks.values():
            task.cancel()
        if tasks:
            task_results = await asyncio.gather(
                *tasks.values(),
                return_exceptions=True,
            )
            for task_result in task_results:
                if isinstance(task_result, BaseException):
                    self._record_fatal(task_result)
        pending_execution_ids = set(self._shutdown_execution_ids)
        while pending_execution_ids:
            for execution_id in tuple(pending_execution_ids):
                result = get_background_task_result(execution_id)
                if result is None:
                    pending_execution_ids.remove(execution_id)
                    self._shutdown_execution_ids.discard(execution_id)
                    continue
                if result.execution_done_event.is_set() and (result.status.is_terminal or result.completed_at is not None):
                    cleanup_background_task(execution_id)
                    pending_execution_ids.remove(execution_id)
                    self._shutdown_execution_ids.discard(execution_id)
            if pending_execution_ids:
                await asyncio.sleep(0.05)
        self._executions.clear()
        self._claim_recoveries.clear()
        self._execution_ids.clear()
        self._item_batches.clear()
        pending_fatal = self._first_fatal
        self._first_fatal = None
        return pending_fatal

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once(now=datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Subagent batch scheduler pass failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._config.poll_interval_seconds,
                )
            except TimeoutError:
                pass

    async def _compensate_claims(
        self,
        items: list[dict[str, Any]],
        *,
        lease_owner: str,
        error: str,
    ) -> None:
        """Release claims that never reached local execution admission."""
        compensation_results = await asyncio.gather(
            *(
                self._repository.requeue_item_after_admission_failure(
                    item["id"],
                    lease_owner=lease_owner,
                    error=error,
                    now=datetime.now(UTC),
                )
                for item in items
            ),
            return_exceptions=True,
        )
        for item, compensation_result in zip(
            items,
            compensation_results,
            strict=True,
        ):
            if isinstance(compensation_result, BaseException):
                logger.error(
                    "Could not compensate durable subagent claim (item_id=%s)",
                    item["id"],
                    exc_info=(
                        type(compensation_result),
                        compensation_result,
                        compensation_result.__traceback__,
                    ),
                )
        for compensation_result in compensation_results:
            if isinstance(compensation_result, BaseException) and not isinstance(
                compensation_result,
                Exception,
            ):
                raise compensation_result

    async def _drain_reclaimed_local_execution(
        self,
        *,
        item_id: str,
        task: asyncio.Task[None],
        lease_owner: str,
    ) -> bool:
        """Fence a reclaimed item until its stale local execution has drained."""
        execution_id = self._execution_ids.get(item_id)
        if execution_id is not None:
            request_cancel_background_task(execution_id)
        task.cancel()
        renew_every = max(1.0, self._config.lease_seconds / 3)
        while not task.done():
            done, _pending = await asyncio.wait(
                {task},
                timeout=renew_every,
            )
            if done:
                break
            try:
                lease = await self._repository.renew_item_lease(
                    item_id,
                    lease_owner=lease_owner,
                    lease_seconds=self._config.lease_seconds,
                    now=datetime.now(UTC),
                )
            except Exception:
                logger.warning(
                    "Could not renew reclaimed durable subagent lease while draining its stale local execution (item_id=%s)",
                    item_id,
                    exc_info=True,
                )
                return False
            if not lease["valid"]:
                return False
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def _recover_reclaimed_item(
        self,
        *,
        item: dict[str, Any],
        task: asyncio.Task[None],
        lease_owner: str,
    ) -> None:
        """Drain a stale local execution before releasing its replacement claim."""
        item_id = item["id"]
        drained = await self._drain_reclaimed_local_execution(
            item_id=item_id,
            task=task,
            lease_owner=lease_owner,
        )
        if drained:
            await self._compensate_claims(
                [item],
                lease_owner=lease_owner,
                error="Worker drained a stale local execution before readmission",
            )

    async def run_once(self, *, now: datetime) -> None:
        available = max(
            0,
            self._runtime_config.max_running - len(self._executions) - len(self._claim_recoveries),
        )
        if available <= 0:
            return
        # A service identity is stable for observability, but ownership must be
        # unique per claim transaction. Otherwise an expired claim reacquired by
        # this process is indistinguishable from its stale local predecessor.
        claim_owner = f"{self._lease_owner}:{uuid.uuid4().hex[:_CLAIM_TOKEN_CHARS]}"
        items = await self._repository.claim_items(
            now=now,
            lease_owner=claim_owner,
            lease_seconds=self._config.lease_seconds,
            limit=available,
        )
        if self._stop.is_set():
            await self._compensate_claims(
                items,
                lease_owner=claim_owner,
                error="Worker stopped before execution admission",
            )
            return
        for item in items:
            item_id = item["id"]
            existing_execution = self._executions.get(item_id)
            if existing_execution is not None:
                recovery = asyncio.create_task(
                    self._recover_reclaimed_item(
                        item=item,
                        task=existing_execution,
                        lease_owner=claim_owner,
                    ),
                    name=f"subagent-batch-reclaim-{item_id}",
                )
                self._claim_recoveries.add(recovery)
                recovery.add_done_callback(self._claim_recovery_done)
                continue
            task = asyncio.create_task(
                self._execute_item(item),
                name=f"subagent-batch-item-{item_id}",
            )
            self._executions[item_id] = task
            task.add_done_callback(
                lambda completed, current_id=item_id: self._execution_done(
                    current_id,
                    completed,
                ),
            )

    async def _wait_for_execution_teardown(
        self,
        *,
        item_id: str,
        execution_id: str,
        lease_owner: str,
    ) -> None:
        """Keep the durable lease while waiting for local execution teardown."""
        renew_every = max(1.0, self._config.lease_seconds / 3)
        loop = asyncio.get_running_loop()
        # Renew immediately before entering the teardown wait. A terminal
        # business result or supervisor failure may arrive near the previous
        # lease boundary; delaying the first renewal would leave a reclaim
        # window while the local execution can still own resources.
        next_renew_at = loop.time()
        while True:
            active_result = get_background_task_result(execution_id)
            done_event = getattr(active_result, "execution_done_event", None)
            if active_result is None or done_event is None or done_event.is_set():
                return
            now_monotonic = loop.time()
            if now_monotonic >= next_renew_at:
                try:
                    lease = await self._repository.renew_item_lease(
                        item_id,
                        lease_owner=lease_owner,
                        lease_seconds=self._config.lease_seconds,
                        now=datetime.now(UTC),
                    )
                except Exception:
                    logger.warning(
                        "Could not renew durable subagent lease while waiting for execution teardown (item_id=%s)",
                        item_id,
                        exc_info=True,
                    )
                    # Ownership is now uncertain while this process can still
                    # hold execution resources. Fail closed immediately rather
                    # than waiting for another renewal attempt.
                    request_cancel_background_task(execution_id)
                    next_renew_at = loop.time() + min(0.1, renew_every)
                else:
                    if not lease["valid"]:
                        request_cancel_background_task(execution_id)
                    next_renew_at = loop.time() + renew_every
            await asyncio.sleep(min(0.05, max(0.0, next_renew_at - loop.time())))

    async def _finalize_item_with_retry(
        self,
        item_id: str,
        *,
        lease_owner: str,
        **kwargs: Any,
    ) -> bool:
        """Retry an uncertain terminal write without changing its meaning."""
        for attempt in range(2):
            try:
                return await self._repository.finalize_item(
                    item_id,
                    lease_owner=lease_owner,
                    **kwargs,
                )
            except Exception:
                logger.exception(
                    "Could not persist durable subagent terminal result (item_id=%s, attempt=%s)",
                    item_id,
                    attempt + 1,
                )
        return False

    async def submit(self, request: BatchSubmitRequest) -> dict[str, Any]:
        total = len(request.items)
        if total < 1 or total > self._config.max_items_per_batch:
            raise ValueError(f"Batch item count must be between 1 and {self._config.max_items_per_batch}")
        max_live = request.max_live_items or self._config.default_max_live_items
        max_running = request.max_running_items or self._config.default_max_running_items
        if not 1 <= max_live <= self._config.max_live_items_per_batch:
            raise ValueError(f"max_live_items must be between 1 and {self._config.max_live_items_per_batch}")
        if not 1 <= max_running <= self._config.max_running_items_per_batch:
            raise ValueError(f"max_running_items must be between 1 and {self._config.max_running_items_per_batch}")
        if max_running > max_live:
            raise ValueError("max_running_items must not exceed max_live_items")
        return await self._repository.create_batch(
            batch_id=f"subagent-batch-{uuid.uuid4().hex}",
            user_id=request.user_id,
            thread_id=request.thread_id,
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            submission_key=request.submission_key,
            title=request.title,
            subagent_type=request.subagent_type,
            items=request.items,
            max_live_items=max_live,
            max_running_items=max_running,
            max_attempts=self._config.max_attempts,
            execution_spec=request.execution_spec,
        )

    async def get_batch(
        self,
        *,
        batch_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        return await self._repository.get_batch(batch_id, user_id=user_id)

    async def cancel_batch(
        self,
        *,
        batch_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        batch = await self._repository.cancel_batch(batch_id, user_id=user_id)
        if batch is None:
            return None
        for item_id, execution_id in list(self._execution_ids.items()):
            if self._item_batches.get(item_id) == batch_id:
                request_cancel_background_task(execution_id)
        # Normal ids are not prefixed; the renew loop observes the durable
        # cancellation within lease_seconds/3. Keeping cancellation durable is
        # what lets another worker own the HTTP control request safely.
        return batch

    async def _execute_item(self, item: dict[str, Any]) -> None:
        item_id = item["id"]
        lease_owner = item.get("_lease_owner", self._lease_owner)
        execution_id: str | None = None
        try:
            batch = item["batch"]
            self._item_batches[item_id] = batch["id"]
            spec = batch["execution_spec"]
            config = SubagentConfig(**spec["subagent_config"])
            app_config = self._app_config or get_app_config()
            from deerflow.tools import get_available_tools

            effective_model = resolve_subagent_model_name(
                config,
                spec.get("parent_model"),
                app_config=app_config,
            )
            tools = get_available_tools(
                groups=spec.get("tool_groups"),
                model_name=effective_model,
                subagent_enabled=False,
                include_upload_tool=False,
                app_config=app_config,
            )
            executor = SubagentExecutor(
                config=config,
                tools=tools,
                app_config=app_config,
                parent_model=spec.get("parent_model"),
                thread_id=batch["thread_id"],
                user_id=batch["user_id"],
                user_role=spec.get("user_role"),
                oauth_provider=spec.get("oauth_provider"),
                oauth_id=spec.get("oauth_id"),
                run_id=batch.get("run_id"),
                channel_user_id=spec.get("channel_user_id"),
                is_internal=spec.get("is_internal") is True,
                authz_attributes=spec.get("authz_attributes"),
                execution_capacity=self._execution_capacity,
                acceptance_criteria=item.get("acceptance_criteria"),
            )
            prompt = f"Durable batch item key: {item['item_key']}\nThis item may be retried after a worker crash. Keep side effects idempotent and use the item key as the idempotency identity.\n\n{item['prompt']}"
            marked_running = await self._repository.mark_item_running(
                item_id,
                lease_owner=lease_owner,
                now=datetime.now(UTC),
            )
            if not marked_running:
                return
            execution_id = executor.execute_async(prompt, task_id=item_id)
            self._execution_ids[item_id] = execution_id
            renew_every = max(1.0, self._config.lease_seconds / 3)
            status_poll_every = min(
                self._config.poll_interval_seconds,
                renew_every,
            )
            loop = asyncio.get_running_loop()
            next_renew_at = loop.time() + renew_every
            while True:
                result = get_background_task_result(execution_id)
                if result is None:
                    raise RuntimeError("Native subagent execution disappeared")
                if result.status.is_terminal:
                    await self._wait_for_execution_teardown(
                        item_id=item_id,
                        execution_id=execution_id,
                        lease_owner=lease_owner,
                    )
                    result = get_background_task_result(execution_id)
                    if result is None:
                        raise RuntimeError(
                            "Native subagent execution disappeared after teardown",
                        )
                    get_fatal_error = getattr(result, "get_fatal_error", None)
                    fatal_error = get_fatal_error() if callable(get_fatal_error) else None
                    if fatal_error is not None:
                        raise fatal_error
                    break
                now_monotonic = loop.time()
                if now_monotonic >= next_renew_at:
                    lease = await self._repository.renew_item_lease(
                        item_id,
                        lease_owner=lease_owner,
                        lease_seconds=self._config.lease_seconds,
                        now=datetime.now(UTC),
                    )
                    next_renew_at = loop.time() + renew_every
                    if not lease["valid"]:
                        request_cancel_background_task(execution_id)
                try:
                    until_renew = max(0.0, next_renew_at - loop.time())
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=min(status_poll_every, until_renew),
                    )
                    if self._stop.is_set():
                        raise asyncio.CancelledError
                except TimeoutError:
                    pass

            raw_result = result.result or ""
            if getattr(result, "admission_failure", False):
                await self._repository.requeue_item_after_admission_failure(
                    item_id,
                    lease_owner=lease_owner,
                    error=result.error,
                    now=datetime.now(UTC),
                )
                return
            truncated = len(raw_result) > self._config.max_result_chars
            stored_result = raw_result[: self._config.max_result_chars] if raw_result else None
            preview = raw_result[: self._config.result_preview_max_chars] if raw_result else None
            acceptance_verdict = None
            if result.status is SubagentStatus.COMPLETED and item.get("acceptance_criteria"):
                try:
                    valid, acceptance_verdict = await self._check_acceptance_with_lease(item, result, app_config)
                    if not valid:
                        return
                except Exception:
                    # Advisory like ordinary task acceptance: an unavailable
                    # checker must not discard useful work or trigger a retry.
                    logger.warning("Batch acceptance check failed; result remains unchecked (item_id=%s)", item_id, exc_info=True)
            await self._finalize_item_with_retry(
                item_id,
                lease_owner=lease_owner,
                succeeded=result.status is SubagentStatus.COMPLETED,
                result=stored_result,
                result_preview=preview,
                result_truncated=truncated,
                error=result.error,
                stop_reason=result.stop_reason,
                token_usage=_usage(result.token_usage_records),
                model_name=effective_model,
                completed_at=datetime.now(UTC),
                acceptance_verdict=acceptance_verdict,
            )
        except Exception as exc:
            logger.exception(
                "Durable subagent batch item failed (item_id=%s)",
                item_id,
            )
            if execution_id is not None:
                request_cancel_background_task(execution_id)
                await self._wait_for_execution_teardown(
                    item_id=item_id,
                    execution_id=execution_id,
                    lease_owner=lease_owner,
                )
            await self._finalize_item_with_retry(
                item_id,
                lease_owner=lease_owner,
                succeeded=False,
                result=None,
                result_preview=None,
                result_truncated=False,
                error=str(exc)[:4_000],
                stop_reason=None,
                token_usage=None,
                model_name=None,
                completed_at=datetime.now(UTC),
            )
        except BaseException:
            if execution_id is not None:
                try:
                    request_cancel_background_task(execution_id)
                finally:
                    await self._wait_for_execution_teardown(
                        item_id=item_id,
                        execution_id=execution_id,
                        lease_owner=lease_owner,
                    )
            # Fatal exits, including cancellation during process shutdown, must
            # not release the durable lease or registry entry until the native
            # execution has finished all teardown.
            raise
        finally:
            self._execution_ids.pop(item_id, None)
            self._item_batches.pop(item_id, None)
            if execution_id is not None:
                cleanup_background_task(execution_id)

    async def _check_acceptance_with_lease(self, item, result, app_config):
        """Keep a completed execution leased until its advisory check drains."""

        async def renew():
            lease = await self._repository.renew_item_lease(
                item["id"],
                lease_owner=self._lease_owner,
                lease_seconds=self._config.lease_seconds,
                now=datetime.now(UTC),
            )
            return lease["valid"]

        if not await renew():
            return False, None
        check = asyncio.create_task(
            check_batch_acceptance(
                item["acceptance_criteria"],
                batch=item["batch"],
                app_config=app_config,
                bash_executions=getattr(result, "bash_executions", None),
            )
        )
        try:
            while True:
                done, _ = await asyncio.wait({check}, timeout=max(1.0, self._config.lease_seconds / 3))
                if done:
                    return True, check.result()
                if not await renew():
                    return False, None
        finally:
            if not check.done():
                check.cancel()
            # The checklist's sandbox offload drains before releasing its
            # holder, even when shutdown or a lost lease cancels this task.
            await asyncio.gather(check, return_exceptions=True)

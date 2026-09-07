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
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._stop = asyncio.Event()
        self._poller: asyncio.Task[None] | None = None
        self._executions: dict[str, asyncio.Task[None]] = {}
        self._execution_ids: dict[str, str] = {}
        self._item_batches: dict[str, str] = {}

    async def start(self) -> None:
        if self._poller is not None:
            return
        self._stop.clear()
        self._poller = asyncio.create_task(self._run(), name="subagent-batch-poller")

    async def stop(self) -> None:
        self._stop.set()
        poller = self._poller
        self._poller = None
        if poller is not None:
            poller.cancel()
            await asyncio.gather(poller, return_exceptions=True)
        execution_ids = list(self._execution_ids.values())
        for execution_id in execution_ids:
            request_cancel_background_task(execution_id)
        tasks = list(self._executions.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._executions.clear()
        self._execution_ids.clear()
        self._item_batches.clear()

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

    async def run_once(self, *, now: datetime) -> None:
        available = max(0, self._runtime_config.max_running - len(self._executions))
        if available <= 0:
            return
        items = await self._repository.claim_items(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._config.lease_seconds,
            limit=available,
        )
        for item in items:
            item_id = item["id"]
            if item_id in self._executions:
                continue
            task = asyncio.create_task(
                self._execute_item(item),
                name=f"subagent-batch-item-{item_id}",
            )
            self._executions[item_id] = task
            task.add_done_callback(
                lambda _task, current_id=item_id: self._executions.pop(
                    current_id,
                    None,
                )
            )

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
            )
            prompt = f"Durable batch item key: {item['item_key']}\nThis item may be retried after a worker crash. Keep side effects idempotent and use the item key as the idempotency identity.\n\n{item['prompt']}"
            execution_id = executor.execute_async(prompt, task_id=item_id)
            self._execution_ids[item_id] = execution_id
            marked_running = False
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
                if result.status is SubagentStatus.RUNNING and not marked_running:
                    marked_running = await self._repository.mark_item_running(
                        item_id,
                        lease_owner=self._lease_owner,
                        now=datetime.now(UTC),
                    )
                    if not marked_running:
                        request_cancel_background_task(execution_id)
                if result.status.is_terminal:
                    break
                now_monotonic = loop.time()
                if now_monotonic >= next_renew_at:
                    lease = await self._repository.renew_item_lease(
                        item_id,
                        lease_owner=self._lease_owner,
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
                    lease_owner=self._lease_owner,
                    error=result.error,
                    now=datetime.now(UTC),
                )
                return
            truncated = len(raw_result) > self._config.max_result_chars
            stored_result = raw_result[: self._config.max_result_chars] if raw_result else None
            preview = raw_result[: self._config.result_preview_max_chars] if raw_result else None
            await self._repository.finalize_item(
                item_id,
                lease_owner=self._lease_owner,
                succeeded=result.status is SubagentStatus.COMPLETED,
                result=stored_result,
                result_preview=preview,
                result_truncated=truncated,
                error=result.error,
                stop_reason=result.stop_reason,
                token_usage=_usage(result.token_usage_records),
                model_name=effective_model,
                completed_at=datetime.now(UTC),
            )
        except asyncio.CancelledError:
            if execution_id is not None:
                request_cancel_background_task(execution_id)
            # Do not finalize on process shutdown. The durable lease expires and
            # another worker reclaims the same stable item key.
            raise
        except Exception as exc:
            logger.exception(
                "Durable subagent batch item failed (item_id=%s)",
                item_id,
            )
            await self._repository.finalize_item(
                item_id,
                lease_owner=self._lease_owner,
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
        finally:
            self._execution_ids.pop(item_id, None)
            self._item_batches.pop(item_id, None)
            if execution_id is not None:
                cleanup_background_task(execution_id)

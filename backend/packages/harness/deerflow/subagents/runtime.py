"""Explicit runtime dependencies for direct ``create_deerflow_agent`` use."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.config.subagents_config import (
    DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
    MAX_TOTAL_SUBAGENTS_PER_RUN,
    MIN_TOTAL_SUBAGENTS_PER_RUN,
)
from deerflow.subagents.batch_runtime import SubagentBatchSubmitter
from deerflow.subagents.capacity import SubagentExecutionCapacity

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig


class SubagentRuntime:
    """Share native-subagent capacity and optional durable batches across graphs.

    Application entry points install equivalent process-global dependencies at
    startup. Direct graph factories instead receive this object explicitly, so
    multiple graphs can share one real execution ceiling. Supplying
    ``app_config`` also keeps their subagent registry, model, and tool
    resolution on the same caller-owned snapshot instead of global YAML.

    When ``batch_repository`` is supplied, the runtime owns a durable batch
    worker. Start it before constructing the graph (or use ``async with``) so
    ``create_deerflow_agent`` can expose the bound batch tools, and stop it
    during application shutdown.
    """

    def __init__(
        self,
        config: SubagentRuntimeConfig | None = None,
        *,
        max_total_per_run: int = DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
        batch_submitter: SubagentBatchSubmitter | None = None,
        batch_repository: Any | None = None,
        batch_config: SubagentBatchesConfig | None = None,
        app_config: AppConfig | None = None,
    ) -> None:
        if not MIN_TOTAL_SUBAGENTS_PER_RUN <= max_total_per_run <= MAX_TOTAL_SUBAGENTS_PER_RUN:
            raise ValueError(f"max_total_per_run must be between {MIN_TOTAL_SUBAGENTS_PER_RUN} and {MAX_TOTAL_SUBAGENTS_PER_RUN}")
        if batch_submitter is not None and batch_repository is not None:
            raise ValueError("Provide either batch_submitter or batch_repository, not both")
        if batch_repository is not None and not bool(getattr(batch_config, "enabled", False)):
            raise ValueError("batch_repository requires batch_config.enabled=true")
        if batch_repository is not None and app_config is None:
            raise ValueError("batch_repository requires an explicit app_config snapshot")
        if batch_config is not None and batch_repository is None:
            raise ValueError("batch_config requires batch_repository")

        self.config = (config or SubagentRuntimeConfig()).model_copy(deep=True)
        self.max_total_per_run = max_total_per_run
        self.app_config = app_config
        self.execution_capacity = SubagentExecutionCapacity(self.config)
        self.batch_config = batch_config.model_copy(deep=True) if batch_config is not None else None
        self._external_batch_submitter = batch_submitter
        self._owned_batch_service = None
        self._batch_started = False
        self._lifecycle_lock = asyncio.Lock()

        if batch_repository is not None:
            from deerflow.subagents.batch_service import SubagentBatchService

            self._owned_batch_service = SubagentBatchService(
                repository=batch_repository,
                config=self.batch_config,
                runtime_config=self.config,
                app_config=app_config,
                execution_capacity=self.execution_capacity,
            )

    @classmethod
    def from_app_config(
        cls,
        app_config: AppConfig,
        *,
        batch_repository: Any | None = None,
    ) -> SubagentRuntime:
        """Build explicit SDK dependencies from a caller-owned config snapshot."""

        runtime_config = getattr(app_config, "subagent_runtime", None)
        if not isinstance(runtime_config, SubagentRuntimeConfig):
            runtime_config = SubagentRuntimeConfig()
        max_total_per_run = int(
            getattr(
                getattr(app_config, "subagents", None),
                "max_total_per_run",
                DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
            )
        )
        batch_config = None
        if batch_repository is not None:
            configured_batches = getattr(app_config, "subagent_batches", None)
            if not isinstance(configured_batches, SubagentBatchesConfig):
                configured_batches = SubagentBatchesConfig()
            batch_config = configured_batches
        return cls(
            runtime_config,
            max_total_per_run=max_total_per_run,
            batch_repository=batch_repository,
            batch_config=batch_config,
            app_config=app_config,
        )

    @property
    def batch_submitter(self) -> SubagentBatchSubmitter | None:
        if self._external_batch_submitter is not None:
            return self._external_batch_submitter
        if self._batch_started:
            return self._owned_batch_service
        return None

    async def start(self) -> None:
        """Start the owned durable batch worker, if configured."""

        if self._owned_batch_service is None:
            return
        async with self._lifecycle_lock:
            if self._batch_started:
                return
            await self._owned_batch_service.start()
            self._batch_started = True

    async def stop(self) -> None:
        """Stop the owned worker before propagating caller cancellation.

        The drain intentionally has no timeout: releasing lifecycle ownership
        while the service is still stopping would allow work to outlive this
        runtime. The owned service's stop() must terminate, so its repository
        awaits and child cleanup must not suppress cancellation indefinitely.
        """

        service = self._owned_batch_service
        if service is None:
            return
        async with self._lifecycle_lock:
            if not self._batch_started:
                return
            # Hide the submitter immediately, but keep this lifecycle operation
            # alive until the owned worker has actually finished stopping.
            self._batch_started = False
            stop_task = asyncio.create_task(service.stop(), name="subagent-runtime-batch-stop")
            cancellation: asyncio.CancelledError | None = None
            while not stop_task.done():
                try:
                    # wait() neither forwards caller cancellation to the owned
                    # task nor raises that task's exception. Inspect its outcome
                    # below so a service failure cannot replace cancellation.
                    await asyncio.wait({stop_task})
                except asyncio.CancelledError as exc:
                    if cancellation is None:
                        cancellation = exc

            if cancellation is not None:
                try:
                    stop_task.result()
                except (asyncio.CancelledError, Exception) as exc:
                    raise cancellation from exc
                raise cancellation
            stop_task.result()

    async def __aenter__(self) -> SubagentRuntime:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

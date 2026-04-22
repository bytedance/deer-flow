"""Public runs facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from deerflow.runtime.stream_bridge import StreamEvent

from .internal.execution.executor import _RunExecution
from .internal.execution.supervisor import RunSupervisor
from .internal.planner import ExecutionPlanner
from .internal.registry import RunRegistry
from .internal.streams import RunStreamService
from .internal.wait import RunWaitService, WaitErrorResult
from .observer import ObserverLike
from .store import RunCreateStore, RunDeleteStore, RunEventStore, RunQueryStore
from .types import CancelAction, RunRecord, RunSpec


class MultitaskRejectError(Exception):
    """Raised when multitask_strategy is reject and thread has inflight runs."""

    pass


@dataclass(frozen=True)
class RunsRuntime:
    """Runtime dependencies needed to execute a run."""

    bridge: Any
    checkpointer: Any
    store: Any | None
    event_store: RunEventStore | None
    agent_factory_resolver: Callable[[str | None], Any]


class _RegistryStatusAdapter:
    """Minimal adapter so execution can update registry-backed run status."""

    def __init__(self, registry: RunRegistry) -> None:
        self._registry = registry

    async def set_status(self, run_id: str, status: Any, *, error: str | None = None) -> None:
        await self._registry.set_status(run_id, status, error=error)


class RunsFacade:
    """
    Phase 1 runs domain facade.

    Provides unified interface for:
    - create_background
    - create_and_stream
    - create_and_wait
    - join_stream
    - join_wait

    Orchestrates registry, planner, supervisor, stream, and wait services.
    Execution now flows through ExecutionPlanner + RunSupervisor rather than
    the legacy RunManager create/start path.
    """

    def __init__(
        self,
        registry: RunRegistry,
        planner: ExecutionPlanner,
        supervisor: RunSupervisor,
        stream_service: RunStreamService,
        wait_service: RunWaitService,
        runtime: RunsRuntime,
        observer: ObserverLike = None,
        query_store: RunQueryStore | None = None,
        create_store: RunCreateStore | None = None,
        delete_store: RunDeleteStore | None = None,
    ) -> None:
        self._registry = registry
        self._planner = planner
        self._supervisor = supervisor
        self._stream = stream_service
        self._wait = wait_service
        self._runtime = runtime
        self._observer = observer
        self._query_store = query_store
        self._create_store = create_store
        self._delete_store = delete_store

    async def create_background(self, spec: RunSpec) -> RunRecord:
        """
        Create a run in background mode.

        Returns immediately with the run record.
        The run executes asynchronously.
        """
        return await self._create_run(spec)

    async def create_and_stream(
        self,
        spec: RunSpec,
    ) -> tuple[RunRecord, AsyncIterator[StreamEvent]]:
        """
        Create a run and return stream.

        Returns (record, stream_iterator).
        """
        record = await self._create_run(spec)

        stream = self._stream.subscribe(record.run_id)
        return record, stream

    async def create_and_wait(
        self,
        spec: RunSpec,
    ) -> tuple[RunRecord, dict[str, Any] | WaitErrorResult | None]:
        """
        Create a run and wait for completion.

        Returns (record, final_values_or_error).
        """
        record = await self._create_run(spec)

        result = await self._wait.wait_for_values_or_error(record.run_id)
        return record, result

    async def join_stream(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Join an existing run stream.

        Supports resumption via last_event_id.
        """
        return self._stream.subscribe(run_id, last_event_id=last_event_id)

    async def join_wait(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
    ) -> dict[str, Any] | WaitErrorResult | None:
        """
        Join an existing run and wait for completion.
        """
        return await self._wait.wait_for_values_or_error(
            run_id,
            last_event_id=last_event_id,
        )

    async def cancel(
        self,
        run_id: str,
        *,
        action: CancelAction = "interrupt",
    ) -> bool:
        """Request cancellation for an active run."""
        return await self._supervisor.cancel(run_id, action=action)

    async def get_run(self, run_id: str) -> RunRecord | None:
        """Get run record by ID."""
        if self._query_store is not None:
            return await self._query_store.get_run(run_id)
        return self._registry.get(run_id)

    async def list_runs(self, thread_id: str) -> list[RunRecord]:
        """List runs for a thread."""
        if self._query_store is not None:
            return await self._query_store.list_runs(thread_id)
        return await self._registry.list_by_thread(thread_id)

    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from durable storage and local runtime state."""
        record = await self.get_run(run_id)
        if record is None:
            return False

        await self._supervisor.cancel(run_id, action="interrupt")
        await self._registry.delete(run_id)

        if self._delete_store is not None:
            return await self._delete_store.delete_run(run_id)

        return True

    async def _create_run(self, spec: RunSpec) -> RunRecord:
        """Create a run record and hand it to the execution backend."""
        await self._apply_multitask_strategy(spec)
        record = await self._registry.create(spec)
        if self._create_store is not None:
            await self._create_store.create_run(record)
        await self._start_execution(record, spec)
        return record

    async def _apply_multitask_strategy(self, spec: RunSpec) -> None:
        """Apply multitask strategy before creating run."""
        has_inflight = await self._registry.has_inflight(spec.scope.thread_id)

        if not has_inflight:
            return

        if spec.multitask_strategy == "reject":
            raise MultitaskRejectError(
                f"Thread {spec.scope.thread_id} has inflight runs"
            )
        elif spec.multitask_strategy == "interrupt":
            interrupted = await self._registry.interrupt_inflight(spec.scope.thread_id)
            for run_id in interrupted:
                await self._supervisor.cancel(run_id, action="interrupt")

    async def _start_execution(self, record: RunRecord, spec: RunSpec) -> None:
        """Start run execution via planner + supervisor."""
        # Update status to starting
        await self._registry.set_status(record.run_id, "starting")

        plan = self._planner.build(record, spec)
        status_adapter = _RegistryStatusAdapter(self._registry)
        agent_factory = self._runtime.agent_factory_resolver(spec.assistant_id)

        async def _runner(handle) -> Any:
            return await _RunExecution(
                bridge=self._runtime.bridge,
                run_manager=status_adapter,  # type: ignore[arg-type]
                record=record,
                checkpointer=self._runtime.checkpointer,
                store=self._runtime.store,
                event_store=self._runtime.event_store,
                agent_factory=agent_factory,
                graph_input=plan.graph_input,
                config=plan.runnable_config,
                observer=self._observer,
                stream_modes=plan.stream_modes,
                stream_subgraphs=plan.stream_subgraphs,
                interrupt_before=plan.interrupt_before,
                interrupt_after=plan.interrupt_after,
                handle=handle,
            ).run()

        await self._supervisor.launch(record.run_id, runner=_runner)

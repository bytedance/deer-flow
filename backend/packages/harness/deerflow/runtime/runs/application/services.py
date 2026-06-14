"""Application service skeleton for run use cases."""

from __future__ import annotations

from dataclasses import dataclass

from ..execution import RunExecutionScheduler, RunSupervisor
from ..repositories import RunEventLog, RunRepository
from ..streams import RunStreamBroker
from .commands import CancelRunCommand, CreateRunCommand, JoinRunStreamCommand
from .dto import RunMessageView, RunSnapshot, RunStreamHandle
from .queries import GetRunQuery, ListRunMessagesQuery, ListRunsQuery


@dataclass
class RunsApplicationService:
    """Use-case orchestration boundary for run runtime operations.

    PR1 only introduces the boundary and dependency shape. Existing Gateway
    handlers continue to call the legacy service functions until later PRs move
    behavior into this class.
    """

    run_repository: RunRepository
    run_event_log: RunEventLog
    stream_broker: RunStreamBroker
    scheduler: RunExecutionScheduler
    supervisor: RunSupervisor

    async def create_background(self, command: CreateRunCommand) -> RunSnapshot:
        # PR1 defines the application boundary; later PRs move Gateway runtime
        # behavior behind this method.
        raise NotImplementedError("RunsApplicationService is not wired in PR1")

    async def create_and_stream(self, command: CreateRunCommand) -> RunStreamHandle:
        raise NotImplementedError("RunsApplicationService is not wired in PR1")

    async def create_and_wait(self, command: CreateRunCommand) -> RunSnapshot:
        raise NotImplementedError("RunsApplicationService is not wired in PR1")

    async def join_stream(self, command: JoinRunStreamCommand) -> RunStreamHandle:
        raise NotImplementedError("RunsApplicationService is not wired in PR1")

    async def cancel(self, command: CancelRunCommand) -> bool:
        return await self.supervisor.cancel(command.run_id, action=command.action)

    async def get_run(self, query: GetRunQuery) -> RunSnapshot | None:
        run = await self.run_repository.get(query.run_id, user_id=query.user_id)
        if run is None:
            return None
        if query.thread_id is not None and run.thread_id != query.thread_id:
            return None
        return RunSnapshot.from_run(run)

    async def list_runs(self, query: ListRunsQuery) -> list[RunSnapshot]:
        return await self.run_repository.list_by_thread(
            query.thread_id,
            user_id=query.user_id,
            limit=query.limit,
        )

    async def list_run_messages(self, query: ListRunMessagesQuery) -> list[RunMessageView]:
        return await self.run_event_log.list_messages_by_run(
            query.thread_id,
            query.run_id,
            limit=query.limit,
            before_seq=query.before_seq,
            after_seq=query.after_seq,
        )


__all__ = [
    "RunsApplicationService",
]

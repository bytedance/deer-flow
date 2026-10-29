from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.runs.worker import RollbackPoint, _rollback_to_pre_run_checkpoint


class _BlockingSyncRollbackCheckpointer:
    def __init__(self) -> None:
        self.mutation_started = threading.Event()
        self.allow_mutation = threading.Event()
        self.mutation_finished = threading.Event()

    async def aget_tuple(self, _config: dict[str, Any]) -> None:
        return None

    def _block_mutation(self) -> None:
        self.mutation_started.set()
        try:
            assert self.allow_mutation.wait(5.0)
        finally:
            self.mutation_finished.set()

    def delete_thread(self, _thread_id: str) -> None:
        self._block_mutation()

    def put_writes(self, _config: dict[str, Any], _writes: list[tuple[str, Any]], *, task_id: str) -> None:
        del task_id
        self._block_mutation()


def _rollback_point() -> RollbackPoint:
    return RollbackPoint(
        config={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "ckpt-1"}},
        state_values={},
        messages=("before",),
        metadata={"source": "input"},
        pending_writes=(("task-a", "messages", "value"),),
    )


@pytest.mark.parametrize("mutation", ["delete_thread", "put_writes"])
@pytest.mark.asyncio
async def test_sync_rollback_mutations_drain_across_repeated_cancellation(monkeypatch, mutation: str) -> None:
    checkpointer = _BlockingSyncRollbackCheckpointer()
    rollback_point = None
    if mutation == "put_writes":
        graph = SimpleNamespace(aupdate_state=AsyncMock(return_value={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}}))
        monkeypatch.setattr("deerflow.runtime.runs.worker.build_state_mutation_graph", lambda *_args, **_kwargs: graph)
        rollback_point = _rollback_point()

    accessor = CheckpointStateAccessor(graph=SimpleNamespace(), checkpointer=checkpointer, mode="full")
    task = asyncio.create_task(
        _rollback_to_pre_run_checkpoint(
            accessor=accessor,
            checkpointer=checkpointer,
            thread_id="thread-1",
            run_id="run-1",
            rollback_point=rollback_point,
            snapshot_capture_failed=False,
        )
    )

    try:
        assert await asyncio.to_thread(checkpointer.mutation_started.wait, 1.0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)

        assert not task.done(), "rollback returned before the synchronous checkpoint mutation finished"

        checkpointer.allow_mutation.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert checkpointer.mutation_finished.is_set()
    finally:
        checkpointer.allow_mutation.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(checkpointer.mutation_finished.wait, 1.0)

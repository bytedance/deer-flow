from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from deerflow.runtime.goal import build_goal_state, write_thread_goal


class _BlockingSyncCheckpointer:
    def __init__(self) -> None:
        self.put_started = threading.Event()
        self.allow_put = threading.Event()
        self.put_finished = threading.Event()
        self.saved_checkpoint = None

    def get_tuple(self, _config):
        return SimpleNamespace(
            config={"configurable": {"checkpoint_id": "checkpoint-1"}},
            checkpoint={
                "id": "checkpoint-1",
                "channel_values": {},
                "channel_versions": {},
            },
            metadata={"step": 0},
        )

    def put(self, _config, checkpoint, _metadata, _new_versions):
        self.put_started.set()
        try:
            assert self.allow_put.wait(5.0)
            self.saved_checkpoint = checkpoint
        finally:
            self.put_finished.set()


@pytest.mark.asyncio
async def test_sync_goal_checkpoint_write_drains_across_repeated_cancellation() -> None:
    checkpointer = _BlockingSyncCheckpointer()
    task = asyncio.create_task(
        write_thread_goal(
            checkpointer,
            "thread-1",
            build_goal_state("Finish the migration"),
        )
    )

    try:
        assert await asyncio.to_thread(checkpointer.put_started.wait, 1.0)

        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)

        assert not task.done(), "goal write returned before the synchronous checkpoint commit finished"

        checkpointer.allow_put.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert checkpointer.put_finished.is_set()
        assert checkpointer.saved_checkpoint is not None
    finally:
        checkpointer.allow_put.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(checkpointer.put_finished.wait, 1.0)

from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace

import pytest
from _thread_checkpoint_helpers import make_saver

from deerflow.agents.goal_state import GoalEvaluation
from deerflow.runtime.goal import build_goal_outcome, build_goal_state, read_thread_goal, write_thread_goal


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


class _AsyncUnsupportedBlockingCheckpointer(_BlockingSyncCheckpointer):
    """Like langgraph's SqliteSaver: async methods exist but are not implemented."""

    async def aget_tuple(self, _config):
        raise NotImplementedError

    async def aput(self, _config, _checkpoint, _metadata, _new_versions):
        raise NotImplementedError


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpointer_cls", [_BlockingSyncCheckpointer, _AsyncUnsupportedBlockingCheckpointer])
async def test_sync_goal_checkpoint_write_drains_across_repeated_cancellation(checkpointer_cls) -> None:
    checkpointer = checkpointer_cls()
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


@pytest.mark.asyncio
async def test_goal_sync_fallback_is_logged(caplog) -> None:
    checkpointer = _AsyncUnsupportedBlockingCheckpointer()

    with caplog.at_level(logging.DEBUG, logger="deerflow.runtime.goal"):
        await read_thread_goal(checkpointer, "thread-1")

    assert "_AsyncUnsupportedBlockingCheckpointer.aget_tuple is not implemented; falling back to get_tuple" in caplog.text


@pytest.mark.asyncio
async def test_goal_read_falls_back_to_sync_only_for_not_implemented() -> None:
    class _BrokenAsyncCheckpointer:
        def __init__(self) -> None:
            self.sync_calls = 0

        async def aget_tuple(self, _config):
            raise ConnectionError("pool closed")

        def get_tuple(self, _config):
            self.sync_calls += 1

    checkpointer = _BrokenAsyncCheckpointer()

    with pytest.raises(ConnectionError):
        await read_thread_goal(checkpointer, "thread-1")
    assert checkpointer.sync_calls == 0


@pytest.mark.asyncio
async def test_goal_read_keeps_not_implemented_without_sync_method() -> None:
    class _AsyncOnlyUnsupportedCheckpointer:
        async def aget_tuple(self, _config):
            raise NotImplementedError

    with pytest.raises(NotImplementedError):
        await read_thread_goal(_AsyncOnlyUnsupportedCheckpointer(), "thread-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("saver_kind", ["sqlite", "cached-sqlite", "postgres"])
async def test_goal_outcome_round_trips_through_the_sync_fallback(saver_kind) -> None:
    """On a sync-only saver the clear writes ``goal_outcome`` and the next goal write drops it."""
    config = {"configurable": {"thread_id": "outcome-thread", "checkpoint_ns": ""}}
    met_goal = build_goal_state("Ship it")
    record = build_goal_outcome(met_goal, GoalEvaluation(satisfied=True, blocker="none", reason="Shipped."), reply_message_id="a1")

    with make_saver(saver_kind) as saver:
        with pytest.raises(NotImplementedError):
            await saver.aget_tuple(config)
        sync_put = saver.put
        put_versions: list[set[str]] = []
        put_writes: list[object] = []

        def recording_put(write_config, checkpoint, metadata, new_versions):
            put_versions.append(set(new_versions))
            put_writes.append(metadata.get("writes"))
            return sync_put(write_config, checkpoint, metadata, new_versions)

        saver.put = recording_put
        await write_thread_goal(saver, "outcome-thread", met_goal, create_if_missing=True)
        await write_thread_goal(saver, "outcome-thread", None, as_node="goal_evaluator", outcome=record)
        cleared = await asyncio.to_thread(saver.get_tuple, config)
        await write_thread_goal(saver, "outcome-thread", build_goal_state("Next goal"))
        replaced = await asyncio.to_thread(saver.get_tuple, config)

    assert put_versions == [set(), {"goal"}, {"goal", "goal_outcome"}, {"goal", "goal_outcome"}]
    assert put_writes[2] == {"goal_evaluator": {"goal": None, "goal_outcome": record}}
    assert put_writes[3]["goal"]["goal_outcome"] is None
    assert cleared.checkpoint["channel_values"]["goal_outcome"] == record
    assert "goal" not in cleared.checkpoint["channel_values"]
    assert replaced.checkpoint["channel_values"]["goal"]["objective"] == "Next goal"
    assert "goal_outcome" not in replaced.checkpoint["channel_values"]
    # PostgresSaver drops metadata["writes"] on put; the others store it.
    if saver_kind != "postgres":
        assert cleared.metadata["writes"] == put_writes[2]
        assert replaced.metadata["writes"] == put_writes[3]

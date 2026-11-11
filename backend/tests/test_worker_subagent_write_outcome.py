"""A lost batch acknowledgement must not duplicate persisted subagent history."""

import asyncio

import pytest

from deerflow.runtime.events.store.base import RunEventStoreNotCommittedError
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, _publish_stream_item, _SubagentEventBuffer, run_agent
from deerflow.runtime.stream_bridge import MemoryStreamBridge


class OutcomeStore(MemoryRunEventStore):
    def __init__(self, outcome):
        super().__init__()
        self.outcome = outcome
        self.calls = 0
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def put_batch(self, events):
        self.calls += 1
        if self.calls != 1:
            return await super().put_batch(events)
        if self.outcome == "not_committed":
            raise RunEventStoreNotCommittedError("rejected before writing")
        rows = await super().put_batch(events)
        self.committed.set()
        if self.outcome == "gated":
            await self.release.wait()
        if self.outcome == "cancelled":
            raise asyncio.CancelledError("store lost acknowledgement")
        if self.outcome != "success":
            raise OSError("lost acknowledgement after commit")
        return rows


def step(index):
    return {
        "type": "task_running",
        "task_id": "child",
        "message_index": index,
        "message": {"type": "ai", "content": f"step {index}"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unknown", "cancelled"])
async def test_streamed_subagent_events_are_not_replayed_after_unknown_write(outcome):
    store = OutcomeStore(outcome)
    buffer = _SubagentEventBuffer(store, "thread", "run")
    bridge = MemoryStreamBridge()
    events = [step(1), {"type": "task_completed", "task_id": "child", "result": "done"}]
    for event in events:
        await _publish_stream_item(
            bridge=bridge,
            run_id="run",
            mode="custom",
            chunk=event,
            namespace=(),
            file_tool_chunk_batcher=None,
            subagent_events=buffer,
        )
    await buffer.flush()  # Worker finalization also flushes the same buffer.
    for index in range(2, 100):
        await buffer.add(step(index))
    await buffer.flush()
    await bridge.publish_end("run")

    persisted = await store.list_events("thread", "run")
    assert [event["event_type"] for event in persisted] == ["subagent.step", "subagent.end"]
    assert store.calls == 1
    assert buffer._pending == []
    assert buffer._unconfirmed_events == 2
    assert buffer._skipped_events == 98
    streamed = [event.data async for event in bridge.subscribe("run") if event.event == "custom"]
    assert streamed == events  # Persistence failure must not break live delivery.


@pytest.mark.asyncio
async def test_known_uncommitted_batch_can_retry_before_successors():
    store = OutcomeStore("not_committed")
    buffer = _SubagentEventBuffer(store, "thread", "run")
    await buffer.add(step(1))
    await buffer.flush()
    await buffer.add(step(2))
    await buffer.flush()
    persisted = await store.list_events("thread", "run")
    assert [event["metadata"]["message_index"] for event in persisted] == [1, 2]
    assert store.calls == 2
    assert not buffer._pending


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["gated", "success"])
async def test_host_cancellation_drains_write_without_replaying(outcome):
    store = OutcomeStore(outcome)
    buffer = _SubagentEventBuffer(store, "thread", "run")
    await buffer.add(step(1))
    task = asyncio.create_task(buffer.flush())
    try:
        await asyncio.wait_for(store.committed.wait(), 5)
        if outcome == "gated":
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            store.release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        await buffer.flush()
        assert store.calls == 1
        assert len(await store.list_events("thread", "run")) == 1
    finally:
        store.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unknown", "cancelled", "success"])
async def test_worker_keeps_business_success_and_stream_end_after_store_failure(outcome):
    store = OutcomeStore(outcome)
    manager = RunManager()
    record = await manager.create("thread")
    bridge = MemoryStreamBridge()

    class Graph:
        async def astream(self, *args, **kwargs):
            yield "custom", step(1)
            yield "custom", {"type": "task_completed", "task_id": "child", "result": "done"}
            yield "values", {"messages": []}

    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda **kwargs: Graph(),
        graph_input={},
        config={},
        stream_modes=["custom", "values"],
    )
    assert record.status == RunStatus.success
    persisted = await store.list_events("thread", record.run_id, event_types=["subagent.step", "subagent.end"])
    assert [event["event_type"] for event in persisted] == ["subagent.step", "subagent.end"]
    streamed = [event async for event in bridge.subscribe(record.run_id)]
    assert streamed[-1].event == "__end__"
    assert len([event for event in streamed if event.event == "custom"]) == 2


@pytest.mark.asyncio
async def test_jsonl_commit_survives_reopen_without_duplicate_replay(tmp_path):
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    class LostAckStore(JsonlRunEventStore):
        async def put_batch(self, events):
            await super().put_batch(events)
            raise OSError("lost acknowledgement")

    buffer = _SubagentEventBuffer(LostAckStore(tmp_path), "thread", "run")
    await buffer.add(step(1))
    await buffer.flush()
    await buffer.flush()
    reopened = JsonlRunEventStore(tmp_path)
    persisted = await reopened.list_events("thread", "run")
    assert len(persisted) == 1
    assert persisted[0]["metadata"]["message_index"] == 1

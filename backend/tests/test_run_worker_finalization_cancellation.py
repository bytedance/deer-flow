"""Regression: cancellation during early terminal finalization must not skip publish_end."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, run_agent


def _make_bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


@pytest.mark.asyncio
async def test_cancellation_during_delivery_receipt_still_publishes_end(monkeypatch):
    import deerflow.runtime.runs.worker as worker_module

    run_manager = RunManager()
    record = await run_manager.create("thread-finalization-cancel")
    store = MemoryRunEventStore()
    bridge = _make_bridge()

    receipt_started = asyncio.Event()
    hold_receipt = asyncio.Event()

    async def blocking_receipt(*args, **kwargs):
        receipt_started.set()
        await hold_receipt.wait()
        return True

    monkeypatch.setattr(worker_module, "_persist_delivery_receipt", blocking_receipt)

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    worker = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=store),
            agent_factory=lambda *, config: DummyAgent(),
            graph_input={},
            config={},
        )
    )

    try:
        await asyncio.wait_for(receipt_started.wait(), timeout=10)

        worker.cancel("cancel during terminal finalization")
        await asyncio.sleep(0)
        # Release the receipt so a deferred cancellation can still finish the tail.
        hold_receipt.set()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(worker, timeout=5)

        # Invariant: the terminal END marker is still published exactly once.
        bridge.publish_end.assert_awaited_once_with(record.run_id)
    finally:
        hold_receipt.set()
        await asyncio.gather(worker, return_exceptions=True)

"""Regression coverage for off-loop Gateway agent construction (#5172)."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, run_agent


class _Agent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield {"messages": []}


def _bridge() -> SimpleNamespace:
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


@pytest.mark.anyio
async def test_gateway_agent_factory_runs_off_the_event_loop() -> None:
    """A slow synchronous MCP/tool assembly must not stall Gateway's loop."""
    run_manager = RunManager()
    record = await run_manager.create("thread-agent-construction")
    factory_started = threading.Event()
    release_factory = threading.Event()
    factory_thread_ids: list[int] = []
    heartbeat: list[float] = []
    stop_heartbeat = asyncio.Event()

    def agent_factory(*, config):
        factory_thread_ids.append(threading.get_ident())
        factory_started.set()
        release_factory.wait(timeout=1)
        return _Agent()

    def release_after_factory_starts() -> None:
        factory_started.wait(timeout=1)
        time.sleep(0.2)
        release_factory.set()

    async def ticker() -> None:
        while not stop_heartbeat.is_set():
            heartbeat.append(time.perf_counter())
            await asyncio.sleep(0.01)

    releaser = threading.Thread(target=release_after_factory_starts, daemon=True)
    releaser.start()
    ticker_task = asyncio.create_task(ticker())
    try:
        await run_agent(
            _bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=agent_factory,
            graph_input={},
            config={},
        )
    finally:
        stop_heartbeat.set()
        await ticker_task
        await asyncio.to_thread(releaser.join, 1)

    assert factory_thread_ids != [threading.get_ident()]
    assert len(heartbeat) > 1
    heartbeat_gaps = [later - earlier for earlier, later in zip(heartbeat, heartbeat[1:])]
    assert max(heartbeat_gaps) < 0.1

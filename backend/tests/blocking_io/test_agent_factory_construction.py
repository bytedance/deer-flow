"""Regression coverage for off-loop Gateway agent construction (#5172)."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.gateway import services
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, run_agent


class _Agent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield {"messages": []}


def _bridge() -> SimpleNamespace:
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


pytestmark = pytest.mark.asyncio


async def _assert_factory_runs_off_the_event_loop(invoke) -> None:
    """The release waits for an event-loop heartbeat while assembly is blocked."""
    factory_started = threading.Event()
    release_factory = threading.Event()
    heartbeat_during_factory = threading.Event()
    factory_thread_ids: list[int] = []
    stop_heartbeat = asyncio.Event()

    def agent_factory(*, config):
        factory_thread_ids.append(threading.get_ident())
        factory_started.set()
        release_factory.wait(timeout=1)
        return _Agent()

    def release_after_factory_starts() -> None:
        factory_started.wait(timeout=1)
        heartbeat_during_factory.wait(timeout=1)
        release_factory.set()

    async def ticker() -> None:
        while not stop_heartbeat.is_set():
            if factory_started.is_set() and not release_factory.is_set():
                heartbeat_during_factory.set()
            await asyncio.sleep(0.01)

    releaser = threading.Thread(target=release_after_factory_starts, daemon=True)
    releaser.start()
    ticker_task = asyncio.create_task(ticker())
    try:
        await invoke(agent_factory)
    finally:
        stop_heartbeat.set()
        await ticker_task
        await asyncio.to_thread(releaser.join, 1)

    assert len(factory_thread_ids) == 1
    assert factory_thread_ids[0] != threading.get_ident()
    assert heartbeat_during_factory.is_set()


async def test_gateway_agent_factory_runs_off_the_event_loop() -> None:
    """Run execution keeps synchronous MCP/tool assembly off Gateway's loop."""
    run_manager = RunManager()
    record = await run_manager.create("thread-agent-construction")

    async def invoke(agent_factory) -> None:
        await run_agent(
            _bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=agent_factory,
            graph_input={},
            config={},
        )

    await _assert_factory_runs_off_the_event_loop(invoke)


async def test_gateway_checkpoint_state_factory_runs_off_the_event_loop() -> None:
    """State/history reads must not rebuild MCP tools on Gateway's loop."""
    request = SimpleNamespace(state=SimpleNamespace(checkpoint_channel_mode="full"))
    ctx = SimpleNamespace(checkpointer=object(), store=None, checkpoint_channel_mode="full", app_config=None)

    async def invoke(agent_factory) -> None:
        with (
            patch.object(services, "get_run_context", return_value=ctx),
            patch.object(services, "resolve_agent_factory", return_value=agent_factory),
        ):
            await services.build_checkpoint_state_accessor(request, thread_id="thread-checkpoint-state")

    try:
        await _assert_factory_runs_off_the_event_loop(invoke)
    finally:
        services._state_accessor_graph_cache.clear()


async def test_gateway_checkpoint_state_factory_is_single_flight() -> None:
    """Concurrent cold-cache reads build one graph without occupying extra workers."""
    request = SimpleNamespace(state=SimpleNamespace(checkpoint_channel_mode="full"))
    ctx = SimpleNamespace(checkpointer=object(), store=None, checkpoint_channel_mode="full", app_config=None)
    factory_started = threading.Event()
    release_factory = threading.Event()
    factory_calls: list[int] = []

    def agent_factory(*, config):
        factory_calls.append(threading.get_ident())
        factory_started.set()
        release_factory.wait(timeout=1)
        return _Agent()

    with (
        patch.object(services, "get_run_context", return_value=ctx),
        patch.object(services, "resolve_agent_factory", return_value=agent_factory),
    ):
        try:
            first = asyncio.create_task(services.build_checkpoint_state_accessor(request, thread_id="thread-single-flight"))
            assert await asyncio.to_thread(factory_started.wait, 1)
            second = asyncio.create_task(services.build_checkpoint_state_accessor(request, thread_id="thread-single-flight"))
            await asyncio.sleep(0)
            release_factory.set()
            first_accessor, second_accessor = await asyncio.gather(first, second)
        finally:
            release_factory.set()
            services._state_accessor_graph_cache.clear()

    assert len(factory_calls) == 1
    assert first_accessor[0].graph is second_accessor[0].graph

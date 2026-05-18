from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from app.gateway.routers.thread_runs import join_run, stream_existing_run
from deerflow.runtime import MemoryStreamBridge, RunManager
from deerflow.runtime.runs import worker


class _FakeCheckpointer:
    async def aget_tuple(self, config: dict) -> None:
        return None


class _FakeAgent:
    checkpointer = None
    store = None
    interrupt_before_nodes = None
    interrupt_after_nodes = None

    async def astream(self, graph_input: dict, *, config, stream_mode: str):
        yield {"messages": [{"role": "assistant", "content": "done"}]}


def _make_request(app: FastAPI) -> SimpleNamespace:
    return SimpleNamespace(app=app, headers={}, _deerflow_test_bypass_auth=True)


async def _run_completed_agent(monkeypatch: pytest.MonkeyPatch, *, thread_id: str = "thread-1"):
    bridge = MemoryStreamBridge()
    manager = RunManager()
    record = await manager.create(thread_id)

    scheduled_tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task
    original_bridge_cleanup = bridge.cleanup
    original_manager_cleanup = manager.cleanup

    async def immediate_bridge_cleanup(run_id: str, *, delay: float = 0) -> None:
        await original_bridge_cleanup(run_id, delay=0)

    async def immediate_manager_cleanup(run_id: str, *, delay: float = 0) -> None:
        await original_manager_cleanup(run_id, delay=0)

    def capture_task(coro):
        task = original_create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(bridge, "cleanup", immediate_bridge_cleanup)
    monkeypatch.setattr(manager, "cleanup", immediate_manager_cleanup)
    monkeypatch.setattr(worker.asyncio, "create_task", capture_task)
    monkeypatch.setattr(worker, "_TERMINAL_RUN_RETENTION_SECONDS", 0)

    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(checkpointer=_FakeCheckpointer()),
        agent_factory=lambda config: _FakeAgent(),
        graph_input={"messages": []},
        config={"configurable": {"thread_id": thread_id}},
        stream_modes=["values"],
    )

    if scheduled_tasks:
        await asyncio.gather(*scheduled_tasks)

    return bridge, manager, record


@pytest.mark.anyio
async def test_run_completion_cleanup_removes_terminal_run_record(monkeypatch: pytest.MonkeyPatch):
    _, manager, record = await _run_completed_agent(monkeypatch)

    assert manager.get(record.run_id) is None
    assert await manager.list_by_thread(record.thread_id) == []


@pytest.mark.anyio
async def test_join_endpoints_return_404_after_completed_run_cleanup(monkeypatch: pytest.MonkeyPatch):
    bridge, manager, record = await _run_completed_agent(monkeypatch)

    app = FastAPI()
    app.state.stream_bridge = bridge
    app.state.run_manager = manager
    request = _make_request(app)

    with pytest.raises(HTTPException, match="not found") as join_exc:
        await join_run(thread_id=record.thread_id, run_id=record.run_id, request=request)
    assert join_exc.value.status_code == 404

    with pytest.raises(HTTPException, match="not found") as stream_exc:
        await stream_existing_run(thread_id=record.thread_id, run_id=record.run_id, request=request)
    assert stream_exc.value.status_code == 404


@pytest.mark.anyio
async def test_run_completion_cleanup_logs_background_failures(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    bridge = MemoryStreamBridge()
    manager = RunManager()
    record = await manager.create("thread-1")

    scheduled_tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task

    async def failing_manager_cleanup(run_id: str, *, delay: float = 0) -> None:
        raise RuntimeError(f"boom for {run_id}")

    def capture_task(coro):
        task = original_create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(manager, "cleanup", failing_manager_cleanup)
    monkeypatch.setattr(worker.asyncio, "create_task", capture_task)
    monkeypatch.setattr(worker, "_TERMINAL_RUN_RETENTION_SECONDS", 0)
    logger_name = worker.logger.name

    with caplog.at_level(logging.ERROR, logger=logger_name):
        await worker.run_agent(
            bridge,
            manager,
            record,
            ctx=worker.RunContext(checkpointer=_FakeCheckpointer()),
            agent_factory=lambda config: _FakeAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
            stream_modes=["values"],
        )

        assert scheduled_tasks
        await asyncio.gather(*scheduled_tasks)

    assert any(log_record.levelno == logging.ERROR and f"Run {record.run_id} deferred cleanup failed" in log_record.message for log_record in caplog.records)

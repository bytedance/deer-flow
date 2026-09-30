"""Personal MCP config mutations drain across handler cancellation.

The gateway convention (managed subagents, managed models, custom skills,
agents router) is that a client disconnect must not cancel a queued
persistence worker or silently drop its failure. All four personal-config
mutations funnel through ``_write`` -> ``_drained_mutation``; the read stays
bare because abandoning it loses nothing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.routers.mcp import McpConfigUpdateRequest, McpServerConfigUpdateRequest, McpServerStateUpdateRequest
from app.gateway.routers.personal_mcp import (
    create_servers,
    delete_server,
    get_configuration,
    update_server,
    update_state,
)
from deerflow.config.paths import Paths
from deerflow.mcp.user_config import user_mcp_config_path

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _personal_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: Paths(base_dir=tmp_path))
    yield tmp_path


def _request(user: str = "alice", role: str = "admin") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id=user, system_role=role), auth_source="session"))


def _create_body(name: str = "github") -> McpConfigUpdateRequest:
    return McpConfigUpdateRequest.model_validate({"mcp_servers": {name: {"type": "http", "url": "https://example.com/mcp"}}})


async def _seed_server(name: str = "github") -> None:
    await create_servers(_request(), _create_body(name))


async def test_personal_mcp_writes_route_through_drain(_personal_env, monkeypatch):
    from app.gateway.routers import personal_mcp as router

    calls: list[str] = []

    async def drained(func, /, *args, **kwargs):
        calls.append(getattr(func, "__name__", str(func)))
        return func(*args, **kwargs)

    monkeypatch.setattr(router, "_drained_mutation", drained)

    await create_servers(_request(), _create_body())
    await get_configuration(_request())
    await update_server(_request(), McpServerConfigUpdateRequest.model_validate({"server_name": "github", "server": {"type": "http", "url": "https://example.com/updated"}}))
    await update_state(_request(), McpServerStateUpdateRequest(server_name="github", enabled=False))
    await delete_server(_request(), "github")

    assert calls == ["_mutate", "_mutate", "_mutate", "_mutate"]


async def test_personal_mcp_mutation_drains_started_write_across_repeated_cancellation(_personal_env, monkeypatch):
    from app.gateway.routers import personal_mcp as router

    await _seed_server()

    started = threading.Event()
    release = threading.Event()

    def blocking_mutate(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=5)
        return {"mcpServers": {"github": {"type": "http", "url": "https://example.com/mcp"}}}

    monkeypatch.setattr(router, "_mutate", blocking_mutate)

    task = asyncio.create_task(update_state(_request(), McpServerStateUpdateRequest(server_name="github", enabled=False)))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_personal_mcp_logs_lost_mutation_failure_after_cancellation(_personal_env, monkeypatch, caplog):
    from app.gateway.routers import personal_mcp as router

    await _seed_server()

    started = threading.Event()
    release = threading.Event()

    def failing_mutate(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=5)
        raise OSError("worker-secret must not appear in logs")

    monkeypatch.setattr(router, "_mutate", failing_mutate)

    with caplog.at_level(logging.ERROR, logger=router.__name__):
        task = asyncio.create_task(update_state(_request(), McpServerStateUpdateRequest(server_name="github", enabled=False)))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()

            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    failures = [record for record in caplog.records if record.name == router.__name__ and "Personal MCP config mutation failed" in record.message]
    assert len(failures) == 1
    assert "OSError" in failures[0].message
    assert "worker-secret" not in caplog.text


async def test_connected_caller_still_sees_domain_errors_unlogged(_personal_env, monkeypatch, caplog):
    """A 409 on the connected path keeps its response contract and stays unlogged."""
    from app.gateway.routers import personal_mcp as router

    await _seed_server()

    def duplicate_mutate(*_args, **_kwargs):
        raise HTTPException(status_code=409, detail="MCP server 'github' already exists")

    monkeypatch.setattr(router, "_mutate", duplicate_mutate)

    with caplog.at_level(logging.ERROR, logger=router.__name__):
        with pytest.raises(HTTPException) as excinfo:
            await create_servers(_request(), _create_body())

    assert excinfo.value.status_code == 409
    assert not [record for record in caplog.records if record.name == router.__name__]


async def test_queued_personal_mcp_mutation_lands_despite_cancellation(_personal_env, tmp_path):
    """A mutation queued behind a busy executor must still persist when the caller goes away.

    Without the drain, cancelling the handler cancels the still-queued worker
    and the personal MCP server silently never lands; the run of this test on
    unfixed code is exactly that data loss.
    """
    blocker_started = threading.Event()
    release_blocker = threading.Event()

    def _block():
        blocker_started.set()
        assert release_blocker.wait(timeout=5)

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(executor)
    try:
        jam = asyncio.create_task(asyncio.to_thread(_block))
        # Poll without touching the executor: it has a single worker, and the
        # blocker occupies it — an executor-based wait would deadlock here.
        for _ in range(100):
            if blocker_started.is_set():
                break
            await asyncio.sleep(0.05)
        assert blocker_started.is_set()

        task = asyncio.create_task(create_servers(_request(), _create_body()))
        await asyncio.sleep(0.1)  # the mutation is now queued behind the blocker
        task.cancel()
        await asyncio.sleep(0.1)

        release_blocker.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(jam, return_exceptions=True)
    finally:
        release_blocker.set()
        executor.shutdown(wait=False)

    config = user_mcp_config_path("alice")
    assert config.exists(), "queued personal MCP server create was lost to cancellation"
    assert "github" in config.read_text(encoding="utf-8")

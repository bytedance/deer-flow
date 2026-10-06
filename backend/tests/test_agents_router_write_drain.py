"""Agent-router persistent writes drain across handler cancellation.

The gateway convention (managed subagents, managed models, custom skills) is
that a client disconnect must not cancel a queued persistence worker or
silently drop its failure. The agent store writes (create / update / delete)
and the USER.md write route through ``await_drained`` the same way; reads stay
bare because abandoning them loses nothing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from pathlib import Path

import pytest

from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    UserProfileUpdateRequest,
    create_agent_endpoint,
    get_agent,
    update_agent,
    update_user_profile,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _agent_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    set_app_config(
        AppConfig(
            models=[ModelConfig(name="agent-model", display_name="Agent Model", description=None, use="langchain_openai:ChatOpenAI", model="agent-model")],
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        )
    )
    try:
        yield
    finally:
        load_agents_api_config_from_dict({})
        reset_app_config()


async def test_agent_persistent_writes_route_through_write_drain(_agent_env, monkeypatch):
    from app.gateway.routers import agents as router

    calls: list[str] = []

    async def drained(action, func, expected_errors=(), /, *args, **kwargs):
        calls.append(action)
        assert isinstance(expected_errors, tuple)
        return func(*args, **kwargs)

    monkeypatch.setattr(router, "run_drained_write", drained)

    await create_agent_endpoint(AgentCreateRequest(name="planner", model="agent-model"))
    await router.import_agent_package(router.AgentPackage(format="deerflow.custom-agent", version=1, agent={"name": "imported", "soul": "imported soul"}))
    await update_agent("planner", AgentUpdateRequest(description="later"))
    await get_agent("planner")
    await update_user_profile(UserProfileUpdateRequest(content="prefs"))
    await router.delete_agent("planner")

    assert calls == ["Create agent", "Create agent", "Update agent", "Update user profile", "Delete agent"]


async def test_agent_import_drains_started_store_write_across_repeated_cancellation(_agent_env, monkeypatch):
    from app.gateway.routers import agents as router

    store = router.get_agent_store()
    started = threading.Event()
    release = threading.Event()

    class BlockingStore:
        def create(self, *args, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            return store.create(*args, **kwargs)

    monkeypatch.setattr(router, "get_agent_store", lambda: BlockingStore())
    package = router.AgentPackage(
        format="deerflow.custom-agent",
        version=1,
        agent={"name": "imported", "soul": "imported soul", "memory_enabled": False},
    )
    task = asyncio.create_task(router.import_agent_package(package))
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
        imported = await get_agent("imported")
        assert imported.soul == "imported soul"
        assert router.load_agent_config("imported", user_id=router.get_effective_user_id()).memory_enabled is False
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_agent_update_drains_started_store_write_across_repeated_cancellation(_agent_env, monkeypatch):
    from app.gateway.routers import agents as router

    await create_agent_endpoint(AgentCreateRequest(name="planner", model="agent-model"))

    started = threading.Event()
    release = threading.Event()

    class BlockingStore:
        def update(self, *_args, **_kwargs):
            started.set()
            assert release.wait(timeout=5)

    monkeypatch.setattr(router, "get_agent_store", lambda: BlockingStore())

    task = asyncio.create_task(update_agent("planner", AgentUpdateRequest(description="later")))
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


async def test_agent_update_logs_lost_worker_failure_after_cancellation(_agent_env, monkeypatch, caplog):
    from app.gateway.routers import agents as router

    await create_agent_endpoint(AgentCreateRequest(name="planner", model="agent-model"))

    started = threading.Event()
    release = threading.Event()

    class FailingStore:
        def update(self, *_args, **_kwargs):
            started.set()
            assert release.wait(timeout=5)
            raise OSError("worker-secret must not appear in logs")

    monkeypatch.setattr(router, "get_agent_store", lambda: FailingStore())

    with caplog.at_level(logging.ERROR, logger=router.__name__):
        task = asyncio.create_task(update_agent("planner", AgentUpdateRequest(description="later")))
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

    failures = [record for record in caplog.records if record.name == "app.gateway.persistent_writes" and "Update agent failed" in record.message]
    assert len(failures) == 1
    assert "OSError" in failures[0].message
    assert "worker-secret" not in caplog.text


async def test_queued_user_profile_write_runs_despite_cancellation(_agent_env, tmp_path):
    """A write queued behind a busy executor must still run when the caller goes away.

    Without the drain, cancelling the handler cancels the still-queued worker
    and the profile silently never lands; the run of this test on unfixed code
    is exactly that data loss.
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

        task = asyncio.create_task(update_user_profile(UserProfileUpdateRequest(content="saved-prefs")))
        await asyncio.sleep(0.1)  # the write is now queued behind the blocker
        task.cancel()
        await asyncio.sleep(0.1)

        release_blocker.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(jam, return_exceptions=True)
    finally:
        release_blocker.set()
        executor.shutdown(wait=False)

    assert list(tmp_path.rglob("USER.md")), "queued USER.md write was lost to cancellation"

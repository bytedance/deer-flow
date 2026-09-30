from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import deerflow.projects.trash as trash_mod


class _EmptySweepRepo:
    async def purge_candidates(self, *args, **kwargs):
        return []

    async def list_all_for_sweep(self, *args, **kwargs):
        return []


@pytest.mark.anyio
@pytest.mark.parametrize("worker_name", ["_reconcile_storage", "_reconcile_rows"])
async def test_cancelled_retention_sweep_drains_reconciliation_worker(monkeypatch, worker_name: str) -> None:
    """Cancellation cannot outlive an already-started reconciliation worker."""
    started = threading.Event()
    finish = threading.Event()

    def blocking_reconcile(*args, **kwargs) -> None:
        started.set()
        finish.wait(5)

    if worker_name == "_reconcile_rows":
        monkeypatch.setattr(trash_mod, "_reconcile_storage", lambda *args, **kwargs: None)
    monkeypatch.setattr(trash_mod, worker_name, blocking_reconcile)

    task = asyncio.create_task(
        trash_mod.run_trash_retention_sweep(
            _EmptySweepRepo(),
            object(),
            retention_days=30,
            user_id=None,
        )
    )
    assert await asyncio.to_thread(started.wait, 5)

    task.cancel()
    try:
        for _ in range(10):
            await asyncio.sleep(0)
        assert not task.done(), "the sweep released ownership while its file-io worker was still running"
    finally:
        finish.set()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_shutdown_hook_drains_running_reconciliation_worker_after_grace_budget(monkeypatch) -> None:
    """The shutdown grace budget does not detach already-started file work."""
    import app.gateway.app as gateway_app

    started = threading.Event()
    finish = threading.Event()

    def blocking_reconcile(*args, **kwargs) -> None:
        started.set()
        finish.wait(5)

    monkeypatch.setattr(trash_mod, "_reconcile_storage", blocking_reconcile)
    monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.01)

    app = FastAPI()
    app.state.project_document_repo = _EmptySweepRepo()
    sweep_task = asyncio.create_task(gateway_app._run_startup_trash_sweep(app, SimpleNamespace(projects=None)))
    app.state.startup_trash_sweep_task = sweep_task
    assert await asyncio.to_thread(started.wait, 5)

    shutdown_task = asyncio.create_task(gateway_app._shutdown_startup_trash_sweep(app))
    try:
        for _ in range(100):
            if sweep_task.cancelling():
                break
            await asyncio.sleep(0.001)
        assert sweep_task.cancelling(), "shutdown never cancelled the over-budget startup sweep"
        assert not sweep_task.done(), "sweep cancellation detached its running file-io worker"
        assert not shutdown_task.done(), "shutdown hook returned while reconciliation was still running"
    finally:
        finish.set()

    await shutdown_task
    assert sweep_task.cancelled()

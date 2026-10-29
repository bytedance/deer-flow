from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.gateway.routers import integrations


@pytest.mark.asyncio
async def test_lark_install_drains_cache_refresh_across_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    release = threading.Event()
    refreshed = asyncio.Event()

    async def allow_admin(*_args, **_kwargs) -> None:
        return None

    def install(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=5)
        return object()

    async def refresh() -> None:
        refreshed.set()

    monkeypatch.setattr(integrations, "require_admin_user", allow_admin)
    monkeypatch.setattr(integrations, "install_lark_integration", install)
    monkeypatch.setattr(integrations, "refresh_skills_system_prompt_cache_async", refresh)

    task = asyncio.create_task(integrations.install_lark(request=None, config=SimpleNamespace()))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert refreshed.is_set()
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence import engine as engine_mod


class _BlockingDisposeEngine:
    def __init__(self) -> None:
        self.dispose_started = asyncio.Event()
        self.allow_dispose = asyncio.Event()
        self.dispose_finished = asyncio.Event()

    async def dispose(self) -> None:
        self.dispose_started.set()
        await self.allow_dispose.wait()
        self.dispose_finished.set()


@pytest.mark.asyncio
async def test_postgres_auto_create_retry_drains_provisional_engine_dispose_across_cancellation(monkeypatch) -> None:
    engine = _BlockingDisposeEngine()
    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace())
    monkeypatch.setattr(engine_mod, "create_async_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(engine_mod, "async_sessionmaker", lambda *args, **kwargs: object())

    async def fail_bootstrap(*args, **kwargs) -> None:
        raise RuntimeError("database does not exist")

    async def fake_auto_create(_url: str) -> None:
        return None

    monkeypatch.setattr(bootstrap_mod, "bootstrap_schema", fail_bootstrap)
    monkeypatch.setattr(engine_mod, "_auto_create_postgres_db", fake_auto_create)

    task = asyncio.create_task(
        engine_mod.init_engine(
            "postgres",
            url="postgresql+asyncpg://user:password@localhost/deerflow",
        )
    )
    try:
        await asyncio.wait_for(engine.dispose_started.wait(), timeout=2)

        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        engine.allow_dispose.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        engine.allow_dispose.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        engine_mod._engine = None
        engine_mod._session_factory = None

    assert engine.dispose_finished.is_set()

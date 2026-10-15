from __future__ import annotations

import asyncio

import pytest

from deerflow.persistence import engine as engine_mod

_TARGET_URL = "postgresql+asyncpg://deerflow:secret@127.0.0.1:5432/deerflow_target"


class _RecordingConnection:
    def __init__(self) -> None:
        self.executed = asyncio.Event()
        self.statements: list[str] = []

    async def __aenter__(self) -> _RecordingConnection:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))
        self.executed.set()


class _BlockingMaintenanceEngine:
    """Fake maintenance engine whose ``dispose()`` can be held open."""

    def __init__(self) -> None:
        self.connection = _RecordingConnection()
        self.dispose_started = asyncio.Event()
        self.allow_dispose = asyncio.Event()
        self.dispose_finished = asyncio.Event()

    def connect(self) -> _RecordingConnection:
        return self.connection

    async def dispose(self) -> None:
        self.dispose_started.set()
        await self.allow_dispose.wait()
        self.dispose_finished.set()


@pytest.mark.asyncio
async def test_auto_create_db_drains_maintenance_dispose_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancelled first boot must still dispose the engine it opened.

    ``_auto_create_postgres_db`` owns a throwaway engine against the server's
    ``postgres`` database. Its ``finally`` dispose was a bare await, so host
    cancellation could return from the helper with that engine's pool still
    live — and because the engine is a local, nothing else ever disposes it.
    """
    maintenance_engine = _BlockingMaintenanceEngine()
    task: asyncio.Task[None] | None = None

    monkeypatch.setattr(engine_mod, "create_async_engine", lambda *args, **kwargs: maintenance_engine)

    try:
        task = asyncio.create_task(engine_mod._auto_create_postgres_db(_TARGET_URL))
        await asyncio.wait_for(maintenance_engine.connection.executed.wait(), timeout=1)
        assert 'CREATE DATABASE "deerflow_target"' in maintenance_engine.connection.statements[0]
        await asyncio.wait_for(maintenance_engine.dispose_started.wait(), timeout=1)

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "database auto-creation returned before the maintenance engine was disposed"

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation interrupted the maintenance engine dispose"

        maintenance_engine.allow_dispose.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert maintenance_engine.dispose_finished.is_set()
    finally:
        maintenance_engine.allow_dispose.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

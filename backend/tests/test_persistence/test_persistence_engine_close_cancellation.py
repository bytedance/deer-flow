import asyncio

import pytest

from deerflow.persistence import engine as engine_mod


class _BlockingEngine:
    def __init__(self) -> None:
        self.dispose_started = asyncio.Event()
        self.allow_dispose = asyncio.Event()
        self.dispose_finished = asyncio.Event()

    async def dispose(self) -> None:
        self.dispose_started.set()
        await self.allow_dispose.wait()
        self.dispose_finished.set()


@pytest.mark.asyncio
async def test_close_engine_drains_dispose_across_repeated_cancellation() -> None:
    fake_engine = _BlockingEngine()
    fake_factory = object()
    previous_engine = engine_mod._engine
    previous_factory = engine_mod._session_factory
    task: asyncio.Task[None] | None = None

    try:
        engine_mod._engine = fake_engine
        engine_mod._session_factory = fake_factory
        task = asyncio.create_task(engine_mod.close_engine())
        await asyncio.wait_for(fake_engine.dispose_started.wait(), timeout=1)

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "engine teardown returned before dispose finished"
        assert engine_mod._engine is fake_engine
        assert engine_mod._session_factory is fake_factory

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation interrupted engine dispose"

        fake_engine.allow_dispose.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert fake_engine.dispose_finished.is_set()
        assert engine_mod._engine is None
        assert engine_mod._session_factory is None
    finally:
        fake_engine.allow_dispose.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        engine_mod._engine = previous_engine
        engine_mod._session_factory = previous_factory


@pytest.mark.asyncio
async def test_close_engine_preserves_replacement_globals() -> None:
    closing_engine = _BlockingEngine()
    closing_factory = object()
    replacement_engine = _BlockingEngine()
    replacement_factory = object()
    previous_engine = engine_mod._engine
    previous_factory = engine_mod._session_factory
    task: asyncio.Task[None] | None = None

    try:
        engine_mod._engine = closing_engine
        engine_mod._session_factory = closing_factory
        task = asyncio.create_task(engine_mod.close_engine())
        await asyncio.wait_for(closing_engine.dispose_started.wait(), timeout=1)

        engine_mod._engine = replacement_engine
        engine_mod._session_factory = replacement_factory
        closing_engine.allow_dispose.set()
        await task

        assert closing_engine.dispose_finished.is_set()
        assert engine_mod._engine is replacement_engine
        assert engine_mod._session_factory is replacement_factory
    finally:
        closing_engine.allow_dispose.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        engine_mod._engine = previous_engine
        engine_mod._session_factory = previous_factory

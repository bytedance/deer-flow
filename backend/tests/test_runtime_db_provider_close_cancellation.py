import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from deerflow.runtime.checkpointer import async_provider as checkpointer_provider
from deerflow.runtime.store import async_provider as store_provider


class _BlockingAsyncContext:
    def __init__(self, value=None) -> None:
        self.value = self if value is None else value
        self.exit_started = asyncio.Event()
        self.allow_exit = asyncio.Event()
        self.exit_finished = asyncio.Event()

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.exit_started.set()
        await self.allow_exit.wait()
        self.exit_finished.set()
        return False


class _SetupResource:
    serde = object()

    async def setup(self) -> None:
        return None


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs) -> None:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


async def _assert_context_exit_is_drained(cm, resource: _BlockingAsyncContext) -> None:
    entered = asyncio.Event()
    leave = asyncio.Event()

    async def owner() -> None:
        async with cm:
            entered.set()
            await leave.wait()

    task: asyncio.Task[None] | None = None
    try:
        task = asyncio.create_task(owner())
        await asyncio.wait_for(entered.wait(), timeout=1)
        leave.set()
        await asyncio.wait_for(resource.exit_started.wait(), timeout=1)

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "provider teardown returned before backend __aexit__ finished"

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation interrupted backend __aexit__"

        resource.allow_exit.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert resource.exit_finished.is_set()
    finally:
        resource.allow_exit.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("unified", [False, True])
async def test_sqlite_checkpointer_context_exit_drains_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch, unified: bool) -> None:
    resource = _BlockingAsyncContext(_SetupResource())

    class _FakeAsyncSqliteSaver:
        @classmethod
        def from_conn_string(cls, _conn_str: str):
            return resource

    _install_module(
        monkeypatch,
        "langgraph.checkpoint.sqlite.aio",
        AsyncSqliteSaver=_FakeAsyncSqliteSaver,
    )

    if unified:
        config = SimpleNamespace(backend="sqlite", checkpointer_sqlite_path=":memory:")
        cm = checkpointer_provider._async_checkpointer_from_database(config)
    else:
        config = SimpleNamespace(type="sqlite", connection_string=":memory:")
        cm = checkpointer_provider._async_checkpointer(config)

    await _assert_context_exit_is_drained(cm, resource)


@pytest.mark.asyncio
@pytest.mark.parametrize("unified", [False, True])
async def test_postgres_checkpointer_context_exit_drains_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch, unified: bool) -> None:
    resource = _BlockingAsyncContext()

    class _FakeAsyncPostgresSaver(_SetupResource):
        def __init__(self, *, conn) -> None:
            assert conn is resource

    monkeypatch.setattr(checkpointer_provider, "_build_postgres_pool", lambda *_args, **_kwargs: resource)
    monkeypatch.setattr(
        checkpointer_provider,
        "_ensure_postgres_imports",
        lambda: (_FakeAsyncPostgresSaver, object()),
    )

    async def _no_schema(_pool, _schema: str) -> None:
        return None

    monkeypatch.setattr(checkpointer_provider, "_ensure_postgres_schema_with_pool", _no_schema)

    if unified:
        config = SimpleNamespace(backend="postgres", postgres_url="postgresql://example/db", postgres_schema="")
        cm = checkpointer_provider._async_checkpointer_from_database(config)
    else:
        config = SimpleNamespace(type="postgres", connection_string="postgresql://example/db", postgres_schema="")
        cm = checkpointer_provider._async_checkpointer(config)

    await _assert_context_exit_is_drained(cm, resource)


@pytest.mark.asyncio
async def test_sqlite_store_context_exit_drains_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    resource = _BlockingAsyncContext(_SetupResource())

    class _FakeAsyncSqliteStore:
        @classmethod
        def from_conn_string(cls, _conn_str: str):
            return resource

    _install_module(
        monkeypatch,
        "langgraph.store.sqlite.aio",
        AsyncSqliteStore=_FakeAsyncSqliteStore,
    )
    config = SimpleNamespace(type="sqlite", connection_string=":memory:")

    await _assert_context_exit_is_drained(store_provider._async_store(config), resource)


@pytest.mark.asyncio
async def test_postgres_store_context_exit_drains_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    resource = _BlockingAsyncContext(_SetupResource())

    class _FakeAsyncPostgresStore:
        @classmethod
        def from_conn_string(cls, _conn_str: str):
            return resource

    _install_module(
        monkeypatch,
        "langgraph.store.postgres.aio",
        AsyncPostgresStore=_FakeAsyncPostgresStore,
    )

    async def _no_schema(_conn_string: str, _schema: str) -> None:
        return None

    monkeypatch.setattr(store_provider, "_ensure_postgres_schema", _no_schema)
    config = SimpleNamespace(
        type="postgres",
        connection_string="postgresql://example/db",
        postgres_schema="",
    )

    await _assert_context_exit_is_drained(store_provider._async_store(config), resource)

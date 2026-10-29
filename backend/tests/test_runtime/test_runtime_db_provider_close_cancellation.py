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


class _PoolConnection(_BlockingAsyncContext):
    """A pool connection whose exit blocks until the test allows it."""

    def __init__(self) -> None:
        super().__init__()
        self.executed: list[str] = []

    async def execute(self, statement: str) -> None:
        self.executed.append(statement)


class _FakePool:
    """A pool that records being closed while a connection is checked out."""

    def __init__(self, connection: _PoolConnection) -> None:
        self._connection = connection
        self.closed_with_checked_out_connection = False

    def connection(self) -> _PoolConnection:
        return self._connection

    async def __aenter__(self) -> "_FakePool":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if not self._connection.exit_finished.is_set():
            self.closed_with_checked_out_connection = True
        return False


@pytest.mark.asyncio
async def test_ensure_postgres_schema_drains_pool_connection_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The schema-setup connection must return to the pool before the pool drains.

    ``_ensure_postgres_schema_with_pool`` runs inside the drained pool context.
    With a raw ``async with pool.connection()``, caller cancellation arriving
    while the connection's ``__aexit__`` is blocked interrupts that exit, so the
    connection is never returned and the pool's own drained teardown closes
    with a checked-out connection — the backend-ownership invariant in
    ``runtime/AGENTS.md``.
    """
    monkeypatch.setattr(checkpointer_provider, "create_schema_sql", lambda schema: f'CREATE SCHEMA "{schema}"')
    connection = _PoolConnection()
    pool = _FakePool(connection)

    async def owner() -> None:
        async with checkpointer_provider.drained_async_context(pool):
            await checkpointer_provider._ensure_postgres_schema_with_pool(pool, "custom")

    task = asyncio.create_task(owner())
    await asyncio.wait_for(connection.exit_started.wait(), timeout=1)
    assert connection.executed == ['CREATE SCHEMA "custom"']

    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done(), "pool teardown returned before the connection exit finished"

    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done(), "repeated cancellation interrupted the connection exit"

    connection.allow_exit.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not pool.closed_with_checked_out_connection, "pool closed with a checked-out connection"

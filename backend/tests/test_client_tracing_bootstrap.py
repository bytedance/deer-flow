"""Embedded durable tracing owns schema bootstrap without a Gateway lifecycle."""

import asyncio
import concurrent.futures
import sqlite3

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def embedded_config(tmp_path, monkeypatch):
    from langsmith.utils import get_env_var

    import deerflow.client as client_module
    import deerflow.config.app_config as config_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.credentials_key import reset_credentials_cipher
    from deerflow.config.tracing_config import reset_tracing_config

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "unused.yaml"))
    monkeypatch.setenv("DEER_FLOW_CREDENTIALS_KEY", Fernet.generate_key().decode())
    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.setenv(name, "false")
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path / "fresh" / "data")}})
    monkeypatch.setattr(client_module, "get_app_config", lambda: config)
    monkeypatch.setattr(config_module, "get_app_config", lambda: config)
    get_env_var.cache_clear()
    reset_credentials_cipher()
    reset_tracing_config()
    try:
        yield config
    finally:
        get_env_var.cache_clear()
        reset_credentials_cipher()
        reset_tracing_config()


@pytest.fixture
def offline_turn(monkeypatch):
    from deerflow.client import DeerFlowClient, StreamEvent
    from deerflow.tracing.scoped import get_current_snapshot

    snapshots = []

    def turn(self, message, **kwargs):
        snapshot = get_current_snapshot()
        snapshots.append(snapshot)
        yield StreamEvent(type="end", data={"snapshot_id": snapshot.snapshot_id if snapshot else None})

    monkeypatch.setattr(DeerFlowClient, "_stream_turn", turn)
    return snapshots


def _assert_authority_ready(config, expected_snapshots):
    with sqlite3.connect(config.database.sqlite_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0047_tracing_profiles",)
        assert connection.execute("SELECT id FROM tracing_admission_fence").fetchall() == [(1,)]
        assert connection.execute("SELECT count(*) FROM run_tracing_snapshots").fetchone() == (expected_snapshots,)


def test_fresh_sqlite_bootstraps_before_zero_export_embedded_turn(embedded_config, offline_turn, monkeypatch):
    from deerflow.client import DeerFlowClient
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import resolve_run_snapshot

    client = DeerFlowClient()
    assert list(client.stream("offline", user_id="alice"))[0].type == "end"
    snapshot = offline_turn[0]
    assert snapshot.mode == "inherit" and snapshot.providers == () and snapshot.monocle_enabled is False
    _assert_authority_ready(embedded_config, 1)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-only-never-export")
    reset_tracing_config()
    restored = resolve_run_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id, app_config=embedded_config)
    assert restored == snapshot
    assert restored.providers == ()


def test_embedded_bootstrap_migrates_existing_sqlite_from_0046(embedded_config, offline_turn):
    from pathlib import Path

    from alembic import command
    from sqlalchemy.ext.asyncio import create_async_engine

    from deerflow.client import DeerFlowClient
    from deerflow.persistence.bootstrap import _get_alembic_config

    Path(embedded_config.database.sqlite_dir).mkdir(parents=True)

    async def seed():
        engine = create_async_engine(embedded_config.database.app_sqlalchemy_url)
        try:
            await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0046_skill_mutations")
        finally:
            await engine.dispose()

    asyncio.run(seed())
    with sqlite3.connect(embedded_config.database.sqlite_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0046_skill_mutations",)
    assert list(DeerFlowClient().stream("offline"))[0].type == "end"
    _assert_authority_ready(embedded_config, 1)


def test_memory_embedded_turn_does_not_bootstrap_sql(embedded_config, offline_turn, monkeypatch):
    import deerflow.persistence.engine as engine_module
    from deerflow.client import DeerFlowClient

    embedded_config.database.backend = "memory"

    def unexpected_sql(*args, **kwargs):
        pytest.fail("memory mode must not create a SQL engine")

    monkeypatch.setattr(engine_module, "create_async_engine", unexpected_sql)
    assert list(DeerFlowClient().stream("offline"))[0].data == {"snapshot_id": None}
    assert offline_turn == [None]


def test_embedded_bootstrap_preserves_gateway_engine_and_supports_repeated_turns(embedded_config, offline_turn, monkeypatch):
    import deerflow.persistence.engine as engine_module
    from deerflow.client import DeerFlowClient

    gateway_engine, gateway_sessions = object(), object()
    monkeypatch.setattr(engine_module, "_engine", gateway_engine)
    monkeypatch.setattr(engine_module, "_session_factory", gateway_sessions)
    client = DeerFlowClient()
    for _ in range(2):
        assert list(client.stream("offline"))[0].type == "end"
    assert engine_module.get_engine() is gateway_engine
    assert engine_module.get_session_factory() is gateway_sessions
    _assert_authority_ready(embedded_config, 2)


@pytest.mark.asyncio
async def test_sync_embedded_bootstrap_can_run_inside_existing_event_loop(embedded_config, offline_turn):
    from deerflow.client import DeerFlowClient

    assert list(DeerFlowClient().stream("offline"))[0].type == "end"
    _assert_authority_ready(embedded_config, 1)


@pytest.mark.parametrize("shared_client", [False, True])
def test_concurrent_embedded_clients_bootstrap_one_sqlite_authority(embedded_config, offline_turn, monkeypatch, shared_client):
    from deerflow.client import DeerFlowClient
    from deerflow.persistence import bootstrap

    original_bootstrap, bootstrapped = bootstrap.bootstrap_schema, []

    async def record_bootstrap(engine, **kwargs):
        bootstrapped.append(engine)
        await original_bootstrap(engine, **kwargs)

    monkeypatch.setattr(bootstrap, "bootstrap_schema", record_bootstrap)
    clients = [DeerFlowClient()] * 4 if shared_client else [DeerFlowClient() for _ in range(4)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda client: list(client.stream("offline")), clients))
    assert all(events[0].type == "end" for events in results)
    assert len({snapshot.snapshot_id for snapshot in offline_turn}) == 4
    if shared_client:
        assert len(bootstrapped) == 1
    _assert_authority_ready(embedded_config, 4)


def test_failed_embedded_bootstrap_disposes_engine_and_retries_same_client(embedded_config, offline_turn, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine

    from deerflow.client import DeerFlowClient
    from deerflow.persistence import bootstrap

    original_bootstrap, original_dispose = bootstrap.bootstrap_schema, AsyncEngine.dispose
    created, disposed = [], []

    async def fail_first(engine, **kwargs):
        created.append(engine)
        if len(created) == 1:
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT 1")) == 1
            raise RuntimeError("bootstrap test failure")
        await original_bootstrap(engine, **kwargs)

    async def dispose(engine, *args, **kwargs):
        await original_dispose(engine, *args, **kwargs)
        if engine in created:
            disposed.append(engine)

    monkeypatch.setattr(bootstrap, "bootstrap_schema", fail_first)
    monkeypatch.setattr(AsyncEngine, "dispose", dispose)
    client = DeerFlowClient()
    with pytest.raises(RuntimeError, match="bootstrap test failure"):
        list(client.stream("offline"))
    assert offline_turn == []
    assert disposed == created
    assert list(client.stream("offline"))[0].type == "end"
    assert disposed == created and len(created) == 2
    _assert_authority_ready(embedded_config, 1)


@pytest.mark.asyncio
async def test_cancelled_temporary_bootstrap_drains_engine_disposal(embedded_config, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine

    from deerflow.persistence import bootstrap
    from deerflow.persistence.engine import bootstrap_schema_from_config

    bootstrap_started, disposal_started, allow_disposal = asyncio.Event(), asyncio.Event(), asyncio.Event()
    disposed = []
    original_dispose = AsyncEngine.dispose

    async def pause_bootstrap(engine, **kwargs):
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
        bootstrap_started.set()
        await asyncio.Event().wait()

    async def pause_dispose(engine, *args, **kwargs):
        disposal_started.set()
        await allow_disposal.wait()
        await original_dispose(engine, *args, **kwargs)
        disposed.append(engine)

    monkeypatch.setattr(bootstrap, "bootstrap_schema", pause_bootstrap)
    monkeypatch.setattr(AsyncEngine, "dispose", pause_dispose)
    task = asyncio.create_task(bootstrap_schema_from_config(embedded_config.database))
    try:
        await asyncio.wait_for(bootstrap_started.wait(), 5)
        task.cancel()
        await asyncio.wait_for(disposal_started.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        allow_disposal.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(disposed) == 1


@pytest.mark.asyncio
async def test_temporary_postgres_bootstrap_pins_schema_and_disposes_on_failure(embedded_config, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from deerflow.persistence import bootstrap
    from deerflow.persistence import engine as engine_module

    config = embedded_config.database.model_copy(update={"backend": "postgres", "postgres_url": "postgresql://test:test@localhost/test", "postgres_schema": "embedded_test"})
    options, statements = {}, []

    class Engine:
        dispose = AsyncMock()

        @asynccontextmanager
        async def begin(self):
            yield self

        async def execute(self, statement):
            statements.append(str(statement))

    engine = Engine()

    def create(url, **kwargs):
        assert url == "postgresql+asyncpg://test:test@localhost/test"
        options.update(kwargs)
        return engine

    async def fail(instance, **kwargs):
        assert instance is engine
        assert kwargs == {"backend": "postgres", "postgres_schema": "embedded_test"}
        raise RuntimeError("migration rejected")

    monkeypatch.setattr(engine_module, "create_async_engine", create)
    monkeypatch.setattr(bootstrap, "bootstrap_schema", fail)
    with pytest.raises(RuntimeError, match="migration rejected"):
        await engine_module.bootstrap_schema_from_config(config)
    assert options["connect_args"] == {"server_settings": {"search_path": "embedded_test"}, "command_timeout": config.command_timeout}
    assert statements == ["CREATE SCHEMA IF NOT EXISTS embedded_test"]
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_temporary_postgres_bootstrap_rebuild_preserves_schema_and_pool_options(embedded_config, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from deerflow.persistence import bootstrap
    from deerflow.persistence import engine as engine_module

    config = embedded_config.database.model_copy(update={"backend": "postgres", "postgres_url": "postgresql://test:test@localhost/test", "postgres_schema": "embedded_test", "pool_size": 12, "pool_recycle": 80, "command_timeout": 45})
    options = []

    class Engine:
        def __init__(self):
            self.dispose = AsyncMock()
            self.statements = []

        @asynccontextmanager
        async def begin(self):
            yield self

        async def execute(self, statement):
            self.statements.append(str(statement))

    initial, retried = Engine(), Engine()
    engines = iter([initial, retried])

    def create(url, **kwargs):
        assert url == config.app_sqlalchemy_url
        options.append(kwargs)
        return next(engines)

    prepare = AsyncMock(side_effect=[RuntimeError("database does not exist"), None])
    create_database = AsyncMock()
    monkeypatch.setattr(engine_module, "create_async_engine", create)
    monkeypatch.setattr(engine_module, "_auto_create_postgres_db", create_database)
    monkeypatch.setattr(bootstrap, "bootstrap_schema", prepare)
    await engine_module.bootstrap_schema_from_config(config)

    assert len(options) == 2 and options[0] == options[1]
    assert options[1]["connect_args"] == {"server_settings": {"search_path": "embedded_test"}, "command_timeout": 45}
    assert options[1]["pool_size"] == 12 and options[1]["pool_recycle"] == 80 and options[1]["pool_pre_ping"] is True
    assert initial.statements == retried.statements == ["CREATE SCHEMA IF NOT EXISTS embedded_test"]
    create_database.assert_awaited_once_with(config.app_sqlalchemy_url)
    assert [call.args[0] for call in prepare.await_args_list] == [initial, retried]
    assert all(call.kwargs == {"backend": "postgres", "postgres_schema": "embedded_test"} for call in prepare.await_args_list)
    initial.dispose.assert_awaited_once()
    retried.dispose.assert_awaited_once()

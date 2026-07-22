"""Tests for hardened PostgreSQL async engine configuration."""

from __future__ import annotations

import asyncio
import sys
from time import monotonic
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence import engine as engine_mod


def test_postgres_engine_kwargs_include_connection_hardening() -> None:
    kwargs = engine_mod._postgres_engine_kwargs(echo=False, pool_size=5)

    assert kwargs["echo"] is False
    assert kwargs["pool_size"] == 5
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == engine_mod.POSTGRES_POOL_RECYCLE_SECONDS
    assert kwargs["connect_args"]["command_timeout"] == engine_mod.POSTGRES_COMMAND_TIMEOUT_SECONDS
    assert kwargs["json_serializer"] is engine_mod._json_serializer


def test_database_command_timeout_defaults_to_30_seconds() -> None:
    config = DatabaseConfig()

    assert config.command_timeout == 30


def test_database_pool_recycle_defaults_to_300_seconds() -> None:
    config = DatabaseConfig()

    assert config.pool_recycle == 300


def test_postgres_engine_kwargs_preserve_caller_values() -> None:
    kwargs = engine_mod._postgres_engine_kwargs(echo=True, pool_size=20, pool_recycle=120, command_timeout=90)

    assert kwargs["echo"] is True
    assert kwargs["pool_size"] == 20
    assert kwargs["pool_recycle"] == 120
    assert kwargs["connect_args"] == {"command_timeout": 90}


def test_postgres_engine_kwargs_allow_command_timeout_opt_out() -> None:
    config = DatabaseConfig(command_timeout=None)
    kwargs = engine_mod._postgres_engine_kwargs(echo=False, pool_size=5, command_timeout=config.command_timeout)

    assert config.command_timeout is None
    assert kwargs["connect_args"] == {}


@pytest.mark.asyncio
async def test_configured_command_timeout_ends_stalled_command() -> None:
    config = DatabaseConfig(
        backend="postgres",
        postgres_url="postgresql://user:password@localhost/deerflow",
        command_timeout=0.01,
    )

    class _StalledAsyncpgEngine:
        def __init__(self, command_timeout: float) -> None:
            self.command_timeout = command_timeout

        async def checkout(self) -> None:
            async with asyncio.timeout(self.command_timeout):
                await asyncio.Event().wait()

        async def dispose(self) -> None:
            return None

    def _create_engine(_url: str, **kwargs) -> _StalledAsyncpgEngine:
        assert kwargs["pool_pre_ping"] is True
        return _StalledAsyncpgEngine(kwargs["connect_args"]["command_timeout"])

    bootstrap_schema = AsyncMock()

    with (
        patch.dict(sys.modules, {"asyncpg": ModuleType("asyncpg")}),
        patch.object(engine_mod, "create_async_engine", side_effect=_create_engine),
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch("deerflow.persistence.bootstrap.bootstrap_schema", new=bootstrap_schema),
    ):
        try:
            await engine_mod.init_engine_from_config(config)
            engine = engine_mod.get_engine()
            assert isinstance(engine, _StalledAsyncpgEngine)
            started_at = monotonic()
            with pytest.raises(TimeoutError):
                await engine.checkout()
            elapsed = monotonic() - started_at

            assert engine.command_timeout == config.command_timeout
            assert elapsed < 1
        finally:
            await engine_mod.close_engine()


@pytest.mark.asyncio
async def test_init_engine_from_config_preserves_longer_command_timeout_override() -> None:
    config = DatabaseConfig(
        backend="postgres",
        postgres_url="postgresql://user:password@localhost/deerflow",
        pool_recycle=120,
        command_timeout=90,
    )
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    bootstrap_schema = AsyncMock()

    with (
        patch.dict(sys.modules, {"asyncpg": ModuleType("asyncpg")}),
        patch.object(engine_mod, "create_async_engine", return_value=mock_engine) as create_engine,
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch("deerflow.persistence.bootstrap.bootstrap_schema", new=bootstrap_schema),
    ):
        try:
            await engine_mod.init_engine_from_config(config)

            kwargs = create_engine.call_args.kwargs
            assert kwargs["connect_args"]["command_timeout"] == 90
            assert kwargs["pool_recycle"] == 120
        finally:
            await engine_mod.close_engine()


@pytest.mark.asyncio
async def test_init_engine_postgres_uses_hardened_kwargs() -> None:
    url = "postgresql+asyncpg://user:password@localhost/deerflow"
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    bootstrap_schema = AsyncMock()

    with (
        patch.dict(sys.modules, {"asyncpg": ModuleType("asyncpg")}),
        patch.object(engine_mod, "create_async_engine", return_value=mock_engine) as create_engine,
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch("deerflow.persistence.bootstrap.bootstrap_schema", new=bootstrap_schema),
    ):
        try:
            await engine_mod.init_engine(backend="postgres", url=url, echo=True, pool_size=12)

            create_engine.assert_called_once_with(url, **engine_mod._postgres_engine_kwargs(echo=True, pool_size=12))
            bootstrap_schema.assert_awaited_once_with(mock_engine, backend="postgres")
        finally:
            await engine_mod.close_engine()


@pytest.mark.asyncio
async def test_init_engine_postgres_retry_uses_hardened_kwargs() -> None:
    url = "postgresql+asyncpg://user:password@localhost/deerflow"
    initial_engine = MagicMock()
    initial_engine.dispose = AsyncMock()
    retry_engine = MagicMock()
    retry_engine.dispose = AsyncMock()
    bootstrap_schema = AsyncMock(side_effect=[Exception("database does not exist"), None])
    auto_create = AsyncMock()

    with (
        patch.dict(sys.modules, {"asyncpg": ModuleType("asyncpg")}),
        patch.object(engine_mod, "create_async_engine", side_effect=[initial_engine, retry_engine]) as create_engine,
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch.object(engine_mod, "_auto_create_postgres_db", new=auto_create),
        patch("deerflow.persistence.bootstrap.bootstrap_schema", new=bootstrap_schema),
    ):
        try:
            await engine_mod.init_engine(backend="postgres", url=url, echo=False, pool_size=8)

            kwargs = engine_mod._postgres_engine_kwargs(echo=False, pool_size=8)
            assert create_engine.call_args_list == [call(url, **kwargs), call(url, **kwargs)]
            auto_create.assert_awaited_once_with(url)
            initial_engine.dispose.assert_awaited_once()
            assert bootstrap_schema.await_args_list == [call(initial_engine, backend="postgres"), call(retry_engine, backend="postgres")]
        finally:
            await engine_mod.close_engine()


@pytest.mark.asyncio
async def test_init_engine_sqlite_omits_postgres_kwargs_and_keeps_wal_listener(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'deerflow.db'}"
    mock_engine = MagicMock()
    mock_engine.sync_engine = object()
    mock_engine.dispose = AsyncMock()
    bootstrap_schema = AsyncMock()
    registered: dict[str, object] = {}

    def _capture_listener(target, event_name):
        assert target is mock_engine.sync_engine
        assert event_name == "connect"

        def _decorator(fn):
            registered["listener"] = fn
            return fn

        return _decorator

    with (
        patch.object(engine_mod, "create_async_engine", return_value=mock_engine) as create_engine,
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch("sqlalchemy.event.listens_for", new=_capture_listener),
        patch("deerflow.persistence.bootstrap.bootstrap_schema", new=bootstrap_schema),
    ):
        try:
            await engine_mod.init_engine(backend="sqlite", url=url, echo=True, sqlite_dir=str(tmp_path))

            create_engine.assert_called_once_with(url, echo=True, json_serializer=engine_mod._json_serializer)

            cursor = MagicMock()
            dbapi_connection = MagicMock()
            dbapi_connection.cursor.return_value = cursor
            listener = registered["listener"]
            listener(dbapi_connection, None)
            assert [entry.args[0] for entry in cursor.execute.call_args_list] == [
                "PRAGMA journal_mode=WAL;",
                "PRAGMA synchronous=NORMAL;",
                "PRAGMA foreign_keys=ON;",
                "PRAGMA busy_timeout=30000;",
            ]
            cursor.close.assert_called_once_with()
        finally:
            await engine_mod.close_engine()

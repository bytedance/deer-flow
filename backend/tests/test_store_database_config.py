"""Store factories should follow unified database persistence config."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import deerflow.config.app_config as app_config_module
from deerflow.config.checkpointer_config import set_checkpointer_config
from deerflow.config.database_config import DatabaseConfig
from deerflow.runtime.store.provider import reset_store


@pytest.fixture(autouse=True)
def reset_store_state():
    app_config_module._app_config = None
    set_checkpointer_config(None)
    reset_store()
    yield
    app_config_module._app_config = None
    set_checkpointer_config(None)
    reset_store()


def _mock_app_config(database: DatabaseConfig):
    config = MagicMock()
    config.checkpointer = None
    config.database = database
    return config


@pytest.mark.anyio
async def test_async_make_store_uses_unified_sqlite_database_config(tmp_path):
    from deerflow.runtime.store.async_provider import make_store

    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    config = _mock_app_config(database)

    mock_store = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_store
    mock_cm.__aexit__.return_value = False

    mock_store_cls = MagicMock()
    mock_store_cls.from_conn_string.return_value = mock_cm
    mock_module = MagicMock()
    mock_module.AsyncSqliteStore = mock_store_cls

    with (
        patch.dict(sys.modules, {"langgraph.store.sqlite.aio": mock_module}),
        patch("deerflow.runtime.store.async_provider.ensure_sqlite_parent_dir") as mock_ensure,
    ):
        async with make_store(config) as store:
            assert store is mock_store

    mock_ensure.assert_called_once_with(database.sqlite_path)
    mock_store_cls.from_conn_string.assert_called_once_with(database.sqlite_path)
    mock_store.setup.assert_awaited_once()


def test_store_context_uses_unified_sqlite_database_config(tmp_path):
    from deerflow.runtime.store.provider import store_context

    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    config = _mock_app_config(database)

    mock_store = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_store
    mock_cm.__exit__.return_value = False

    mock_store_cls = MagicMock()
    mock_store_cls.from_conn_string.return_value = mock_cm
    mock_module = MagicMock()
    mock_module.SqliteStore = mock_store_cls

    with (
        patch("deerflow.runtime.store.provider.get_app_config", return_value=config),
        patch.dict(sys.modules, {"langgraph.store.sqlite": mock_module}),
        patch("deerflow.runtime.store.provider.ensure_sqlite_parent_dir") as mock_ensure,
    ):
        with store_context() as store:
            assert store is mock_store

    mock_ensure.assert_called_once_with(database.sqlite_path)
    mock_store_cls.from_conn_string.assert_called_once_with(database.sqlite_path)
    mock_store.setup.assert_called_once()


def test_get_store_uses_unified_postgres_database_config():
    from deerflow.runtime.store.provider import get_store

    database = DatabaseConfig(
        backend="postgres",
        postgres_url="postgresql://user:pass@localhost:5432/deerflow",
    )
    config = _mock_app_config(database)

    mock_store = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_store
    mock_cm.__exit__.return_value = False

    mock_store_cls = MagicMock()
    mock_store_cls.from_conn_string.return_value = mock_cm
    mock_module = MagicMock()
    mock_module.PostgresStore = mock_store_cls

    with (
        patch("deerflow.runtime.store.provider.get_app_config", return_value=config),
        patch.dict(sys.modules, {"langgraph.store.postgres": mock_module}),
    ):
        store = get_store()

    assert store is mock_store
    mock_store_cls.from_conn_string.assert_called_once_with(database.postgres_url)
    mock_store.setup.assert_called_once()

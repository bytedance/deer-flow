"""Regression coverage for unified database fallback in checkpointer/store factories."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

import deerflow.config.app_config as app_config_module
from deerflow.config.app_config import AppConfig
from deerflow.config.checkpointer_config import CheckpointerConfig, set_checkpointer_config
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime.checkpointer import checkpointer_context, get_checkpointer, reset_checkpointer
from deerflow.runtime.store import get_store, reset_store, store_context


@pytest.fixture(autouse=True)
def reset_state():
    app_config_module._app_config = None
    set_checkpointer_config(None)
    reset_checkpointer()
    reset_store()
    yield
    app_config_module._app_config = None
    set_checkpointer_config(None)
    reset_checkpointer()
    reset_store()


def _app_config_with_database(database: DatabaseConfig) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="test"), database=database, checkpointer=None)


def _app_config_with_legacy_checkpointer(database: DatabaseConfig, checkpointer: CheckpointerConfig) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="test"), database=database, checkpointer=checkpointer)


def test_sync_checkpointer_and_store_use_database_sqlite_when_legacy_checkpointer_absent(tmp_path):
    config = _app_config_with_database(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    app_config_module._app_config = config

    saver_instance = MagicMock(name="sqlite_saver")
    saver_cm = MagicMock()
    saver_cm.__enter__ = MagicMock(return_value=saver_instance)
    saver_cm.__exit__ = MagicMock(return_value=False)
    saver_cls = MagicMock()
    saver_cls.from_conn_string = MagicMock(return_value=saver_cm)
    saver_module = MagicMock(SqliteSaver=saver_cls)

    store_instance = MagicMock(name="sqlite_store")
    store_cm = MagicMock()
    store_cm.__enter__ = MagicMock(return_value=store_instance)
    store_cm.__exit__ = MagicMock(return_value=False)
    store_cls = MagicMock()
    store_cls.from_conn_string = MagicMock(return_value=store_cm)
    store_module = MagicMock(SqliteStore=store_cls)

    with patch.dict(
        sys.modules,
        {
            "langgraph.checkpoint.sqlite": saver_module,
            "langgraph.store.sqlite": store_module,
        },
    ):
        assert get_checkpointer() is saver_instance
        assert get_store() is store_instance

    saver_cls.from_conn_string.assert_called_once_with(config.database.sqlite_path)
    store_cls.from_conn_string.assert_called_once_with(config.database.sqlite_path)
    saver_instance.setup.assert_called_once()
    store_instance.setup.assert_called_once()


def test_sync_database_postgres_requires_database_postgres_url():
    app_config_module._app_config = _app_config_with_database(DatabaseConfig(backend="postgres", postgres_url=""))

    with pytest.raises(ValueError, match="database.postgres_url"):
        get_checkpointer()

    with pytest.raises(ValueError, match="database.postgres_url"):
        get_store()


def test_sync_checkpointer_and_store_use_database_postgres_when_legacy_checkpointer_absent():
    config = _app_config_with_database(DatabaseConfig(backend="postgres", postgres_url="postgresql://localhost/deerflow"))
    app_config_module._app_config = config

    saver_instance = MagicMock(name="postgres_saver")
    saver_cm = MagicMock()
    saver_cm.__enter__ = MagicMock(return_value=saver_instance)
    saver_cm.__exit__ = MagicMock(return_value=False)
    saver_cls = MagicMock()
    saver_cls.from_conn_string = MagicMock(return_value=saver_cm)
    saver_module = MagicMock(PostgresSaver=saver_cls)

    store_instance = MagicMock(name="postgres_store")
    store_cm = MagicMock()
    store_cm.__enter__ = MagicMock(return_value=store_instance)
    store_cm.__exit__ = MagicMock(return_value=False)
    store_cls = MagicMock()
    store_cls.from_conn_string = MagicMock(return_value=store_cm)
    store_module = MagicMock(PostgresStore=store_cls)

    with patch.dict(
        sys.modules,
        {
            "langgraph.checkpoint.postgres": saver_module,
            "langgraph.store.postgres": store_module,
        },
    ):
        assert get_checkpointer() is saver_instance
        assert get_store() is store_instance

    saver_cls.from_conn_string.assert_called_once_with(config.database.postgres_url)
    store_cls.from_conn_string.assert_called_once_with(config.database.postgres_url)
    saver_instance.setup.assert_called_once()
    store_instance.setup.assert_called_once()


def test_legacy_checkpointer_takes_precedence_over_database_postgres(tmp_path):
    legacy_path = tmp_path / "legacy.db"
    config = _app_config_with_legacy_checkpointer(
        DatabaseConfig(backend="postgres", postgres_url="postgresql://localhost/deerflow"),
        CheckpointerConfig(type="sqlite", connection_string=str(legacy_path)),
    )
    app_config_module._app_config = config
    set_checkpointer_config(config.checkpointer)

    saver_instance = MagicMock(name="legacy_sqlite_saver")
    saver_cm = MagicMock()
    saver_cm.__enter__ = MagicMock(return_value=saver_instance)
    saver_cm.__exit__ = MagicMock(return_value=False)
    saver_cls = MagicMock()
    saver_cls.from_conn_string = MagicMock(return_value=saver_cm)
    saver_module = MagicMock(SqliteSaver=saver_cls)

    store_instance = MagicMock(name="legacy_sqlite_store")
    store_cm = MagicMock()
    store_cm.__enter__ = MagicMock(return_value=store_instance)
    store_cm.__exit__ = MagicMock(return_value=False)
    store_cls = MagicMock()
    store_cls.from_conn_string = MagicMock(return_value=store_cm)
    store_module = MagicMock(SqliteStore=store_cls)

    postgres_saver_module = MagicMock()
    postgres_store_module = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "langgraph.checkpoint.sqlite": saver_module,
            "langgraph.store.sqlite": store_module,
            "langgraph.checkpoint.postgres": postgres_saver_module,
            "langgraph.store.postgres": postgres_store_module,
        },
    ):
        assert get_checkpointer() is saver_instance
        assert get_store() is store_instance

    saver_cls.from_conn_string.assert_called_once_with(str(legacy_path))
    store_cls.from_conn_string.assert_called_once_with(str(legacy_path))
    assert not postgres_saver_module.PostgresSaver.from_conn_string.called
    assert not postgres_store_module.PostgresStore.from_conn_string.called


def test_explicit_database_memory_logs_info_not_warning(caplog):
    config = _app_config_with_database(DatabaseConfig(backend="memory"))
    app_config_module._app_config = config

    checkpointer_logger = "deerflow.runtime.checkpointer.provider"
    store_logger = "deerflow.runtime.store.provider"

    with caplog.at_level("INFO", logger=checkpointer_logger), caplog.at_level("INFO", logger=store_logger):
        assert isinstance(get_checkpointer(), InMemorySaver)
        assert isinstance(get_store(), InMemoryStore)

    warning_records = [record for record in caplog.records if record.levelname == "WARNING"]
    info_messages = [record.getMessage() for record in caplog.records if record.levelname == "INFO"]

    assert warning_records == []
    assert any("Checkpointer: using InMemorySaver" in message for message in info_messages)
    assert any("Store: using InMemoryStore" in message for message in info_messages)


def test_sync_context_managers_use_database_sqlite_when_legacy_checkpointer_absent(tmp_path):
    config = _app_config_with_database(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))

    saver_instance = MagicMock(name="sqlite_saver")
    saver_cm = MagicMock()
    saver_cm.__enter__ = MagicMock(return_value=saver_instance)
    saver_cm.__exit__ = MagicMock(return_value=False)
    saver_cls = MagicMock()
    saver_cls.from_conn_string = MagicMock(return_value=saver_cm)
    saver_module = MagicMock(SqliteSaver=saver_cls)

    store_instance = MagicMock(name="sqlite_store")
    store_cm = MagicMock()
    store_cm.__enter__ = MagicMock(return_value=store_instance)
    store_cm.__exit__ = MagicMock(return_value=False)
    store_cls = MagicMock()
    store_cls.from_conn_string = MagicMock(return_value=store_cm)
    store_module = MagicMock(SqliteStore=store_cls)

    with (
        patch("deerflow.runtime.checkpointer.provider.get_app_config", return_value=config),
        patch("deerflow.runtime.store.provider.get_app_config", return_value=config),
        patch.dict(
            sys.modules,
            {
                "langgraph.checkpoint.sqlite": saver_module,
                "langgraph.store.sqlite": store_module,
            },
        ),
    ):
        with checkpointer_context() as saver:
            assert saver is saver_instance
        with store_context() as store:
            assert store is store_instance

    saver_cls.from_conn_string.assert_called_once_with(config.database.sqlite_path)
    store_cls.from_conn_string.assert_called_once_with(config.database.sqlite_path)


def test_database_change_invalidates_persistence_singletons(tmp_path):
    app_config_module._app_config = _app_config_with_database(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "old")))
    next_config = _app_config_with_database(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "new")))

    with (
        patch("deerflow.runtime.checkpointer.reset_checkpointer") as reset_cp,
        patch("deerflow.runtime.store.reset_store") as reset_store_mock,
    ):
        AppConfig._apply_singleton_configs(next_config, {})

    reset_cp.assert_called_once()
    reset_store_mock.assert_called_once()


@pytest.mark.anyio
async def test_async_make_store_uses_database_sqlite_when_legacy_checkpointer_absent(tmp_path):
    from deerflow.runtime.store.async_provider import make_store

    config = _app_config_with_database(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))

    store_instance = MagicMock(name="async_sqlite_store")
    store_instance.setup = AsyncMock()

    class FakeAsyncSqliteStore:
        @classmethod
        def from_conn_string(cls, conn_string):
            FakeAsyncSqliteStore.conn_string = conn_string
            return cls()

        async def __aenter__(self):
            return store_instance

        async def __aexit__(self, exc_type, exc, tb):
            return False

    store_module = MagicMock(AsyncSqliteStore=FakeAsyncSqliteStore)

    with patch.dict(sys.modules, {"langgraph.store.sqlite.aio": store_module}):
        async with make_store(config) as store:
            assert store is store_instance

    assert FakeAsyncSqliteStore.conn_string == config.database.sqlite_path
    store_instance.setup.assert_awaited_once()

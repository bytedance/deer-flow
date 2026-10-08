"""``auth.local.throttle_storage``: selector semantics and store resolution.

``auto`` (the default) puts failed-login counters in the application database
whenever one exists (``database.backend`` sqlite or postgres), so every
Gateway replica sharing that database enforces one lockout per IP; a
``memory`` database has no shared table and falls back to the per-process
counter. ``memory`` forces the per-process counter; ``db`` forces the table
and degrades to memory with a warning when there is no database to hold it.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pydantic
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth import login_throttle
from deerflow.config.auth_config import LocalAuthConfig, LoginThrottleStorage, resolve_login_throttle_storage
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS, STARTUP_ONLY_PREFIX
from deerflow.persistence.login_throttle import MemoryLoginThrottleStore, SqlLoginThrottleStore


@pytest.fixture(autouse=True)
def _no_installed_store():
    login_throttle.reset_login_throttle_store()
    yield
    login_throttle.reset_login_throttle_store()


@pytest.mark.parametrize(
    ("selector", "database_backend", "expected"),
    [
        ("auto", "sqlite", "db"),
        ("auto", "postgres", "db"),
        ("auto", "memory", "memory"),
        ("auto", None, "memory"),
        ("memory", "postgres", "memory"),
        ("memory", "sqlite", "memory"),
        ("db", "sqlite", "db"),
        ("db", "postgres", "db"),
        ("db", "memory", "memory"),
        (LoginThrottleStorage.AUTO, "sqlite", "db"),
        (LoginThrottleStorage.DB, "memory", "memory"),
    ],
)
def test_resolve_login_throttle_storage(selector, database_backend, expected):
    assert resolve_login_throttle_storage(selector, database_backend) == expected


def test_local_auth_config_selector_defaults_to_auto_and_validates():
    assert LocalAuthConfig().throttle_storage == LoginThrottleStorage.AUTO
    assert LocalAuthConfig(throttle_storage="db").throttle_storage == LoginThrottleStorage.DB
    assert LocalAuthConfig(throttle_storage="memory").throttle_storage == LoginThrottleStorage.MEMORY
    with pytest.raises(pydantic.ValidationError):
        LocalAuthConfig(throttle_storage="redis")


def test_throttle_storage_is_registered_as_startup_only():
    """The store is resolved once at Gateway startup; the policy knobs stay live-read."""
    field_path = "auth.local.throttle_storage"
    assert field_path in STARTUP_ONLY_FIELDS
    description = LocalAuthConfig.model_fields["throttle_storage"].description or ""
    assert description.startswith(STARTUP_ONLY_PREFIX)
    assert STARTUP_ONLY_FIELDS[field_path] in description
    for live_field in ("max_login_attempts", "lockout_seconds"):
        assert not (LocalAuthConfig.model_fields[live_field].description or "").startswith(STARTUP_ONLY_PREFIX)


def _config(selector: str, database_backend: str) -> SimpleNamespace:
    return SimpleNamespace(
        auth=SimpleNamespace(local=LocalAuthConfig(throttle_storage=selector)),
        database=SimpleNamespace(backend=database_backend),
    )


@pytest.fixture
def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'resolver.db'}")
    yield async_sessionmaker(engine, expire_on_commit=False)
    engine.sync_engine.dispose()


def test_auto_with_a_database_resolves_the_sql_store(session_factory, caplog):
    with caplog.at_level(logging.WARNING):
        store = login_throttle.resolve_login_throttle_store(_config("auto", "sqlite"), session_factory=session_factory)
    assert isinstance(store, SqlLoginThrottleStore)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_auto_with_postgres_resolves_the_sql_store(session_factory):
    store = login_throttle.resolve_login_throttle_store(_config("auto", "postgres"), session_factory=session_factory)
    assert isinstance(store, SqlLoginThrottleStore)


def test_auto_with_a_memory_database_resolves_the_memory_store(caplog):
    with caplog.at_level(logging.WARNING):
        store = login_throttle.resolve_login_throttle_store(_config("auto", "memory"), session_factory=None)
    assert isinstance(store, MemoryLoginThrottleStore)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_explicit_memory_ignores_the_database(session_factory):
    store = login_throttle.resolve_login_throttle_store(_config("memory", "postgres"), session_factory=session_factory)
    assert isinstance(store, MemoryLoginThrottleStore)


def test_explicit_db_without_a_database_falls_back_to_memory_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        store = login_throttle.resolve_login_throttle_store(_config("db", "memory"), session_factory=None)
    assert isinstance(store, MemoryLoginThrottleStore)
    assert any("auth.local.throttle_storage=db" in r.message and "database.backend" in r.message for r in caplog.records)


def test_db_resolution_without_an_engine_falls_back_to_memory_and_warns(caplog):
    """A database is configured but no engine was initialised (bare app): never crash the login path."""
    with caplog.at_level(logging.WARNING):
        store = login_throttle.resolve_login_throttle_store(_config("auto", "sqlite"), session_factory=None)
    assert isinstance(store, MemoryLoginThrottleStore)
    assert any("engine" in r.message for r in caplog.records)


def test_missing_config_resolves_the_memory_store():
    assert isinstance(login_throttle.resolve_login_throttle_store(None, session_factory=None), MemoryLoginThrottleStore)


def test_install_and_reset_hooks():
    assert login_throttle.installed_login_throttle_store() is None
    store = MemoryLoginThrottleStore()
    login_throttle.install_login_throttle_store(store)
    assert login_throttle.installed_login_throttle_store() is store
    login_throttle.reset_login_throttle_store()
    assert login_throttle.installed_login_throttle_store() is None


def test_lazy_resolution_uses_live_config_and_installs_once(monkeypatch, session_factory):
    """A bare app (no Gateway lifespan) resolves on first use and keeps that store."""
    from deerflow.config import app_config as app_config_module
    from deerflow.persistence import engine as engine_module

    monkeypatch.setattr(app_config_module, "get_app_config", lambda: _config("auto", "sqlite"))
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: session_factory)
    first = login_throttle.resolve_and_install_from_live_config()
    assert isinstance(first, SqlLoginThrottleStore)
    assert login_throttle.installed_login_throttle_store() is first
    # A second resolver racing the first keeps the already installed store.
    assert login_throttle.resolve_and_install_from_live_config() is first


def test_lazy_resolution_without_config_file_uses_defaults(monkeypatch):
    from deerflow.config import app_config as app_config_module
    from deerflow.persistence import engine as engine_module

    def _missing():
        raise FileNotFoundError("no config.yaml")

    monkeypatch.setattr(app_config_module, "get_app_config", _missing)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    assert isinstance(login_throttle.resolve_and_install_from_live_config(), MemoryLoginThrottleStore)


def test_lazy_resolution_propagates_a_malformed_config(monkeypatch):
    """Like the policy read: a broken config.yaml fails loudly rather than silently picking a store."""
    from deerflow.config import app_config as app_config_module

    def _malformed():
        raise ValueError("config validation error")

    monkeypatch.setattr(app_config_module, "get_app_config", _malformed)
    with pytest.raises(ValueError, match="config validation error"):
        login_throttle.resolve_and_install_from_live_config()
    assert login_throttle.installed_login_throttle_store() is None

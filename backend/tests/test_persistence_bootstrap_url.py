"""Tests for the Postgres URL / ConfigParser pitfalls in ``bootstrap``.

Two failure modes the ``_alembic_safe_url`` helper exists to prevent:

1. ``str(engine.url)`` (and the default ``URL.render_as_string()``) masks the
   password as ``***``. The live engine would still work because it carries
   the password in-memory, but alembic ``stamp`` / ``upgrade`` (which open
   their own connection from the URL we pass in) would authenticate with
   garbage and fail at runtime.
2. ``alembic.config.Config.set_main_option`` forwards to ``ConfigParser.set``,
   which performs ``%(name)s``-style interpolation on the value. A URL-encoded
   password containing ``%`` (e.g. ``p%40ss`` for ``p@ss``) raises
   ``InterpolationSyntaxError``. Every literal ``%`` must be doubled.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.engine.url import make_url

from deerflow.persistence.bootstrap import _alembic_safe_url, _escape_url_for_alembic, _get_alembic_config


def _fake_engine(url: str) -> SimpleNamespace:
    """Build a minimal stand-in for ``AsyncEngine`` so we don't need a real
    driver (e.g. asyncpg) installed just to exercise the URL path."""
    return SimpleNamespace(url=make_url(url))


def test_safe_url_preserves_password_for_postgres() -> None:
    engine = _fake_engine("postgresql://alice:s3cret@db.example.com/app")
    safe = _alembic_safe_url(engine)
    assert "s3cret" in safe, "password got masked: alembic would auth with garbage"
    assert "***" not in safe


def test_safe_url_escapes_percent_for_configparser() -> None:
    # URL-encoded ``@`` in password -> raw ``%40`` in URL -> ConfigParser
    # would treat it as an interpolation marker.
    engine = _fake_engine("postgresql://alice:p%40ss@db.example.com/app")
    safe = _alembic_safe_url(engine)
    assert "p%%40ss" in safe, f"percent not doubled, ConfigParser will fail: {safe}"


def test_alembic_config_accepts_url_with_percent_and_round_trips() -> None:
    # The whole point: build_config should not raise, and the URL alembic
    # reads back should match the original (single ``%``, real password).
    original = "postgresql://alice:p%40ss@db.example.com/app"
    engine = _fake_engine(original)
    cfg = _get_alembic_config(engine)
    roundtrip = cfg.get_main_option("sqlalchemy.url")
    assert roundtrip == original, f"alembic sees a different URL than we set: {roundtrip}"


def test_sqlite_url_does_not_double_percent_unnecessarily() -> None:
    # No percent in the URL -> no escaping needed -> output equals input.
    engine = _fake_engine("sqlite+aiosqlite:///tmp/db.sqlite")
    safe = _alembic_safe_url(engine)
    assert safe == "sqlite+aiosqlite:///tmp/db.sqlite"


def test_escape_url_for_alembic_doubles_only_percent_signs() -> None:
    # Shared helper used by both ``bootstrap._alembic_safe_url`` and
    # ``scripts/_autogen_revision._alembic_config`` -- pins the round-trip
    # rule so any future URL/ConfigParser corner case is fixed in one place.
    assert _escape_url_for_alembic("postgresql://a:p%40ss@h/d") == "postgresql://a:p%%40ss@h/d"
    assert _escape_url_for_alembic("sqlite:///x.db") == "sqlite:///x.db"
    # Idempotency is intentionally NOT a property -- doubling is one-way;
    # callers must escape exactly once on the way into set_main_option.
    assert _escape_url_for_alembic("a%%b") == "a%%%%b"


def test_alembic_config_forwards_postgres_schema_option() -> None:
    # The custom schema must reach env.py so the alembic-spawned engine can
    # pin its search_path; otherwise alembic_version + migration DDL land in
    # ``public`` while the ORM tables land in the custom schema.
    engine = _fake_engine("postgresql://a:b@h/d")
    cfg = _get_alembic_config(engine, postgres_schema="deerflow")
    assert cfg.get_main_option("deerflow_pg_schema") == "deerflow"


def test_alembic_config_omits_schema_option_when_unset() -> None:
    engine = _fake_engine("postgresql://a:b@h/d")
    cfg = _get_alembic_config(engine)
    assert cfg.get_main_option("deerflow_pg_schema") is None


@pytest.mark.parametrize("scheme", ["postgresql+asyncpg", "postgresql", "postgres"])
def test_env_module_pins_search_path_from_schema_option(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    """Behavioral verification on migrations/env.py: run_migrations_online reads
    ``deerflow_pg_schema`` from the Alembic Config and passes the pinned asyncpg
    ``search_path`` connect_args to ``create_async_engine``."""
    import asyncio
    import importlib.util
    from contextlib import asynccontextmanager
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from alembic.config import Config

    from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

    alembic_cfg = Config()
    dsn = f"{scheme}://deerflow:deerflow@localhost:5432/deerflow_test"
    alembic_cfg.set_main_option("sqlalchemy.url", dsn)
    alembic_cfg.set_main_option("deerflow_pg_schema", "tenant_isolated")

    captured: dict[str, object] = {}

    class _FakeAsyncEngine:
        url = make_url(dsn)
        sync_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        @asynccontextmanager
        async def connect(self):
            class _Conn:
                async def run_sync(self, _fn):
                    return None

            yield _Conn()

        async def dispose(self):
            return None

    def _fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured["connect_args"] = kwargs.get("connect_args")
        return _FakeAsyncEngine()

    fake_ctx = MagicMock()
    fake_ctx.config = alembic_cfg
    fake_ctx.is_offline_mode.return_value = True  # avoid running online at import time

    monkeypatch.setattr("alembic.context", fake_ctx)
    env_path = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/persistence/migrations/env.py"
    spec = importlib.util.spec_from_file_location("_test_migrations_env_schema", env_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "create_async_engine", _fake_create_async_engine)

    asyncio.run(mod.run_migrations_online())

    assert captured["url"] == dsn
    assert captured["connect_args"] == build_asyncpg_connect_args("tenant_isolated")

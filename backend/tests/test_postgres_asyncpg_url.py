"""Async ORM URLs preserve TLS requirements without changing libpq consumers."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence import engine as engine_mod


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
@pytest.mark.parametrize("mode", [None, "disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
def test_async_orm_url_preserves_tls_credentials_and_query_options(scheme, mode):
    uri = f"{scheme}://us%40er%3Aname:p%40ss%2Fword%3A%25@localhost:5432/deerflow_test?target_session_attrs=read-write"
    if mode is not None:
        uri += f"&sslmode={mode}"
    config = DatabaseConfig(backend="postgres", postgres_url=uri)
    url = make_url(config.app_sqlalchemy_url)
    _, kwargs = url.get_dialect()().create_connect_args(url)
    assert url.drivername == "postgresql+asyncpg"
    assert kwargs["user"] == "us@er:name"
    assert kwargs["password"] == "p@ss/word:%"
    assert kwargs["target_session_attrs"] == "read-write"
    assert "sslmode" not in kwargs
    if mode is None:
        assert "ssl" not in kwargs
    else:
        assert kwargs["ssl"] == mode
    assert config.postgres_url == uri
    assert make_url(config.app_sync_sqlalchemy_url).query == make_url(uri).query
    assert asyncpg_test_url(uri) == config.app_sqlalchemy_url


@pytest.mark.parametrize("query", ["ssl=require", "ssl=require&sslmode=require"])
def test_explicit_matching_ssl_options_are_preserved(query):
    config = DatabaseConfig(backend="postgres", postgres_url=f"postgresql://user:password@localhost/test?{query}")
    assert make_url(config.app_sqlalchemy_url).query == {"ssl": "require"}


@pytest.mark.parametrize(
    "query",
    [
        "ssl=require&sslmode=disable",
        "sslmode=invalid",
        "sslmode=",
        "ssl=invalid",
        "ssl=",
        "sslmode=require&sslmode=disable",
        "ssl=require&ssl=disable",
        "channel_binding=require",
        "channel_binding=prefer",
        "channel_binding=disable",
        "channel_binding=invalid",
        "channel_binding=",
    ],
)
def test_unsupported_or_ambiguous_security_options_are_rejected_without_secrets(query):
    config = DatabaseConfig(backend="postgres", postgres_url=f"postgresql://user:private-password@localhost/test?{query}")
    with pytest.raises(ValueError) as caught:
        _ = config.app_sqlalchemy_url
    assert "private-password" not in str(caught.value)
    assert make_url(config.app_sync_sqlalchemy_url).query == make_url(config.postgres_url).query


def test_asyncpg_url_normalization_is_idempotent():
    from deerflow.persistence.postgres_url import normalize_asyncpg_url

    normalized = normalize_asyncpg_url("postgres://user:p%40ss@localhost/test?sslmode=verify-full")
    assert normalize_asyncpg_url(normalized) == normalized


@pytest.mark.parametrize("scheme", ["sqlite", "mysql", "postgresql+psycopg"])
def test_asyncpg_url_rejects_other_drivers(scheme):
    from deerflow.persistence.postgres_url import normalize_asyncpg_url

    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_asyncpg_url(f"{scheme}://user:password@localhost/test")


@pytest.mark.asyncio
async def test_raw_libpq_url_bootstraps_through_database_config():
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    schema = "asyncpg_url_" + uuid4().hex
    config = DatabaseConfig(backend="postgres", postgres_url=uri, postgres_schema=schema)
    cleanup = create_async_engine(asyncpg_test_url(uri))
    try:
        await engine_mod.init_engine_from_config(config)
        async with engine_mod.get_engine().connect() as conn:
            assert await conn.scalar(text("SELECT current_schema()")) == schema
            assert await conn.scalar(text("SELECT version_num FROM alembic_version"))
            assert await conn.scalar(text("SELECT to_regclass('runs')")) == "runs"
        assert config.postgres_url == uri
    finally:
        await engine_mod.close_engine()
        async with cleanup.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await cleanup.dispose()

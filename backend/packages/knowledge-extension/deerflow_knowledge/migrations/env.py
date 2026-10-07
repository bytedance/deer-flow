"""Alembic environment for the knowledge extension's own tables.

This chain owns exactly the tables declared in ``deerflow_knowledge.db.Base.metadata``
and nothing else. ``include_object`` excludes every table it does not own — host tables
and any other extension's — so running ``alembic revision --autogenerate`` from this
directory can never propose DDL against them (mirrors the host's filter in spirit; the
host's filter runs the other way around, excluding *this* extension's ``kb_`` tables).

``version_table`` is ``kb_alembic_version``: the extension's chain bookkeeping must not
share the host's ``alembic_version``, or either side's upgrade would skip the other's.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow_knowledge.models  # noqa: F401 - registers the extension's tables
from deerflow_knowledge.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

VERSION_TABLE = "kb_alembic_version"


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ANN001
    """Keep only this chain's own tables in alembic's view."""
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_object=include_object,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # Required for SQLite ALTER TABLE support
        include_object=include_object,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    # Mirror the host env: when a custom Postgres schema is configured, pin this
    # alembic-spawned engine's search_path to it, or kb_alembic_version and every
    # table would land in ``public`` while the app engine reads the custom schema.
    pg_schema = config.get_main_option("deerflow_pg_schema")
    connect_args: dict = {}
    if pg_schema and url and url.split("+", 1)[0].split(":", 1)[0] in {"postgresql", "postgres"}:
        from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

        connect_args = build_asyncpg_connect_args(pg_schema)

    connectable = create_async_engine(url, connect_args=connect_args)

    if connectable.url.drivername.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(connectable.sync_engine, "connect")
        def _alembic_sqlite_busy_timeout(dbapi_conn, _record):  # noqa: ARG001
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout=30000;")
            finally:
                cursor.close()

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

"""Alembic environment for DeerFlow application tables.

ONLY manages DeerFlow's tables (runs, threads_meta, cron_jobs, users).
LangGraph's checkpointer tables are managed by LangGraph itself -- they
have their own schema lifecycle and must not be touched by Alembic.
"""

from __future__ import annotations

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.base import Base

# Import all models so metadata is populated.
try:
    import deerflow.persistence.models as models  # register ORM models with Base.metadata

    _ = models
except ImportError:
    # Models not available — migration will work with existing metadata only.
    logging.getLogger(__name__).warning("Could not import deerflow.persistence.models; Alembic may not detect all tables")

# Enterprise ORM model registration (M0 placeholder; populated by M1/M2/M3).
#
# Each enterprise sub-package (rbac/audit/approval) will declare ORM models
# on the shared ``deerflow.persistence.base:Base`` metadata. Importing those
# modules here forces SQLAlchemy class registration so ``alembic revision
# --autogenerate`` can detect the tables. The blocks below are intentionally
# tolerant of ImportError because in M0 these sub-modules do not yet exist;
# this lets the existing migration environment keep working unchanged while
# we land the foundation.
for _enterprise_module in (
    "deerflow.enterprise.rbac.repository",
    "deerflow.enterprise.audit.storage",
    "deerflow.enterprise.approval.repository",
):
    try:
        __import__(_enterprise_module)
    except ImportError:
        # Sub-module not yet implemented (expected during M0); silent skip.
        logging.getLogger(__name__).debug("Enterprise migration import skipped: %s not yet available", _enterprise_module)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # Required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

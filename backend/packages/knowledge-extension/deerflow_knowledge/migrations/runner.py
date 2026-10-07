"""Bring the extension's private chain to head (mirrors ``bootstrap_schema``).

Runs from ``KnowledgeExtensionService.start()`` against the host session factory's bind,
which is sequenced after the host's own bootstrap by construction (services start once
persistence is ready). Postgres upgrades serialise across Gateway instances with a
session-level advisory lock under this extension's own key; SQLite serialises inside one
process and is best-effort across processes via the file lock + the ``busy_timeout`` the
alembic-spawned engine sets in ``env.py``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent

#: Stable advisory-lock key for this extension's schema upgrade: two random 32-bit
#: halves, distinct from the host's bootstrap key so the two chains never wait on each
#: other. Do not change it while deployments may be mid-upgrade.
_KNOWLEDGE_PG_LOCK_KEY = 0x6B6E6F77  # "know"

_LOCK_RETRY_SECONDS = 1.0


def _escape_url_for_alembic(url: str) -> str:
    """Double literal ``%`` so ConfigParser interpolation leaves the URL intact."""
    return url.replace("%", "%%")


@asynccontextmanager
async def _upgrade_lock(engine: AsyncEngine, backend: str):
    if backend == "postgres":
        async with engine.connect() as conn:
            # Disable idle-in-transaction kills for this transaction only: the lock
            # session sits idle while alembic runs on another connection, and managed
            # Postgres would otherwise drop it (silently releasing the advisory lock).
            await conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
            while not (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _KNOWLEDGE_PG_LOCK_KEY})).scalar_one():
                logger.info("knowledge schema upgrade: advisory lock is held by another instance; waiting")
                await asyncio.sleep(_LOCK_RETRY_SECONDS)
            try:
                logger.info("knowledge schema upgrade: acquired advisory lock key=0x%x", _KNOWLEDGE_PG_LOCK_KEY)
                yield
            finally:
                try:
                    await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _KNOWLEDGE_PG_LOCK_KEY})
                except Exception:  # noqa: BLE001
                    logger.warning("knowledge schema upgrade: pg_advisory_unlock raised; session close will release", exc_info=True)
    else:
        yield


async def run_knowledge_migrations(session_factory) -> None:
    """Bring the extension's chain to head on the host engine's bind."""
    engine = getattr(session_factory, "kw", {}).get("bind")
    if not isinstance(engine, AsyncEngine):
        raise RuntimeError("knowledge migrations need a session factory bound to an async engine")

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _escape_url_for_alembic(engine.url.render_as_string(hide_password=False)))
    try:
        from deerflow.config.app_config import get_app_config

        pg_schema = getattr(getattr(get_app_config(), "database", None), "postgres_schema", "") or ""
    except Exception:  # noqa: BLE001 - a missing config is not this runner's verdict
        pg_schema = ""
    if pg_schema:
        cfg.set_main_option("deerflow_pg_schema", pg_schema)

    backend = engine.url.get_backend_name()
    async with _upgrade_lock(engine, backend):
        await asyncio.to_thread(command.upgrade, cfg, "head")

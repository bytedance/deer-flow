"""Enterprise SQLAlchemy engine wrapper.

Manages the lifecycle of a separate async SQLAlchemy engine dedicated to
enterprise tables (RBAC, audit, approval, OIDC links). Schema management
is delegated to Alembic — the runtime ``init()`` only confirms the
connection works (``SELECT 1``); it never calls ``Base.metadata.create_all``.

Operators run ``alembic upgrade head`` against the enterprise database
URL during deploy; see RFC §8.1 / §8.4.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from deerflow.enterprise.config import EnterpriseDatabaseConfig

logger = logging.getLogger(__name__)


class EnterpriseDatabase:
    """Async SQLAlchemy engine wrapper for enterprise tables.

    Construction does not open any connection — ``init()`` does. Callers
    should treat ``init()`` / ``close()`` as idempotent lifecycle hooks
    invoked from FastAPI's ``lifespan`` (M1+ wires this up).
    """

    def __init__(self, config: EnterpriseDatabaseConfig) -> None:
        self._config = config
        engine_kwargs: dict[str, object] = {"echo": config.echo}
        # SQLAlchemy raises if pool_size is passed to a SQLite (NullPool/StaticPool)
        # engine; only forward it for backends that actually pool.
        if not config.url.startswith(("sqlite", "sqlite+aiosqlite")):
            engine_kwargs["pool_size"] = config.pool_size
            engine_kwargs["pool_pre_ping"] = True
        self.engine: AsyncEngine = create_async_engine(config.url, **engine_kwargs)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        """Initialize the connection pool with a liveness probe.

        Schema creation is intentionally NOT performed here. ``alembic
        upgrade head`` is the single source of truth for schema state
        (RFC §8.1). Auto-creating tables on startup would mask migration
        gaps and conflict with audit / compliance expectations.
        """
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("EnterpriseDatabase initialised: url=%s", self._config.url)

    async def close(self) -> None:
        """Dispose the engine and release pooled connections."""
        await self.engine.dispose()
        logger.info("EnterpriseDatabase closed")


__all__ = ["EnterpriseDatabase"]

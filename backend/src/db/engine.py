"""Database engine and session management.

Supports both PostgreSQL (production) and file-based (local dev) modes.
When DATABASE_URL is set, PostgreSQL is used; otherwise, falls back to
file-based storage in .think-tank/ directory.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""

    pass


def get_database_url() -> str | None:
    """Get the database URL from environment, if configured."""
    return os.environ.get("DATABASE_URL")


def get_sync_database_url() -> str | None:
    """Get a synchronous database URL from the configured DATABASE_URL.

    Converts asyncpg URLs to psycopg2-compatible URLs for synchronous operations.
    """
    url = get_database_url()
    if not url:
        return None
    # Convert async driver to sync driver
    return url.replace("postgresql+asyncpg://", "postgresql://")


def is_db_enabled() -> bool:
    """Check if database mode is enabled (DATABASE_URL is set)."""
    return bool(get_database_url())


# Lazy-initialized engine and session factory
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Get or create the synchronous SQLAlchemy engine.

    Raises:
        RuntimeError: If DATABASE_URL is not configured.
    """
    global _engine
    if _engine is None:
        url = get_sync_database_url()
        if not url:
            raise RuntimeError("DATABASE_URL is not configured")
        _engine = create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Get a database session as a context manager.

    Usage::

        with get_db_session() as session:
            session.query(User).all()
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initialize the database: create all tables.

    This is primarily for development/testing. In production,
    use Alembic migrations.
    """
    # Import models to ensure they are registered with Base.metadata
    import src.db.models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def run_db_migrations() -> None:
    """Run Alembic migrations to bring the schema to head.

    This is safe to call at startup. If DATABASE_URL is not configured,
    this function is a no-op.
    """
    if not is_db_enabled():
        return

    # Import lazily so file-based mode does not require Alembic.
    from alembic import command
    from alembic.config import Config

    sync_url = get_sync_database_url()
    if not sync_url:
        return

    backend_dir = Path(__file__).resolve().parents[2]
    alembic_ini = backend_dir / "alembic.ini"
    migrations_dir = backend_dir / "src" / "db" / "migrations"

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", sync_url)

    command.upgrade(config, "head")


def check_db_connection() -> str:
    """Check if the database is reachable.

    Returns:
        "healthy" if connection succeeds, error description otherwise.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "healthy"
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return f"unhealthy: {e}"


def reset_engine() -> None:
    """Reset the engine and session factory.

    Useful for testing when switching database configurations.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None

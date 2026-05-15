from typing import Any

from sqlalchemy import URL
from sqlalchemy.engine.url import make_url

from store.common import DataBaseType
from store.config.app_config import get_app_config
from store.config.storage_config import StorageConfig
from store.persistence.types import AppPersistence


def storage_config_from_database_config(database_config: Any) -> StorageConfig:
    """Convert the existing public DatabaseConfig shape to StorageConfig.

    Storage only owns durable database-backed persistence. The app bridge
    should handle memory mode before calling into this package.
    """
    backend = getattr(database_config, "backend", None)
    if backend == "sqlite":
        return StorageConfig(
            driver="sqlite",
            sqlite_dir=getattr(database_config, "sqlite_dir", ".deer-flow/data"),
            echo_sql=getattr(database_config, "echo_sql", False),
            pool_size=getattr(database_config, "pool_size", 5),
        )

    if backend == "postgres":
        postgres_url = getattr(database_config, "postgres_url", "")
        if not postgres_url:
            raise ValueError("database.postgres_url is required when database.backend is 'postgres'")
        parsed = make_url(postgres_url)
        return StorageConfig(
            driver="postgres",
            database_url=postgres_url,
            username=parsed.username or "",
            password=parsed.password or "",
            host=parsed.host or "localhost",
            port=parsed.port or 5432,
            db_name=parsed.database or "deerflow",
            echo_sql=getattr(database_config, "echo_sql", False),
            pool_size=getattr(database_config, "pool_size", 5),
        )

    raise ValueError(f"Unsupported database backend for storage persistence: {backend!r}")


def _create_database_url(storage_config: StorageConfig) -> URL:
    """Build an async SQLAlchemy URL from StorageConfig (sqlite/mysql/postgres)."""

    if storage_config.driver == DataBaseType.sqlite:
        driver = "sqlite+aiosqlite"
    elif storage_config.driver == DataBaseType.mysql:
        driver = "mysql+aiomysql"
    elif storage_config.driver in (DataBaseType.postgresql, "postgres"):
        driver = "postgresql+asyncpg"
    else:
        raise ValueError(f"Unsupported database driver: {storage_config.driver}")

    if storage_config.driver == DataBaseType.sqlite:
        import os

        db_path = storage_config.sqlite_storage_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        url = URL.create(
            drivername=driver,
            database=db_path,
        )
    elif storage_config.database_url:
        url = make_url(storage_config.database_url)
        if storage_config.driver in (DataBaseType.postgresql, "postgres") and url.drivername == "postgresql":
            url = url.set(drivername="postgresql+asyncpg")
        elif storage_config.driver == DataBaseType.mysql and url.drivername == "mysql":
            url = url.set(drivername="mysql+aiomysql")
    else:
        url = URL.create(
            drivername=driver,
            username=storage_config.username,
            password=storage_config.password,
            host=storage_config.host,
            port=storage_config.port,
            database=storage_config.db_name or "deerflow",
        )

    return url


async def create_persistence_from_storage_config(storage_config: StorageConfig) -> AppPersistence:
    from .drivers.mysql import build_mysql_persistence
    from .drivers.postgres import build_postgres_persistence
    from .drivers.sqlite import build_sqlite_persistence

    driver = storage_config.driver
    db_url = _create_database_url(storage_config)

    if driver in ("postgres", "postgresql"):
        return await build_postgres_persistence(
            db_url,
            echo=storage_config.echo_sql,
            pool_size=storage_config.pool_size,
        )

    if driver == "mysql":
        return await build_mysql_persistence(
            db_url,
            echo=storage_config.echo_sql,
            pool_size=storage_config.pool_size,
        )

    if driver == "sqlite":
        return await build_sqlite_persistence(db_url, echo=storage_config.echo_sql)

    raise ValueError(f"Unsupported database driver: {driver}")


async def create_persistence_from_database_config(database_config: Any) -> AppPersistence:
    storage_config = storage_config_from_database_config(database_config)
    return await create_persistence_from_storage_config(storage_config)


async def create_persistence() -> AppPersistence:
    app_config = get_app_config()
    return await create_persistence_from_storage_config(app_config.storage)

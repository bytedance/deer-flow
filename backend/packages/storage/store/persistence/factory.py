from sqlalchemy import URL

from store.common import DataBaseType
from store.config.app_config import get_app_config
from store.config.storage_config import StorageConfig
from store.persistence.types import AppPersistence


def _create_database_url(storage_config: StorageConfig) -> URL:
    """Build an async SQLAlchemy URL from StorageConfig (sqlite/mysql/postgres)."""

    if storage_config.driver == DataBaseType.sqlite:
        driver = "sqlite+aiosqlite"
    elif storage_config.driver == DataBaseType.mysql:
        driver = "mysql+aiomysql"
    elif storage_config.driver == DataBaseType.postgresql:
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


async def create_persistence() -> AppPersistence:
    from .drivers.mysql import build_mysql_persistence
    from .drivers.postgres import build_postgres_persistence
    from .drivers.sqlite import build_sqlite_persistence

    app_config = get_app_config()

    driver = app_config.storage.driver
    db_url = _create_database_url(app_config.storage)

    if driver == "postgresql":
        return await build_postgres_persistence(db_url)

    if driver == "mysql":
        return await build_mysql_persistence(db_url)

    if driver == "sqlite":
        return await build_sqlite_persistence(db_url)

    raise ValueError(f"Unsupported database driver: {driver}")

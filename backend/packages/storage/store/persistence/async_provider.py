from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import URL

from store.config.app_config import get_app_config


@asynccontextmanager
async def make_checkpointer() -> AsyncIterator[object]:
    """Create a LangGraph checkpointer from the unified storage config."""
    storage = get_app_config().storage

    if storage.driver == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        conn_str = storage.sqlite_storage_path
        await asyncio.to_thread(_ensure_sqlite_parent_dir, conn_str)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()
            yield saver
        return

    if storage.driver == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(_create_postgres_url(storage)) as saver:
            await saver.setup()
            yield saver
        return

    if storage.driver == "mysql":
        from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

        async with AIOMySQLSaver.from_conn_string(_create_mysql_url(storage)) as saver:
            await saver.setup()
            yield saver
        return

    raise ValueError(f"Unsupported storage driver for checkpointer: {storage.driver}")


def _ensure_sqlite_parent_dir(connection_string: str) -> None:
    from pathlib import Path

    if connection_string == ":memory:":
        return
    Path(connection_string).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _create_postgres_url(storage) -> URL:
    return URL.create(
        drivername="postgresql+asyncpg",
        username=storage.username,
        password=storage.password,
        host=storage.host,
        port=storage.port,
        database=storage.db_name or "deerflow",
    )


def _create_mysql_url(storage) -> URL:
    return URL.create(
        drivername="mysql+aiomysql",
        username=storage.username,
        password=storage.password,
        host=storage.host,
        port=storage.port,
        database=storage.db_name or "deerflow",
    )


__all__ = ["make_checkpointer"]

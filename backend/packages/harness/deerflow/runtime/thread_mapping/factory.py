"""Construct native :class:`ThreadMappingStore` backends from :class:`UserThreadMappingConfig` (no LangGraph)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from deerflow.config.user_thread_config import UserThreadMappingConfig
from deerflow.runtime._db_utils import (
    assert_sqlite_path_no_user_thread_placeholders,
    ensure_postgres_schema_exists,
    ensure_sqlite_parent_dir,
    resolve_sqlite_conn_str,
    validate_mongo_collection_name,
)
from .types import ThreadMappingStore

logger = logging.getLogger(__name__)

SQLITE_MAPPING_INSTALL = (
    "aiosqlite is required for user_thread_mapping type sqlite. Install with: uv add aiosqlite"
)
POSTGRES_MAPPING_INSTALL = (
    "psycopg is required for user_thread_mapping type postgres. "
    "Install with: uv add 'psycopg[binary]' or deerflow-harness[memory-db]"
)
MONGO_MAPPING_INSTALL = (
    "pymongo is required for user_thread_mapping type mongo. "
    "Install with: uv add pymongo or deerflow-harness[memory-db]"
)


@contextlib.asynccontextmanager
async def native_thread_mapping_store(
        config: UserThreadMappingConfig,
) -> AsyncIterator[ThreadMappingStore]:
    """Open the configured mapping store and tear it down on exit."""
    if config.type == "memory":
        from .stores.memory import MemoryThreadMappingStore

        logger.info("Thread mapping: MemoryThreadMappingStore (in-process)")
        yield MemoryThreadMappingStore()
        return

    if config.type == "sqlite":
        try:
            import aiosqlite
        except ImportError as exc:
            raise ImportError(SQLITE_MAPPING_INSTALL) from exc

        from .stores.memory import SqliteThreadMappingStore

        if not config.connection_string:
            raise ValueError("user_thread_mapping.connection_string is required for sqlite")
        conn_template = assert_sqlite_path_no_user_thread_placeholders(
            config.connection_string, role="user_thread_mapping (sqlite)"
        )
        conn_str = resolve_sqlite_conn_str(conn_template)
        ensure_sqlite_parent_dir(conn_str)
        async with aiosqlite.connect(conn_str) as conn:
            store = SqliteThreadMappingStore(conn, table=config.table)
            await store._ensure_table()
            logger.info("Thread mapping: SqliteThreadMappingStore (%s, table=%s)", conn_str, config.table)
            yield store
        return

    if config.type == "postgres":
        from deerflow.persistence.engine import get_session_factory
        from deerflow.persistence.thread_meta import ThreadMetaRepository

        session_factory = get_session_factory()
        if session_factory is None:
            raise ValueError("user_thread_mapping.type=postgres requires initialized persistence engine/session factory")

        from .stores.persistence_adapter import PersistenceThreadMappingStore

        logger.info("Thread mapping: PersistenceThreadMappingStore (thread_meta-backed)")
        yield PersistenceThreadMappingStore(ThreadMetaRepository(session_factory))
        return

    if config.type == "postgres-legacy":
        try:
            from psycopg import AsyncConnection
        except ImportError as exc:
            raise ImportError(POSTGRES_MAPPING_INSTALL) from exc

        from .stores.memory import PostgresThreadMappingStore

        if not config.connection_string:
            raise ValueError("user_thread_mapping.connection_string is required for postgres")
        dsn = str(config.connection_string).strip()
        await asyncio.to_thread(ensure_postgres_schema_exists, dsn, config.postgres_schema)
        async with await AsyncConnection.connect(dsn) as conn:
            store = PostgresThreadMappingStore(
                conn,
                schema=config.postgres_schema,
                table=config.table,
            )
            await store._ensure_table()
            sch = config.postgres_schema
            logger.info(
                "Thread mapping: PostgresThreadMappingStore legacy (table=%s%s)",
                config.table,
                f", schema={sch.strip()}" if sch and str(sch).strip() else "",
            )
            yield store
            return

    if config.type == "mongo":
        try:
            from pymongo import AsyncMongoClient
        except ImportError as exc:
            raise ImportError(MONGO_MAPPING_INSTALL) from exc

        from .stores.memory import MongoThreadMappingStore

        if not config.connection_string:
            raise ValueError("user_thread_mapping.connection_string is required for mongo")
        uri = str(config.connection_string).strip()
        coll_name = validate_mongo_collection_name(config.mongo_collection or config.table)
        db_name = str(config.mongo_database).strip() or "deerflow"
        client: AsyncMongoClient = AsyncMongoClient(uri)
        try:
            coll = client[db_name][coll_name]
            store = MongoThreadMappingStore(coll)
            await store._ensure_indexes()
            logger.info("Thread mapping: MongoThreadMappingStore (db=%s, collection=%s)", db_name, coll_name)
            yield store
        finally:
            await client.close()
        return

    if config.type == "redis":
        import redis.asyncio as redis_async

        from .stores.memory import RedisThreadMappingStore

        if not config.connection_string:
            raise ValueError("user_thread_mapping.connection_string is required for redis")
        url = str(config.connection_string).strip()
        r = redis_async.from_url(url, decode_responses=True)
        try:
            store = RedisThreadMappingStore(r, key_prefix=config.redis_key_prefix)
            logger.info("Thread mapping: RedisThreadMappingStore (prefix=%s)", config.redis_key_prefix)
            yield store
        finally:
            await r.aclose()
        return

    raise ValueError(f"Unknown user_thread_mapping type: {config.type!r}")

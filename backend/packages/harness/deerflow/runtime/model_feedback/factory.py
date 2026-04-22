"""Open :class:`ModelFeedbackStore` backends from :class:`ModelFeedbackConfig`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from deerflow.config.model_feedback_config import ModelFeedbackConfig
from deerflow.runtime._db_utils import (
    assert_sqlite_path_no_user_thread_placeholders,
    ensure_postgres_schema_exists,
    ensure_sqlite_parent_dir,
    resolve_sqlite_conn_str,
    validate_mongo_collection_name,
)
from deerflow.runtime.model_feedback.stores.impl import (
    MemoryModelFeedbackStore,
    MongoModelFeedbackStore,
    PostgresModelFeedbackStore,
    RedisModelFeedbackStore,
    SqliteModelFeedbackStore,
)
from deerflow.runtime.model_feedback.types import ModelFeedbackStore

logger = logging.getLogger(__name__)

SQLITE_INSTALL = "aiosqlite is required for model_feedback type sqlite. Install with: uv add aiosqlite"
POSTGRES_INSTALL = "psycopg is required for model_feedback type postgres. Install with: uv add 'psycopg[binary]'"
MONGO_INSTALL = "pymongo is required for model_feedback type mongo. Install with: uv add pymongo"


@contextlib.asynccontextmanager
async def native_model_feedback_store(config: ModelFeedbackConfig) -> AsyncIterator[ModelFeedbackStore]:
    """Yield a store matching *config* and tear it down on exit."""
    if config.type == "memory":
        logger.info("Model feedback: MemoryModelFeedbackStore (in-process)")
        yield MemoryModelFeedbackStore()
        return

    if config.type == "sqlite":
        try:
            import aiosqlite
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        if not config.connection_string:
            raise ValueError("model_feedback.connection_string is required for sqlite")
        conn_template = assert_sqlite_path_no_user_thread_placeholders(
            config.connection_string, role="model_feedback (sqlite)"
        )
        conn_str = resolve_sqlite_conn_str(conn_template)
        ensure_sqlite_parent_dir(conn_str)
        async with aiosqlite.connect(conn_str) as conn:
            store = SqliteModelFeedbackStore(conn, table=config.table)
            await store._ensure_table()
            logger.info("Model feedback: SqliteModelFeedbackStore (%s, table=%s)", conn_str, config.table)
            yield store
        return

    if config.type == "postgres":
        try:
            from psycopg import AsyncConnection
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError("model_feedback.connection_string is required for postgres")
        dsn = str(config.connection_string).strip()
        await asyncio.to_thread(ensure_postgres_schema_exists, dsn, config.postgres_schema)
        async with await AsyncConnection.connect(dsn) as conn:
            store = PostgresModelFeedbackStore(conn, schema=config.postgres_schema, table=config.table)
            await store._ensure_table()
            sch = config.postgres_schema
            logger.info(
                "Model feedback: PostgresModelFeedbackStore (table=%s%s)",
                config.table,
                f", schema={sch.strip()}" if sch and str(sch).strip() else "",
            )
            yield store
        return

    if config.type == "mongo":
        try:
            from pymongo import AsyncMongoClient
        except ImportError as exc:
            raise ImportError(MONGO_INSTALL) from exc

        if not config.connection_string:
            raise ValueError("model_feedback.connection_string is required for mongo")
        uri = str(config.connection_string).strip()
        coll_name = validate_mongo_collection_name(config.mongo_collection or config.table)
        db_name = str(config.mongo_database).strip() or "deerflow"
        client: AsyncMongoClient = AsyncMongoClient(uri)
        try:
            coll = client[db_name][coll_name]
            store = MongoModelFeedbackStore(coll)
            await store._ensure_indexes()
            logger.info("Model feedback: MongoModelFeedbackStore (db=%s, collection=%s)", db_name, coll_name)
            yield store
        finally:
            await client.close()
        return

    if config.type == "redis":
        import redis.asyncio as redis_async

        if not config.connection_string:
            raise ValueError("model_feedback.connection_string is required for redis")
        url = str(config.connection_string).strip()
        r = redis_async.from_url(url, decode_responses=True)
        try:
            store = RedisModelFeedbackStore(r, key_prefix=config.redis_key_prefix)
            logger.info("Model feedback: RedisModelFeedbackStore (prefix=%s)", config.redis_key_prefix)
            yield store
        finally:
            await r.aclose()
        return

    raise ValueError(f"Unknown model_feedback type: {config.type!r}")

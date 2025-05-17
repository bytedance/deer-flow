# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver

from src.config.loader import load_yaml_config

logger = logging.getLogger(__name__)

_connection_pool = {}


async def _create_checkpointer_from_config() -> Optional[object]:
    """Get appropriate saver based on configuration."""
    global _connection_pool

    config = load_yaml_config("conf.yaml")
    storage_config = config.get("STORAGE", {})

    if storage_config is None:
        logger.warning("STORAGE configuration not found, using default memory storage")
        storage_config = {}

    storage_type = storage_config.get("type", "memory")

    logger.info(f"Loading storage type: {storage_type}")

    if storage_type == "memory" or not storage_type:
        logger.info("Using MemorySaver for workflow persistence")
        return MemorySaver()

    elif storage_type == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import aiosqlite

        try:
            # Check if there's already a SQLite connection in the connection pool
            if "sqlite" not in _connection_pool:
                # Create a new connection and save it in the connection pool
                conn = await aiosqlite.connect("checkpoints.db")
                saver = AsyncSqliteSaver(conn)
                await saver.setup()
                _connection_pool["sqlite"] = {"conn": conn, "saver": saver}
                logger.info("New SQLite connection created and setup successfully")
            else:
                logger.info("Reusing existing SQLite connection")

            return _connection_pool["sqlite"]["saver"]
        except Exception as e:
            logger.error(
                f"Error initializing AsyncSqliteSaver: {e}. Falling back to MemorySaver."
            )
            return MemorySaver()

    elif storage_type == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        # Get database URI
        db_uri = storage_config.get("db_uri")
        if not db_uri:
            logger.warning(
                "PostgreSQL connection URI not configured. Falling back to MemorySaver."
            )
            return MemorySaver()

        # Get connection pool configuration
        pool_config = storage_config.get("pool", {})

        # Check if there's already a PostgreSQL connection in the connection pool
        if "postgres" not in _connection_pool:
            try:
                # Parse connection string in key-value format into connection parameters
                conn_params = {}
                for param in db_uri.split():
                    if "=" in param:
                        key, value = param.split("=", 1)
                        conn_params[key] = value

                # Get connection pool parameters from config file, use defaults as fallback
                min_size = pool_config.get("min_size", 1)
                max_size = pool_config.get("max_size", 5)
                timeout = pool_config.get("timeout", 30)
                max_idle = pool_config.get("max_idle", 300)
                max_lifetime = pool_config.get("max_lifetime", 3600)
                pool_name = pool_config.get("name", "pgpool")

                # Create connection pool using recommended explicit open() approach to avoid warnings
                # open=False ensures we control when to open the pool
                pool = AsyncConnectionPool(
                    kwargs=conn_params,
                    min_size=min_size,
                    max_size=max_size,
                    timeout=timeout,
                    max_idle=max_idle,
                    max_lifetime=max_lifetime,
                    name=pool_name,
                    open=False,  # Explicitly specify not to open in constructor
                )

                # Explicitly open the connection pool
                await pool.open()

                # Get a connection to setup the database
                async with pool.connection() as conn:
                    # Create saver and setup database tables
                    saver = AsyncPostgresSaver(conn)
                    await saver.setup()

                # Create a custom saver class that gets new connections from the pool
                class PooledPostgresSaver(AsyncPostgresSaver):
                    def __init__(self, pool):
                        self.pool = pool
                        # We don't set self.conn here, but get a new connection for each operation

                    async def aget_tuple(self, config):
                        async with self.pool.connection() as conn:
                            temp_saver = AsyncPostgresSaver(conn)
                            return await temp_saver.aget_tuple(config)

                    async def aput(self, config, checkpoint, metadata, new_versions):
                        async with self.pool.connection() as conn:
                            temp_saver = AsyncPostgresSaver(conn)
                            return await temp_saver.aput(
                                config, checkpoint, metadata, new_versions
                            )

                    async def alist(self, config, **kwargs):
                        async with self.pool.connection() as conn:
                            temp_saver = AsyncPostgresSaver(conn)
                            async for item in temp_saver.alist(config, **kwargs):
                                yield item

                    async def aput_writes(self, config, writes, task_id, task_path=""):
                        async with self.pool.connection() as conn:
                            temp_saver = AsyncPostgresSaver(conn)
                            await temp_saver.aput_writes(
                                config, writes, task_id, task_path
                            )

                    async def adelete_thread(self, thread_id):
                        async with self.pool.connection() as conn:
                            temp_saver = AsyncPostgresSaver(conn)
                            await temp_saver.adelete_thread(thread_id)

                # Create pooled saver
                pooled_saver = PooledPostgresSaver(pool)

                # Store pool and saver in the connection pool
                _connection_pool["postgres"] = {"pool": pool, "saver": pooled_saver}

                return pooled_saver
            except Exception as e:
                logger.error(f"Error setting up PostgreSQL connection: {e}")
                import traceback

                logger.error(f"Traceback: {traceback.format_exc()}")
                return MemorySaver()
        else:
            logger.info("Reusing existing PostgreSQL connection pool")
            return _connection_pool["postgres"]["saver"]

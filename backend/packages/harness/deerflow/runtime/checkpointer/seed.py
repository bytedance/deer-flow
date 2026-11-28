"""Publish a thread's first checkpoint atomically with respect to deletion."""

import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext

from langgraph.checkpoint.base import get_checkpoint_metadata
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
except ImportError:  # Optional PostgreSQL extra.
    AsyncPostgresSaver = None


@asynccontextmanager
async def _postgres_thread_transaction(saver, thread_id):
    from psycopg_pool import AsyncConnectionPool

    # Use the saver's connection (including its configured schema and serde).
    # DELETE cannot lock a missing root row. Take the same transaction-scoped
    # advisory lock for both operations, including when the thread is empty.
    pooled = isinstance(saver.conn, AsyncConnectionPool)
    connection = saver.conn.connection() if pooled else nullcontext(saver.conn)
    connection_lock = nullcontext() if pooled else saver.lock
    async with connection_lock, connection as conn, conn.transaction():
        # A delete which waits for a seed must see its commit in the next
        # statement even when the connection defaults to repeatable read.
        await conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        await conn.execute("SELECT pg_advisory_xact_lock('checkpoints'::regclass::oid::int, hashtext(%s))", (thread_id,))
        yield AsyncPostgresSaver(conn, pipe=saver.pipe, serde=saver.serde)


@asynccontextmanager
async def _sqlite_writer(saver):
    await saver.setup()
    async with saver.lock:
        # Reserve the writer before running any statement. A timed-out DELETE
        # must not leave a read transaction on the gateway's shared connection.
        try:
            async with saver.conn.execute("BEGIN IMMEDIATE"):
                yield saver.conn
        except BaseException:
            await saver.conn.rollback()
            raise


async def put_sql_seed(saver, config, checkpoint, metadata, validate: Callable[[], Awaitable[None]]) -> bool:
    """Handle a SQL seed in the source saver's transaction, including delta mode."""
    source = saver.source_saver if isinstance(saver, CachedHistorySaver) else saver
    thread_id = config["configurable"]["thread_id"]
    if isinstance(source, AsyncSqliteSaver):
        # LangGraph's aput commits internally. Stage its empty-root row on the
        # saver connection so we can roll it back if admission changed during
        # the insert. SQLite's writer lock orders the commit with every delete.
        kind, payload = source.serde.dumps_typed(checkpoint)
        encoded = json.dumps(get_checkpoint_metadata(config, metadata), ensure_ascii=False).encode("utf-8", "ignore")
        async with _sqlite_writer(source) as conn:
            async with conn.execute(
                """INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata)
                   SELECT ?, '', ?, ?, ?, ? WHERE NOT EXISTS
                   (SELECT 1 FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = '')""",
                (thread_id, checkpoint["id"], kind, payload, encoded, thread_id),
            ):
                await validate()
                await conn.commit()
    elif AsyncPostgresSaver is not None and isinstance(source, AsyncPostgresSaver):
        async with _postgres_thread_transaction(source, thread_id) as transaction:
            if await transaction.aget_tuple(config) is None:
                await transaction.aput(config, checkpoint, metadata, {})
            await validate()
    else:
        return False
    return True


async def delete_thread_checkpoints(saver, thread_id: str) -> None:
    source = saver.source_saver if isinstance(saver, CachedHistorySaver) else saver
    if isinstance(source, AsyncSqliteSaver):
        async with _sqlite_writer(source) as conn:
            # The outer lock owns the connection. The scoped saver can use
            # LangGraph's normal multi-table delete and commit on that connection.
            await AsyncSqliteSaver(conn).adelete_thread(thread_id)
    elif AsyncPostgresSaver is not None and isinstance(source, AsyncPostgresSaver):
        async with _postgres_thread_transaction(source, thread_id) as transaction:
            await transaction.adelete_thread(thread_id)
    else:
        await saver.adelete_thread(thread_id)
        return
    if isinstance(saver, CachedHistorySaver):
        await saver.ainvalidate_history_cache(thread_id)

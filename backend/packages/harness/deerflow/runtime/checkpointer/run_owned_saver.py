"""Limit graph checkpoint writes to the run that owns the active lease."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple

from deerflow.runtime.cancellation import drained_async_context


class CheckpointOwnershipLostError(RuntimeError):
    """The graph tried to write after its run lost ownership."""


class RunOwnedSaver(BaseCheckpointSaver):
    """Check one run's ownership before each graph checkpoint write."""

    def __init__(self, inner: BaseCheckpointSaver, run_manager: Any, record: Any) -> None:
        super().__init__(serde=inner.serde)
        self._inner = inner
        self._run_manager = run_manager
        self._record = record
        self._postgres = self._postgres_source(inner)

    @staticmethod
    def _postgres_source(inner: BaseCheckpointSaver):
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError:
            return None
        source = getattr(inner, "source_saver", inner)
        return source if isinstance(source, AsyncPostgresSaver) else None

    @property
    def config_specs(self):
        return self._inner.config_specs

    def get_next_version(self, current, channel):
        return self._inner.get_next_version(current, channel)

    async def _assert_owned(self, config: RunnableConfig) -> None:
        if config.get("configurable", {}).get("thread_id") != self._record.thread_id:
            raise CheckpointOwnershipLostError("Checkpoint thread differs from the owned run")
        if not await self._run_manager.owns_active_admission(self._record):
            raise CheckpointOwnershipLostError("Run lost checkpoint write ownership")

    @asynccontextmanager
    async def _postgres_writer(self, config):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        if config.get("configurable", {}).get("thread_id") != self._record.thread_id:
            raise CheckpointOwnershipLostError("Checkpoint thread differs from the owned run")
        if self._record.ownership_lost:
            raise CheckpointOwnershipLostError("Run lost checkpoint write ownership")

        source = self._postgres
        connection_source = source.conn

        @asynccontextmanager
        async def connection():
            if isinstance(connection_source, AsyncConnectionPool):
                async with drained_async_context(connection_source.connection()) as conn:
                    yield conn
            else:
                yield connection_source

        async with source.lock, connection() as conn, drained_async_context(conn.transaction()):
            await conn.execute("SELECT run_id FROM runs WHERE run_id = %s FOR UPDATE", (self._record.run_id,))
            cursor = await conn.execute(
                """
                SELECT 1 FROM runs
                WHERE run_id = %s AND thread_id = %s AND owner_worker_id = %s
                  AND run_incarnation IS NOT DISTINCT FROM %s
                  AND producer_epoch IS NOT DISTINCT FROM %s
                  AND status IN ('pending', 'running')
                  AND lease_expires_at > clock_timestamp()
                """,
                (
                    self._record.run_id,
                    self._record.thread_id,
                    self._record.owner_worker_id,
                    self._record.run_incarnation,
                    self._record.producer_epoch,
                ),
            )
            if await cursor.fetchone() is None:
                raise CheckpointOwnershipLostError("Run lost checkpoint write ownership")
            yield AsyncPostgresSaver(conn=conn, serde=source.serde)

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self._inner.get_tuple(config)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await self._inner.aget_tuple(config)

    def list(self, config: RunnableConfig | None, *, filter=None, before=None, limit=None) -> Iterator[CheckpointTuple]:
        return self._inner.list(config, filter=filter, before=before, limit=limit)

    def alist(self, config: RunnableConfig | None, *, filter=None, before=None, limit=None):
        return self._inner.alist(config, filter=filter, before=before, limit=limit)

    def put(self, config, checkpoint, metadata, new_versions):
        raise CheckpointOwnershipLostError("Synchronous graph checkpoint writes need run ownership")

    async def aput(self, config, checkpoint, metadata, new_versions):
        if self._postgres is not None:
            async with self._postgres_writer(config) as saver:
                return await saver.aput(config, checkpoint, metadata, new_versions)
        await self._assert_owned(config)
        return await self._inner.aput(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path="") -> None:
        raise CheckpointOwnershipLostError("Synchronous graph checkpoint writes need run ownership")

    async def aput_writes(self, config, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = "") -> None:
        if self._postgres is not None:
            async with self._postgres_writer(config) as saver:
                await saver.aput_writes(config, writes, task_id, task_path)
            return
        await self._assert_owned(config)
        await self._inner.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        config = {"configurable": {"thread_id": thread_id}}
        if self._postgres is not None:
            async with self._postgres_writer(config) as saver:
                await saver.adelete_thread(thread_id)
            invalidate = getattr(self._inner, "ainvalidate_history_cache", None)
            if invalidate is not None:
                await invalidate(thread_id)
            return
        await self._assert_owned(config)
        await self._inner.adelete_thread(thread_id)

    def get_delta_channel_history(self, *, config, channels):
        return self._inner.get_delta_channel_history(config=config, channels=channels)

    async def aget_delta_channel_history(self, *, config, channels):
        return await self._inner.aget_delta_channel_history(config=config, channels=channels)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

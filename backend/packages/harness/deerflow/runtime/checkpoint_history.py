"""Shared checkpoint-history traversal for partially asynchronous savers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph._internal._constants import CONFIG_KEY_CHECKPOINTER, CONFIG_KEY_DURABILITY, NS_SEP
from langgraph.runtime import ExecutionInfo
from langgraph.types import StateSnapshot

from deerflow.runtime.checkpoint_mode import INTERNAL_CHECKPOINT_MODE_KEY
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph

_ASYNC_CHECKPOINT_WAIT_SECONDS = 2


async def task_checkpoint_ancestors(config: RunnableConfig, execution: ExecutionInfo, *, thread_id: str) -> AsyncIterator[StateSnapshot]:
    """Read the executing task's pinned checkpoint lineage within its graph."""
    configurable = config.get("configurable", {})
    checkpointer = configurable.get(CONFIG_KEY_CHECKPOINTER)
    if checkpointer is None or execution.thread_id != thread_id or not execution.checkpoint_id:
        return

    # ExecutionInfo identifies the task namespace. The containing graph saved
    # the checkpoint that scheduled this task under the parent namespace.
    namespace = execution.checkpoint_ns.rpartition(NS_SEP)[0]
    mode = "delta" if configurable.get(INTERNAL_CHECKPOINT_MODE_KEY) == "delta" else "full"
    graph = build_state_mutation_graph("read_checkpoint_history", mode)
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode=mode, direct_namespace=True)
    scope = {"thread_id": thread_id, "checkpoint_ns": namespace}
    cursor = {**scope, "checkpoint_id": execution.checkpoint_id}
    visited = set()
    read_sync = False
    loop = asyncio.get_running_loop()
    pending_until = loop.time() + _ASYNC_CHECKPOINT_WAIT_SECONDS if configurable.get(CONFIG_KEY_DURABILITY, "async") == "async" else 0
    while (checkpoint_id := cursor.get("checkpoint_id")) and checkpoint_id not in visited:
        if cursor.get("thread_id") != thread_id or cursor.get("checkpoint_ns", "") != namespace:
            return
        await asyncio.sleep(0)  # Let deadlines and cancellation interrupt an in-memory walk.
        read_config = {"configurable": {**scope, "checkpoint_id": checkpoint_id}}
        if not read_sync:
            try:
                snapshot = await accessor.aget(read_config)
            except NotImplementedError:
                read_sync = True
        if read_sync:
            snapshot = await asyncio.to_thread(accessor.get, read_config)
        if snapshot.created_at is None and not visited and loop.time() < pending_until:
            # An async run can start its tool while the scheduling checkpoint
            # is still being written. Wait for that ID rather than reading the head.
            await asyncio.sleep(0.05)
            continue
        saved = snapshot.config["configurable"]
        if snapshot.created_at is None or saved.get("checkpoint_id") != checkpoint_id or saved.get("thread_id") != thread_id or saved.get("checkpoint_ns", "") != namespace:
            return
        visited.add(checkpoint_id)
        yield snapshot
        cursor = (snapshot.parent_config or {}).get("configurable", {})


async def recent_checkpoint_history(checkpointer: Any, read_config: dict[str, Any], *, limit: int = 20) -> AsyncIterator[Any]:
    """Yield checkpoints newest-first, degrading to the current tuple when needed.

    ``BaseCheckpointSaver`` exposes asynchronous methods even when a saver only
    implements their synchronous counterparts. Each stage therefore treats
    ``NotImplementedError`` as a capability signal and moves to the next one.
    Synchronous iteration and reads are kept off the event loop.
    """
    if checkpointer is None:
        return

    async_history = getattr(checkpointer, "alist", None)
    if callable(async_history):
        try:
            async for checkpoint_tuple in async_history(read_config, limit=limit):
                yield checkpoint_tuple
            return
        except NotImplementedError:
            pass

    sync_history = getattr(checkpointer, "list", None)
    if callable(sync_history):
        try:
            checkpoints = await asyncio.to_thread(lambda: list(sync_history(read_config, limit=limit)))
        except NotImplementedError:
            pass
        else:
            for checkpoint_tuple in checkpoints:
                yield checkpoint_tuple
            return

    async_get_tuple = getattr(checkpointer, "aget_tuple", None)
    if callable(async_get_tuple):
        try:
            checkpoint_tuple = await async_get_tuple(read_config)
        except NotImplementedError:
            pass
        else:
            if checkpoint_tuple is not None:
                yield checkpoint_tuple
            return

    sync_get_tuple = getattr(checkpointer, "get_tuple", None)
    if callable(sync_get_tuple):
        try:
            checkpoint_tuple = await asyncio.to_thread(sync_get_tuple, read_config)
        except NotImplementedError:
            return
        if checkpoint_tuple is not None:
            yield checkpoint_tuple

"""Shared checkpoint-history traversal for partially asynchronous savers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


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

"""Async stream bridge factory.

Provides an **async context manager** aligned with
:func:`deerflow.runtime.checkpointer.async_provider.make_checkpointer`.

Usage (e.g. FastAPI lifespan)::

    from deerflow.agents.stream_bridge import make_stream_bridge

    async with make_stream_bridge() as bridge:
        app.state.stream_bridge = bridge
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from deerflow.config.stream_bridge_config import get_stream_bridge_config

from .base import StreamBridge

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def make_stream_bridge(config=None) -> AsyncIterator[StreamBridge]:
    """Async context manager that yields a :class:`StreamBridge`.

    Falls back to :class:`MemoryStreamBridge` when no configuration is
    provided and nothing is set globally.
    """
    if config is None:
        config = get_stream_bridge_config()

    if config is None or config.type == "memory":
        from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

        maxsize = config.queue_maxsize if config is not None else 256
        bridge = MemoryStreamBridge(queue_maxsize=maxsize)
        logger.info("Stream bridge initialised: memory (queue_maxsize=%d)", maxsize)
        try:
            yield bridge
        finally:
            await bridge.close()
        return

    if config.type == "redis":
        if not config.redis_url or not str(config.redis_url).strip():
            raise ValueError("stream_bridge.redis_url is required when stream_bridge.type is 'redis'")
        from deerflow.runtime.stream_bridge.redis import RedisStreamBridge

        bridge = RedisStreamBridge(
            redis_url=str(config.redis_url).strip(),
            queue_maxsize=config.queue_maxsize,
            key_prefix=(config.redis_key_prefix or "deerflow:sse").strip(),
        )
        logger.info("Stream bridge initialised: redis (%s)", config.redis_url.split("@")[-1] if "@" in config.redis_url else config.redis_url)
        try:
            yield bridge
        finally:
            await bridge.close()
        return

    raise ValueError(f"Unknown stream bridge type: {config.type!r}")

"""App-owned stream bridge factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from deerflow.config.stream_bridge_config import get_stream_bridge_config
from deerflow.runtime.stream_bridge import StreamBridge

from .adapters import MemoryStreamBridge, RedisStreamBridge

logger = logging.getLogger(__name__)


def build_stream_bridge(config=None) -> AbstractAsyncContextManager[StreamBridge]:
    """Build the configured app-owned stream bridge."""
    return _build_stream_bridge_impl(config)


@asynccontextmanager
async def _build_stream_bridge_impl(config=None) -> AsyncIterator[StreamBridge]:
    if config is None:
        config = get_stream_bridge_config()

    if config is None or config.type == "memory":
        maxsize = config.queue_maxsize if config is not None else 256
        bridge = MemoryStreamBridge(queue_maxsize=maxsize)
        await bridge.start()
        logger.info("Stream bridge initialised: memory (queue_maxsize=%d)", maxsize)
        try:
            yield bridge
        finally:
            await bridge.close()
        return

    if config.type == "redis":
        if not config.redis_url:
            raise ValueError("Redis stream bridge requires redis_url")
        bridge = RedisStreamBridge(redis_url=config.redis_url)
        await bridge.start()
        logger.info("Stream bridge initialised: redis (%s)", config.redis_url)
        try:
            yield bridge
        finally:
            await bridge.close()
        return

    raise ValueError(f"Unknown stream bridge type: {config.type!r}")

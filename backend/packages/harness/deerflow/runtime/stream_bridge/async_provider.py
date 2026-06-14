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
import os
from collections.abc import AsyncIterator

from deerflow.config.app_config import AppConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig, get_stream_bridge_config

from .base import StreamBridge

logger = logging.getLogger(__name__)

_ENV_REDIS_URL = "DEER_FLOW_STREAM_BRIDGE_REDIS_URL"


def _resolve_config(app_config: AppConfig | None) -> StreamBridgeConfig | None:
    if app_config is None:
        config = get_stream_bridge_config()
    else:
        config = app_config.stream_bridge

    if config is None:
        redis_url = os.getenv(_ENV_REDIS_URL)
        if redis_url:
            return StreamBridgeConfig(type="redis", redis_url=redis_url)
    return config


def _resolve_redis_url(config: StreamBridgeConfig) -> str:
    return config.redis_url or os.getenv(_ENV_REDIS_URL) or os.getenv("REDIS_URL") or "redis://localhost:6379/0"


@contextlib.asynccontextmanager
async def make_stream_bridge(app_config: AppConfig | None = None) -> AsyncIterator[StreamBridge]:
    """Async context manager that yields a :class:`StreamBridge`.

    Falls back to :class:`MemoryStreamBridge` when no configuration is
    provided and nothing is set globally.
    """
    config = _resolve_config(app_config)

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
        from deerflow.runtime.stream_bridge.redis import RedisStreamBridge

        redis_url = _resolve_redis_url(config)
        bridge = RedisStreamBridge(
            redis_url=redis_url,
            queue_maxsize=config.queue_maxsize,
            max_connections=config.max_connections,
        )
        logger.info(
            "Stream bridge initialised: redis (queue_maxsize=%d, max_connections=%s)",
            config.queue_maxsize,
            config.max_connections,
        )
        try:
            yield bridge
        finally:
            await bridge.close()
        return

    raise ValueError(f"Unknown stream bridge type: {config.type!r}")

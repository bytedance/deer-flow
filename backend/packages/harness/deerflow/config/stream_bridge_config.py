"""Configuration for stream bridge."""

from typing import Literal

from pydantic import BaseModel, Field

StreamBridgeType = Literal["memory", "redis"]


class StreamBridgeConfig(BaseModel):
    """Configuration for the stream bridge that connects agent workers to SSE endpoints."""

    type: StreamBridgeType = Field(
        default="memory",
        description="Stream bridge backend type. 'memory' uses an in-process event log (single-process only). 'redis' uses Redis Streams for multi-worker Docker deployments.",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis stream bridge type. If omitted, DEER_FLOW_STREAM_BRIDGE_REDIS_URL, REDIS_URL, or redis://localhost:6379/0 is used.",
    )
    queue_maxsize: int = Field(
        default=256,
        description="Maximum number of events retained per run (memory bridge queue size / redis stream MAXLEN).",
    )
    max_connections: int | None = Field(
        default=None,
        description=(
            "Max Redis connections in the pool for the redis stream bridge. Each live SSE "
            "client holds one connection blocked in XREAD ... BLOCK for up to heartbeat_interval "
            "(15s), so hundreds of concurrent clients open hundreds of connections. Leave unset "
            "for redis-py's default (effectively unbounded), or set a ceiling sized for peak "
            "concurrent SSE clients. Only applies to the redis bridge."
        ),
    )


# Global configuration instance — None means no stream bridge is configured
# (falls back to memory with defaults).
_stream_bridge_config: StreamBridgeConfig | None = None


def get_stream_bridge_config() -> StreamBridgeConfig | None:
    """Get the current stream bridge configuration, or None if not configured."""
    return _stream_bridge_config


def set_stream_bridge_config(config: StreamBridgeConfig | None) -> None:
    """Set the stream bridge configuration."""
    global _stream_bridge_config
    _stream_bridge_config = config


def load_stream_bridge_config_from_dict(config_dict: dict | None) -> None:
    """Load stream bridge configuration from a dictionary."""
    global _stream_bridge_config
    if config_dict is None:
        _stream_bridge_config = None
        return
    _stream_bridge_config = StreamBridgeConfig(**config_dict)

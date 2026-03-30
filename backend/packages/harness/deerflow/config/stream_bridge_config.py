"""Configuration for stream bridge."""

from typing import Literal

from pydantic import BaseModel, Field

StreamBridgeType = Literal["memory", "redis"]


class StreamBridgeConfig(BaseModel):
    """Configuration for the stream bridge that connects agent workers to SSE endpoints."""

    type: StreamBridgeType = Field(
        default="memory",
        description="Stream bridge backend type. 'memory' uses in-process asyncio.Queue (single-process only). 'redis' uses Redis Streams (planned for Phase 2, not yet implemented).",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis stream bridge type. Example: 'redis://localhost:6379/0'.",
    )
    queue_maxsize: int = Field(
        default=256,
        description="Maximum number of events buffered per run in the memory bridge.",
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


def load_stream_bridge_config_from_dict(config_dict: dict) -> None:
    """Load stream bridge configuration from a dictionary."""
    global _stream_bridge_config
    _stream_bridge_config = StreamBridgeConfig(**config_dict)

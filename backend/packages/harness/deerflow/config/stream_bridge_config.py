"""Configuration for stream bridge."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

StreamBridgeType = Literal["memory", "redis"]


class StreamBridgeConfig(BaseModel):
    """Configuration for the stream bridge that connects agent workers to SSE endpoints."""

    type: StreamBridgeType = Field(
        default="memory",
        description="Stream bridge backend type. 'memory' uses in-process asyncio.Queue (single-process only). 'redis' uses Redis Streams for multi-worker / multi-replica deployments.",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis stream bridge type. Required when type=redis. Example: 'redis://localhost:6379/0'. Environment variables use the '$REDIS_URL' form.",
    )
    queue_maxsize: int = Field(
        default=256,
        gt=0,
        description="Maximum number of events retained per run (approximate MAXLEN for redis).",
    )
    redis_max_command_connections: int = Field(
        default=64,
        gt=0,
        description="Command connection pool size, serving publish/cleanup/refresh_ttl/boundary probes. Isolated from the blocking subscribe pool so SSE subscriptions cannot starve publishes.",
    )
    redis_max_blocking_connections: int = Field(
        default=1024,
        gt=0,
        description="Blocking subscribe connection pool size; each active SSE subscription consumes one connection. Size by single-process peak SSE concurrency.",
    )
    redis_pool_timeout: float = Field(
        default=1.0,
        gt=0,
        description="Fail fast after waiting this many seconds for a connection from either pool.",
    )
    redis_socket_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Socket timeout for command connections. Blocking subscribe connections use heartbeat_interval + buffer instead.",
    )
    redis_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        description="Fallback key expiry when cleanup is missed. Must exceed the worker cleanup delay (60s). Default 24h so long-idle runs are not dropped.",
    )
    redis_max_payload_bytes: int = Field(
        default=524288,
        gt=0,
        description="Maximum serialized event payload size allowed into Redis. Oversized events are rejected (dropped for data events) and logged.",
    )
    redis_key_prefix: str = Field(
        default="df:sb",
        description="Redis key prefix for stream keys.",
    )
    redis_require_tls: bool = Field(
        default=False,
        description="When true, only rediss:// URLs are accepted.",
    )

    @model_validator(mode="after")
    def _validate_redis(self) -> "StreamBridgeConfig":
        if self.type != "redis":
            return self
        if not self.redis_url:
            raise ValueError("redis_url is required when stream_bridge.type=redis")
        if self.redis_ttl_seconds < 60:
            raise ValueError("redis_ttl_seconds must be >= 60 (greater than worker cleanup delay)")
        if self.redis_require_tls and not self.redis_url.startswith("rediss://"):
            raise ValueError("redis_require_tls=true requires a rediss:// URL")
        return self


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

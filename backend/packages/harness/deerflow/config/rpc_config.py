"""Configuration for Java RPC client."""

from pydantic import BaseModel, Field


class RpcEndpointConfig(BaseModel):
    """Configuration for a single RPC endpoint on a Java service."""

    method: str = Field(..., description="Logical method name used when calling via RPC client")
    path: str = Field(..., description="HTTP path template (e.g. /api/user/{id})")
    http_method: str = Field(
        default="POST",
        description="HTTP method: GET, POST, PUT, or DELETE",
    )


class RpcRetryConfig(BaseModel):
    """Retry configuration for RPC calls."""

    max_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts (0 = no retry)",
    )
    backoff_factor: float = Field(
        default=0.5,
        ge=0.1,
        description="Backoff multiplier for retry delays",
    )


class RpcServiceConfig(BaseModel):
    """Configuration for a single Java RPC service."""

    name: str = Field(..., description="Logical service name for RPC client lookup")
    discovery: str | None = Field(
        default=None,
        description="Nacos service name for discovery (mutually exclusive with base_url)",
    )
    base_url: str | None = Field(
        default=None,
        description="Direct base URL when not using Nacos discovery (mutually exclusive with discovery)",
    )
    timeout: float | None = Field(
        default=None,
        ge=0.1,
        description="Per-service timeout override in seconds",
    )
    retry: RpcRetryConfig | None = Field(
        default=None,
        description="Per-service retry configuration override",
    )
    endpoints: list[RpcEndpointConfig] = Field(
        default_factory=list,
        description="Configured RPC endpoints for this service",
    )


class RpcConfig(BaseModel):
    """Configuration for the Java RPC client.

    When set to None in AppConfig, the RPC client is disabled.
    """

    default_timeout: float = Field(
        default=30.0,
        ge=1.0,
        description="Default request timeout in seconds",
    )
    default_retry: RpcRetryConfig = Field(
        default_factory=RpcRetryConfig,
        description="Default retry configuration for all services",
    )
    services: list[RpcServiceConfig] = Field(
        default_factory=list,
        description="Configured Java RPC services",
    )


# Global configuration instance (singleton pattern matching MemoryConfig etc.)
_rpc_config: RpcConfig | None = None


def get_rpc_config() -> RpcConfig | None:
    """Get the current RPC configuration.

    Returns None if RPC is not configured (disabled).
    """
    return _rpc_config


def load_rpc_config_from_dict(config_dict: dict | None) -> None:
    """Load RPC configuration from a dictionary.

    Pass None to disable the RPC client.
    """
    global _rpc_config
    if config_dict is None:
        _rpc_config = None
    else:
        _rpc_config = RpcConfig(**config_dict)

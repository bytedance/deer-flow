"""Configuration for Nacos service discovery."""

from pydantic import BaseModel, Field


class NacosServiceConfig(BaseModel):
    """Service instance configuration for Nacos registration."""

    name: str = Field(
        default="deer-flow-gateway",
        description="Service name registered in Nacos",
    )
    ip: str = Field(
        default="",
        description="Service IP address (empty = auto-detect from host)",
    )
    port: int = Field(
        default=8001,
        ge=1,
        le=65535,
        description="Service port",
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=100.0,
        description="Instance weight for load balancing",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Additional metadata key-value pairs",
    )


class NacosHeartbeatConfig(BaseModel):
    """Heartbeat configuration for Nacos."""

    interval: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Heartbeat interval in seconds",
    )
    timeout: int = Field(
        default=15,
        ge=5,
        le=60,
        description="Instance expiration timeout in seconds on Nacos side",
    )


class NacosRetryConfig(BaseModel):
    """Retry configuration for Nacos registration."""

    max_attempts: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Maximum registration retry attempts (0 = no retry)",
    )
    base_delay: float = Field(
        default=1.0,
        ge=0.1,
        description="Base delay in seconds for exponential backoff",
    )
    max_delay: float = Field(
        default=60.0,
        ge=1.0,
        description="Maximum delay in seconds for exponential backoff",
    )


class NacosConfig(BaseModel):
    """Configuration for Nacos service discovery.

    When set to None in AppConfig, the entire Nacos module is disabled.
    """

    server_addr: str = Field(
        default="127.0.0.1:8848",
        description="Nacos server address (host:port). Supports $ENV_VAR syntax.",
    )
    namespace: str = Field(
        default="",
        description="Nacos namespace ID (empty = public namespace)",
    )
    group: str = Field(
        default="DEFAULT_GROUP",
        description="Nacos service group name",
    )
    service: NacosServiceConfig = Field(
        default_factory=NacosServiceConfig,
        description="Service instance registration parameters",
    )
    heartbeat: NacosHeartbeatConfig = Field(
        default_factory=NacosHeartbeatConfig,
        description="Heartbeat configuration",
    )
    retry: NacosRetryConfig = Field(
        default_factory=NacosRetryConfig,
        description="Retry configuration for registration",
    )


# Global configuration instance (singleton pattern matching MemoryConfig etc.)
_nacos_config: NacosConfig | None = None


def get_nacos_config() -> NacosConfig | None:
    """Get the current Nacos configuration.

    Returns None if Nacos is not configured (disabled).
    """
    return _nacos_config


def load_nacos_config_from_dict(config_dict: dict | None) -> None:
    """Load Nacos configuration from a dictionary.

    Pass None to disable Nacos service discovery.
    """
    global _nacos_config
    if config_dict is None:
        _nacos_config = None
    else:
        _nacos_config = NacosConfig(**config_dict)

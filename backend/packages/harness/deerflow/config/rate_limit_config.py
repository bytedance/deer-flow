"""Rate limiting configuration for the DeerFlow Gateway API."""

from pydantic import BaseModel, Field


class EndpointLimit(BaseModel):
    """Per-endpoint rate limit override."""

    path: str = Field(description="URL path prefix to match (e.g. '/api/rag/search')")
    limit: str = Field(description="Rate limit string (e.g. '30/minute')")


class RateLimitConfig(BaseModel):
    """Configuration for API rate limiting.

    Uses ``slowapi`` with an in-memory backend by default; Redis is
    supported for distributed deployments.
    """

    enabled: bool = Field(default=False, description="Enable rate limiting middleware")
    backend: str = Field(default="memory", description="Rate limit storage backend ('memory' or 'redis')")
    redis_url: str = Field(default="", description="Redis connection URL (required when backend='redis')")
    global_per_minute: int = Field(default=1000, description="Global requests per minute")
    tenant_per_minute: int = Field(default=100, description="Per-tenant requests per minute")
    user_per_minute: int = Field(default=60, description="Per-user requests per minute")
    llm_calls_per_minute: int = Field(default=50, description="LLM API calls per minute per tenant")
    tokens_per_minute: int = Field(default=100000, description="Tokens per minute per tenant")
    endpoints: list[EndpointLimit] = Field(default_factory=list, description="Per-endpoint rate limit overrides")


_rate_limit_config: RateLimitConfig | None = None


def get_rate_limit_config() -> RateLimitConfig:
    """Get the rate limit config, returning defaults if not loaded."""
    global _rate_limit_config
    if _rate_limit_config is None:
        _rate_limit_config = RateLimitConfig()
    return _rate_limit_config


def load_rate_limit_config_from_dict(data: dict) -> RateLimitConfig:
    """Load rate limit config from a dict (called during AppConfig loading)."""
    global _rate_limit_config
    _rate_limit_config = RateLimitConfig.model_validate(data)
    return _rate_limit_config


def reset_rate_limit_config() -> None:
    """Reset the cached config instance. Used in tests to prevent singleton leaks."""
    global _rate_limit_config
    _rate_limit_config = None

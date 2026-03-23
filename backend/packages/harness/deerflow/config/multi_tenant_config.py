"""Multi-tenant authentication configuration.

This module defines the configuration for DeerFlow's multi-tenant mode.
When multi-tenant is disabled, authentication is optional and all requests
use a default user.
"""

import os
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class UserRole(StrEnum):
    """User roles for multi-tenant authentication."""

    USER = "user"
    ADMIN = "admin"


class MultiTenantConfig(BaseModel):
    """Configuration for multi-tenant authentication."""

    enabled: bool = Field(default=False, description="Enable multi-tenant mode")
    jwt_secret: str | None = Field(
        default=None,
        description="JWT secret key for token signing (or set DEER_FLOW_JWT_SECRET env var)",
    )
    token_expire_minutes: int = Field(
        default=60 * 24 * 7,  # 7 days (RFC-001 compliant)
        description="JWT token expiration time in minutes",
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm (HS256 or RS256)")
    default_user_id: str = Field(
        default="default",
        description="Default user ID for unauthenticated requests in single-tenant mode",
    )

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def resolve_jwt_secret(cls, v: str | None) -> str | None:
        """Resolve JWT secret from value or environment variable."""
        if v is not None:
            return v
        return os.getenv("DEER_FLOW_JWT_SECRET")

    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, v: str) -> str:
        """Validate JWT algorithm."""
        allowed = {"HS256", "RS256"}
        if v not in allowed:
            raise ValueError(f"JWT algorithm must be one of {allowed}, got {v}")
        return v


_multi_tenant_config: MultiTenantConfig | None = None


def load_multi_tenant_config_from_dict(config_data: dict[str, Any] | None) -> MultiTenantConfig:
    """Load multi-tenant config from dictionary.

    Args:
        config_data: Configuration dictionary with multi_tenant settings

    Returns:
        MultiTenantConfig instance
    """
    global _multi_tenant_config
    if config_data is None:
        config_data = {}
    _multi_tenant_config = MultiTenantConfig.model_validate(config_data)
    return _multi_tenant_config


def get_multi_tenant_config() -> MultiTenantConfig:
    """Get the multi-tenant config instance.

    Returns:
        MultiTenantConfig: The cached config instance.

    Raises:
        RuntimeError: If config has not been loaded.
    """
    if _multi_tenant_config is None:
        # Return default config if not loaded
        return MultiTenantConfig()
    return _multi_tenant_config


def reset_multi_tenant_config() -> None:
    """Reset the cached multi-tenant config instance."""
    global _multi_tenant_config
    _multi_tenant_config = None

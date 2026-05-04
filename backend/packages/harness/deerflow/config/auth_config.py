"""Authentication configuration for the DeerFlow Gateway API."""

from pydantic import BaseModel, Field


class AuthConfig(BaseModel):
    """Configuration for API authentication (JWT + API Key).

    When ``enabled`` is False (default), the auth middleware falls back to
    the existing tenant-header extraction behaviour for full backward
    compatibility.
    """

    enabled: bool = Field(default=False, description="Enable authentication middleware")
    jwt_secret: str = Field(default="", description="Secret key for JWT signing/verification")
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_expire_minutes: int = Field(default=1440, description="JWT token expiry in minutes (default: 24h)")
    api_key_enabled: bool = Field(default=True, description="Enable API Key authentication")
    admin_username: str = Field(default="admin", description="Default admin username for MVP")
    admin_password_hash: str = Field(default="", description="Bcrypt hash of the admin password")


_auth_config: AuthConfig | None = None


def get_auth_config() -> AuthConfig:
    """Get the auth config, returning defaults if not loaded."""
    global _auth_config
    if _auth_config is None:
        _auth_config = AuthConfig()
    return _auth_config


def load_auth_config_from_dict(data: dict) -> AuthConfig:
    """Load auth config from a dict (called during AppConfig loading)."""
    global _auth_config
    _auth_config = AuthConfig.model_validate(data)
    return _auth_config


def reset_auth_config() -> None:
    """Reset the cached config instance. Used in tests to prevent singleton leaks."""
    global _auth_config
    _auth_config = None

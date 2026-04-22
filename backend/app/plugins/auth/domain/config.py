"""Auth configuration schema and environment loader."""

from __future__ import annotations

import logging
import os
import secrets

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)


class AuthConfig(BaseModel):
    """JWT and auth-related configuration."""

    jwt_secret: str = Field(..., description="Secret key for JWT signing. MUST be set via AUTH_JWT_SECRET.")
    token_expiry_days: int = Field(default=7, ge=1, le=30)
    oauth_github_client_id: str | None = Field(default=None)
    oauth_github_client_secret: str | None = Field(default=None)


def load_auth_config_from_env() -> AuthConfig:
    """Build an auth config from environment variables."""

    jwt_secret = os.environ.get("AUTH_JWT_SECRET")
    if not jwt_secret:
        jwt_secret = secrets.token_urlsafe(32)
        os.environ["AUTH_JWT_SECRET"] = jwt_secret
        logger.warning(
            "⚠ AUTH_JWT_SECRET is not set — using an auto-generated ephemeral secret. "
            "Sessions will be invalidated on restart. "
            "For production, add AUTH_JWT_SECRET to your .env file: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    return AuthConfig(jwt_secret=jwt_secret)


__all__ = ["AuthConfig", "load_auth_config_from_env"]

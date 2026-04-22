"""Authentication configuration for DeerFlow."""

import hmac
import ipaddress
import logging
import os
import secrets
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)


class TrustedHeaderProviderConfig(BaseModel):
    """Config for trusted reverse-proxy header authentication."""

    enabled: bool = Field(default=False)
    trusted_networks: list[str] = Field(default_factory=list)
    user_id_header: str = Field(default="X-Forwarded-User")
    legacy_user_id_headers: list[str] = Field(default_factory=list)
    hmac_secret_env: str | None = Field(default=None)
    hmac_signature_header: str = Field(default="X-Forwarded-User-Signature")

    def validate_trusted_networks(self) -> None:
        if self.enabled and not self.trusted_networks:
            raise ValueError("trusted_header.trusted_networks must be non-empty when trusted header auth is enabled")
        for cidr in self.trusted_networks:
            ipaddress.ip_network(cidr, strict=False)

    def get_hmac_secret(self) -> str | None:
        if not self.hmac_secret_env:
            return None
        value = os.environ.get(self.hmac_secret_env)
        return value.strip() if value and value.strip() else None

    def verify_hmac(self, user_id: str, signature: str | None) -> bool:
        secret = self.get_hmac_secret()
        if not secret:
            return True
        if not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), user_id.encode("utf-8"), "sha256").hexdigest()
        return hmac.compare_digest(expected, signature)


class AuthConfig(BaseModel):
    """JWT and auth-related configuration. Parsed once at startup.

    Note: the ``users`` table now lives in the shared persistence
    database managed by ``deerflow.persistence.engine``. The old
    ``users_db_path`` config key has been removed — user storage is
    configured through ``config.database`` like every other table.
    """

    provider: Literal["local", "trusted_header"] = Field(default="local")
    jwt_secret: str = Field(
        ...,
        description="Secret key for JWT signing. MUST be set via AUTH_JWT_SECRET.",
    )
    token_expiry_days: int = Field(default=7, ge=1, le=30)
    oauth_github_client_id: str | None = Field(default=None)
    oauth_github_client_secret: str | None = Field(default=None)
    trusted_header: TrustedHeaderProviderConfig = Field(default_factory=TrustedHeaderProviderConfig)

    def validate_provider_config(self) -> None:
        self.trusted_header.validate_trusted_networks()
        if self.provider == "trusted_header":
            self.trusted_header.enabled = True
        if self.provider == "trusted_header" and not self.trusted_header.trusted_networks:
            raise ValueError("auth.provider='trusted_header' requires non-empty trusted_header.trusted_networks")


_auth_config: AuthConfig | None = None


def get_auth_config() -> AuthConfig:
    """Get the global AuthConfig instance. Parses from env on first call."""
    global _auth_config
    if _auth_config is None:
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
        provider = (os.environ.get("AUTH_PROVIDER_TYPE") or "local").strip() or "local"
        _auth_config = AuthConfig(jwt_secret=jwt_secret, provider=provider)
        _auth_config.validate_provider_config()
    return _auth_config


def set_auth_config(config: AuthConfig) -> None:
    """Set the global AuthConfig instance (for testing)."""
    global _auth_config
    config.validate_provider_config()
    _auth_config = config

"""Authentication configuration for DeerFlow."""

import logging
import os
import secrets

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuthConfig(BaseModel):
    """JWT and auth-related configuration. Parsed once at startup.

    Note: the ``users`` table now lives in the shared persistence
    database managed by ``deerflow.persistence.engine``. The old
    ``users_db_path`` config key has been removed — user storage is
    configured through ``config.database`` like every other table.
    """

    jwt_secret: str = Field(
        ...,
        description="Secret key for JWT signing. MUST be set via AUTH_JWT_SECRET.",
    )
    token_expiry_days: int = Field(default=7, ge=1, le=30)
    oauth_github_client_id: str | None = Field(default=None)
    oauth_github_client_secret: str | None = Field(default=None)


_auth_config: AuthConfig | None = None


def get_auth_config() -> AuthConfig:
    """Get the global AuthConfig instance. Parses from env on first call.

    When ``AUTH_JWT_SECRET`` is not set in the environment, a random secret
    is generated and persisted to ``.deer-flow/jwt_secret`` so that sessions
    survive process restarts (e.g. uvicorn --reload in dev mode).
    """
    global _auth_config
    if _auth_config is None:
        from dotenv import load_dotenv

        load_dotenv()
        jwt_secret = os.environ.get("AUTH_JWT_SECRET")
        if not jwt_secret:
            logger.warning(
                "AUTH_JWT_SECRET is not set; falling back to a persisted or generated local development secret."
            )
            jwt_secret = _load_or_generate_jwt_secret()
            os.environ["AUTH_JWT_SECRET"] = jwt_secret
        _auth_config = AuthConfig(jwt_secret=jwt_secret)
    return _auth_config


def _jwt_secret_file() -> str:
    """Path to the persisted JWT secret file."""
    from deerflow.config.runtime_paths import runtime_home

    return os.path.join(runtime_home(), "jwt_secret")


def _load_or_generate_jwt_secret() -> str:
    """Load a persisted JWT secret, or generate and persist a new one."""
    secret_path = _jwt_secret_file()
    try:
        with open(secret_path, "r") as f:
            existing = f.read().strip()
            if existing:
                logger.info("Loaded persisted JWT secret from %s", secret_path)
                return existing
    except FileNotFoundError:
        pass

    jwt_secret = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(secret_path), exist_ok=True)
    with open(secret_path, "w") as f:
        f.write(jwt_secret)
    logger.warning(
        "AUTH_JWT_SECRET is not set — generated and persisted to %s. "
        "For production, set AUTH_JWT_SECRET in your .env file: "
        'python -c "import secrets; print(secrets.token_urlsafe(32))"',
        secret_path,
    )
    return jwt_secret


def set_auth_config(config: AuthConfig) -> None:
    """Set the global AuthConfig instance (for testing)."""
    global _auth_config
    _auth_config = config

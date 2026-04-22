"""Runtime state holder for auth configuration."""

from __future__ import annotations

from app.plugins.auth.domain.config import AuthConfig, load_auth_config_from_env

_auth_config: AuthConfig | None = None


def get_auth_config() -> AuthConfig:
    global _auth_config
    if _auth_config is None:
        _auth_config = load_auth_config_from_env()
    return _auth_config


def set_auth_config(config: AuthConfig) -> None:
    global _auth_config
    _auth_config = config


def reset_auth_config() -> None:
    global _auth_config
    _auth_config = None


__all__ = ["get_auth_config", "reset_auth_config", "set_auth_config"]

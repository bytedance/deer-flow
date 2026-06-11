"""Shared helpers for local/E2E auth-disabled mode."""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

from deerflow.runtime.user_context import DEFAULT_USER_ID

AUTH_DISABLED_ENV_VAR = "DEER_FLOW_AUTH_DISABLED"
AUTH_DISABLED_USER_ID = DEFAULT_USER_ID
AUTH_DISABLED_USER_EMAIL = "default@test.local"

AUTH_SOURCE_SESSION = "session"
AUTH_SOURCE_INTERNAL = "internal"
AUTH_SOURCE_AUTH_DISABLED = "auth_disabled"

_PRODUCTION_ENV_VARS: tuple[str, ...] = ("DEER_FLOW_ENV", "ENVIRONMENT")
_PRODUCTION_ENV_VALUES: frozenset[str] = frozenset({"prod", "production"})

logger = logging.getLogger(__name__)


def is_explicit_production_environment() -> bool:
    return any(os.environ.get(name, "").strip().lower() in _PRODUCTION_ENV_VALUES for name in _PRODUCTION_ENV_VARS)


def is_auth_disabled_requested() -> bool:
    return os.environ.get(AUTH_DISABLED_ENV_VAR) == "1"


def is_auth_disabled() -> bool:
    return is_auth_disabled_requested() and not is_explicit_production_environment()


def warn_if_auth_disabled_enabled() -> None:
    if not is_auth_disabled():
        return

    logger.warning(
        "%s=1 is active: authentication is bypassed and anonymous requests run as synthetic admin user %r. Do not enable this in shared or production deployments.",
        AUTH_DISABLED_ENV_VAR,
        AUTH_DISABLED_USER_ID,
    )


def get_auth_disabled_user():
    return SimpleNamespace(
        id=AUTH_DISABLED_USER_ID,
        email=AUTH_DISABLED_USER_EMAIL,
        password_hash=None,
        system_role="admin",
        needs_setup=False,
        token_version=0,
        oauth_provider=None,
    )

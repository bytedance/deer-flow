"""Shared helpers for local/E2E auth-disabled mode."""

from __future__ import annotations

import os
from types import SimpleNamespace

AUTH_DISABLED_ENV_VAR = "DEER_FLOW_AUTH_DISABLED"
AUTH_DISABLED_USER_ID = "e2e-user"
AUTH_DISABLED_USER_EMAIL = "e2e@test.local"


def is_auth_disabled() -> bool:
    return os.environ.get(AUTH_DISABLED_ENV_VAR) == "1"


def get_auth_disabled_user():
    return SimpleNamespace(
        id=AUTH_DISABLED_USER_ID,
        email=AUTH_DISABLED_USER_EMAIL,
        password_hash=None,
        system_role="admin",
        needs_setup=False,
        token_version=0,
    )

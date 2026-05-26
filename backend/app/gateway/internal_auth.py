"""Shared-token authentication for Gateway internal callers."""

from __future__ import annotations

import os
import secrets
from types import SimpleNamespace

from deerflow.runtime.user_context import DEFAULT_USER_ID

INTERNAL_AUTH_HEADER_NAME = "X-DeerFlow-Internal-Token"
INTERNAL_AUTH_TOKEN_ENV = "DEER_FLOW_INTERNAL_AUTH_TOKEN"
_INTERNAL_AUTH_TOKEN = os.getenv(INTERNAL_AUTH_TOKEN_ENV) or secrets.token_urlsafe(32)


def create_internal_auth_headers() -> dict[str, str]:
    """Return headers that authenticate trusted Gateway internal calls."""
    return {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches the configured internal token."""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def get_internal_user():
    """Return the synthetic user used for trusted internal channel calls."""
    return SimpleNamespace(id=DEFAULT_USER_ID, system_role="internal")

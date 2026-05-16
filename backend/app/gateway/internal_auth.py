"""Authentication for Gateway internal callers.

The internal token defaults to a freshly-generated process-local secret so
same-process callers (e.g. background workers in this gateway) authenticate
out of the box. When ``DEERFLOW_INTERNAL_TOKEN`` is set in the environment,
it is used instead — letting trusted external services (e.g. the AlphaFRS
backend dispatching research jobs) present the same shared secret over the
network.
"""

from __future__ import annotations

import os
import secrets
from types import SimpleNamespace

from deerflow.runtime.user_context import DEFAULT_USER_ID

INTERNAL_AUTH_HEADER_NAME = "X-DeerFlow-Internal-Token"
_INTERNAL_AUTH_TOKEN = os.environ.get("DEERFLOW_INTERNAL_TOKEN") or secrets.token_urlsafe(32)


def create_internal_auth_headers() -> dict[str, str]:
    """Return headers that authenticate same-process Gateway internal calls."""
    return {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches the process-local internal token."""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def get_internal_user():
    """Return the synthetic user used for trusted internal channel calls."""
    return SimpleNamespace(id=DEFAULT_USER_ID, system_role="internal")

"""Process-local authentication for Gateway internal callers."""

from __future__ import annotations

import secrets
from types import SimpleNamespace

from deerflow.runtime.user_context import DEFAULT_USER_ID

INTERNAL_AUTH_HEADER_NAME = "X-DeerFlow-Internal-Token"
# Header used by trusted internal callers (e.g. IM channel workers) to act on
# behalf of an end user that exists in an external system (e.g. a Feishu
# ``open_id``). The Gateway auth middleware only honours this header when the
# internal-auth token has already been validated, so external clients cannot
# spoof another user via this header. See ``app.gateway.auth_middleware``.
ACTING_USER_HEADER_NAME = "X-DeerFlow-Acting-User"
_INTERNAL_AUTH_TOKEN = secrets.token_urlsafe(32)


def create_internal_auth_headers(acting_user_id: str | None = None) -> dict[str, str]:
    """Return headers that authenticate same-process Gateway internal calls.

    If ``acting_user_id`` is provided, also include the acting-user header so
    that downstream code paths see the real end user instead of the synthetic
    internal user. The Gateway auth middleware only trusts this header when
    paired with a valid internal-auth token.
    """
    headers = {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}
    if acting_user_id:
        headers[ACTING_USER_HEADER_NAME] = acting_user_id
    return headers


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches the process-local internal token."""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def get_internal_user():
    """Return the synthetic user used for trusted internal channel calls."""
    return SimpleNamespace(id=DEFAULT_USER_ID, system_role="internal")


def make_acting_internal_user(acting_user_id: str):
    """Return a synthetic user representing a real end user via internal-auth.

    Used when a trusted internal caller (validated via internal-auth token)
    forwards a request on behalf of a platform-specific user id such as a
    Feishu ``open_id``. The returned object is structurally compatible with
    the ``deerflow.runtime.user_context.CurrentUser`` protocol via ``.id``.
    """
    return SimpleNamespace(id=acting_user_id, system_role="internal-on-behalf-of")

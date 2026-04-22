"""Authorization layer for the auth plugin."""

from app.plugins.auth.authorization.authentication import get_auth_context
from app.plugins.auth.authorization.hooks import (
    AuthzHooks,
    build_authz_hooks,
    build_permission_provider,
    build_policy_chain_builder,
    get_authz_hooks,
    get_default_authz_hooks,
)
from app.plugins.auth.authorization.types import (
    AuthContext,
    Permissions,
    ALL_PERMISSIONS,
)

_ALL_PERMISSIONS = ALL_PERMISSIONS

__all__ = [
    "AuthContext",
    "AuthzHooks",
    "Permissions",
    "_ALL_PERMISSIONS",
    "build_authz_hooks",
    "build_permission_provider",
    "build_policy_chain_builder",
    "get_auth_context",
    "get_authz_hooks",
    "get_default_authz_hooks",
]

"""Auth-plugin authz extension hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.plugins.auth.authorization.providers import PermissionProvider, default_permission_provider
from app.plugins.auth.authorization.registry import PolicyChainBuilder, build_default_policy_evaluators


@dataclass(frozen=True)
class AuthzHooks:
    """Extension hooks for permission and policy resolution."""

    permission_provider: PermissionProvider = default_permission_provider
    policy_chain_builder: PolicyChainBuilder = build_default_policy_evaluators


DEFAULT_AUTHZ_HOOKS = AuthzHooks()


def get_default_authz_hooks() -> AuthzHooks:
    return DEFAULT_AUTHZ_HOOKS


def get_authz_hooks(request: Request | Any | None = None) -> AuthzHooks:
    if request is not None:
        app = getattr(request, "app", None)
        state = getattr(app, "state", None)
        hooks = getattr(state, "authz_hooks", None)
        if isinstance(hooks, AuthzHooks):
            return hooks
    return DEFAULT_AUTHZ_HOOKS


def build_permission_provider() -> PermissionProvider:
    return default_permission_provider


def build_policy_chain_builder() -> PolicyChainBuilder:
    return build_default_policy_evaluators


def build_authz_hooks() -> AuthzHooks:
    return AuthzHooks(
        permission_provider=build_permission_provider(),
        policy_chain_builder=build_policy_chain_builder(),
    )


__all__ = [
    "AuthzHooks",
    "DEFAULT_AUTHZ_HOOKS",
    "build_authz_hooks",
    "build_permission_provider",
    "build_policy_chain_builder",
    "get_authz_hooks",
    "get_default_authz_hooks",
]

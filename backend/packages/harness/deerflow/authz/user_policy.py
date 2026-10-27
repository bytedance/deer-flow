"""Exact per-user grants, re-evaluated at each tool execution."""

import asyncio

from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.security.defaults import is_default_resource
from deerflow.security.store import UserSecurityStore

PROVIDER_PATH = "deerflow.authz.user_policy:UserAuthorizationProvider"


def user_security_enabled():
    from deerflow.config.app_config import get_app_config

    config = get_app_config().authorization
    return config.enabled and config.provider is not None and config.provider.use == PROVIDER_PATH


def get_user_security_store():
    from deerflow.config.app_config import get_app_config

    config = get_app_config().authorization
    path = config.provider.config.get("store_path") if config.provider else None
    return UserSecurityStore(path)


class UserAuthorizationProvider:
    name = "user-grants"

    def __init__(self, *, store_path=None):
        # Construction must remain I/O-free; async callers offload decisions.
        self.store = UserSecurityStore(store_path)

    @staticmethod
    def _allowed(principal, resource, target, grants):
        if not principal.user_id or principal.user_id == "default" or principal.role not in {"admin", "user"}:
            return False
        if principal.role == "admin":
            return True
        if is_default_resource(resource, target):
            return True
        if resource in {"tool", "mcp_server", "sandbox", "skill"}:
            return (resource, target) in grants
        # Routes and models retain their existing ownership checks.
        return resource in {"route", "model"}

    def authorize(self, request):
        allowed = self._allowed(request.principal, request.resource, request.target, self.store.grants(request.principal.user_id))
        return AuthzDecision(allow=allowed, reasons=[AuthzReason(code="user_grants.allowed" if allowed else "user_grants.denied")], policy_id="user-grants")

    async def aauthorize(self, request):
        return await asyncio.to_thread(self.authorize, request)

    def filter_resources(self, principal, resource_type, candidates):
        grants = self.store.grants(principal.user_id)
        return [target for target in candidates if self._allowed(principal, resource_type, target, grants)]

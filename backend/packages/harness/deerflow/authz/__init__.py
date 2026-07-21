"""Pluggable fine-grained authorization (resource-level RBAC and beyond)."""

from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.principal import build_principal_from_context, normalize_authz_attributes
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzReason, AuthzRequest, Principal
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.authz.runtime import resolve_authorization_provider

__all__ = [
    "AuthzDecision",
    "AuthzReason",
    "AuthzRequest",
    "AuthorizationProvider",
    "GuardrailAuthorizationAdapter",
    "Principal",
    "RbacAuthorizationProvider",
    "build_principal_from_context",
    "normalize_authz_attributes",
    "resolve_authorization_provider",
]

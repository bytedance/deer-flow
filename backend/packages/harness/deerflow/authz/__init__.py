"""Pluggable fine-grained authorization (resource-level RBAC and beyond)."""

from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.principal import build_principal_from_context, normalize_authz_attributes
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzReason, AuthzRequest, Principal

__all__ = [
    "AuthzDecision",
    "AuthzReason",
    "AuthzRequest",
    "AuthorizationProvider",
    "GuardrailAuthorizationAdapter",
    "Principal",
    "build_principal_from_context",
    "normalize_authz_attributes",
]

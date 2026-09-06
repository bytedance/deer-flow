"""Built-in RBAC authorization provider.

Reads a role→resource policy from config and compiles it into immutable
structures at construction time. Deny always wins over allow. Unknown or
missing roles raise ``ValueError`` (not a silent allow) so that the execution
layer's ``fail_closed`` can make the final decision.

See ``docs/plans/2026-07-15-authz-phase1a-implementation-plan.md`` §3.3 for
the full semantic table.
"""

from __future__ import annotations

from typing import Any

from deerflow.authz.provider import (
    AuthzDecision,
    AuthzReason,
    AuthzRequest,
    Principal,
)

# Explicit resource-type → config-key mapping. Prevents silent mis-lookup
# when ``AuthzRequest.resource`` (singular, e.g. "tool") doesn't match the
# config key (plural, e.g. "tools").
_RESOURCE_POLICY_KEYS: dict[str, str] = {
    "tool": "tools",
    "model": "models",
    "skill": "skills",
    "sandbox": "sandbox",
    "mcp_server": "mcp_servers",
    "route": "routes",
}

_ALL = object()  # sentinel meaning "allow all candidates"
_ABSENT = object()  # sentinel meaning "key not present in dict"


# The only supported keys in a resource policy dict. Any other key (typos,
# unknown fields) is rejected at construction to prevent silent mis-grants.
_SUPPORTED_POLICY_KEYS: frozenset[str] = frozenset({"allow", "deny"})


def _require_non_empty_string(value: object, *, field: str) -> str:
    """Return a validated request identifier or raise a stable boundary error."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string, got {value!r}")
    return value


class _CompiledPolicy:
    """Immutable, pre-validated policy for a single (role, resource_type) pair."""

    __slots__ = ("allowed", "denied")

    def __init__(self, *, allowed: frozenset[str] | object, denied: frozenset[str]):
        self.allowed = allowed
        self.denied = denied

    def is_allowed(self, target: str) -> bool:
        # Deny always wins.
        if target in self.denied:
            return False
        if self.allowed is _ALL:
            return True
        return target in self.allowed


class RbacAuthorizationProvider:
    """Built-in role-based authorization provider.

    Configured via ``roles`` mapping where each role maps resource-type keys
    to ``{allow: ..., deny: [...]}`` policies. Policy configuration is fully
    validated at construction; the request path validates identifiers before
    performing membership checks.

    Policies are scoped by role, resource, and target. ``AuthzRequest.action``
    is accepted for protocol compatibility but is not a rule dimension in this
    built-in provider.

    Example config::

        roles:
          admin:
            tools: {allow: "*"}
          user:
            tools: {allow: "*", deny: ["update_agent"]}
          guest:
            tools: {allow: ["web_search", "read_file"]}
    """

    name = "rbac"

    def __init__(self, *, roles: dict[str, Any] | object = _ABSENT, **kwargs: Any) -> None:
        if kwargs:
            raise ValueError(f"unknown provider config keys {sorted(kwargs, key=repr)}; supported: ['roles']")
        if roles is _ABSENT:
            raise ValueError("missing required provider config key 'roles'")
        if not isinstance(roles, dict):
            raise ValueError(f"roles must be a dict, got {type(roles).__name__}")

        # Compile all policies up front.
        self._policies: dict[tuple[str, str], _CompiledPolicy] = {}
        self._known_roles: frozenset[str] = frozenset(roles.keys())

        for role_name, role_config in roles.items():
            if not isinstance(role_name, str) or not role_name:
                raise ValueError(f"role name must be a non-empty string, got {role_name!r}")
            if not isinstance(role_config, dict):
                raise ValueError(f"role '{role_name}' config must be a dict, got {type(role_config).__name__}")

            for resource_key, resource_policy in role_config.items():
                if not isinstance(resource_key, str) or not resource_key:
                    raise ValueError(f"role '{role_name}' has invalid resource key {resource_key!r}")
                mapped_resource_key = _RESOURCE_POLICY_KEYS.get(resource_key)
                if mapped_resource_key is not None and mapped_resource_key != resource_key:
                    raise ValueError(f"role '{role_name}' resource key '{resource_key}' is a reserved request alias; use '{mapped_resource_key}' in RBAC config")
                if not isinstance(resource_policy, dict):
                    raise ValueError(f"role '{role_name}' resource '{resource_key}' must be a dict, got {type(resource_policy).__name__}")

                compiled = self._compile_resource_policy(role_name, resource_key, resource_policy)
                self._policies[(role_name, resource_key)] = compiled

    def validate_role(self, role: str, *, field: str = "role") -> None:
        """Fail fast when an operator-configured role is not defined."""
        role = _require_non_empty_string(role, field=field)
        if role not in self._known_roles:
            if field == "role":
                raise ValueError(f"Unknown role '{role}'; known roles: {sorted(self._known_roles)}")
            raise ValueError(f"{field} '{role}' is not defined; known roles: {sorted(self._known_roles)}")

    @staticmethod
    def _compile_resource_policy(
        role_name: str,
        resource_key: str,
        policy: dict[str, Any],
    ) -> _CompiledPolicy:
        """Validate and compile a single resource policy into immutable structures.

        Distinguishes "key absent" (use default) from "key present but null"
        (invalid — reject). Unknown keys (typos) are rejected to prevent
        silent mis-grants.
        """
        # --- reject unknown keys (catch typos like "alow") ---
        unknown_keys = set(policy.keys()) - _SUPPORTED_POLICY_KEYS
        if unknown_keys:
            raise ValueError(f"role '{role_name}' resource '{resource_key}': unknown policy keys {sorted(unknown_keys, key=repr)}; supported: {sorted(_SUPPORTED_POLICY_KEYS)}")

        # --- allow ---
        raw_allow = policy.get("allow", _ABSENT)
        if raw_allow is _ABSENT:
            allowed: frozenset[str] | object = _ALL  # missing allow = allow all (deny still applies)
        elif raw_allow is None:
            raise ValueError(f"role '{role_name}' resource '{resource_key}': allow must not be null; omit the key, or use '*' / bool / list")
        elif raw_allow is True:
            allowed = _ALL
        elif raw_allow is False:
            allowed = frozenset()  # allow: false = deny all
        elif isinstance(raw_allow, str):
            if raw_allow == "*":
                allowed = _ALL
            else:
                raise ValueError(f"role '{role_name}' resource '{resource_key}': allow string must be '*', got {raw_allow!r}")
        elif isinstance(raw_allow, (list, tuple)):
            for item in raw_allow:
                if not isinstance(item, str) or not item:
                    raise ValueError(f"role '{role_name}' resource '{resource_key}': allow list contains non-string or empty item {item!r}")
            allowed = frozenset(raw_allow)
        else:
            raise ValueError(f"role '{role_name}' resource '{resource_key}': allow must be '*', bool, or list of strings, got {type(raw_allow).__name__}")

        # --- deny ---
        raw_deny = policy.get("deny", _ABSENT)
        if raw_deny is _ABSENT or raw_deny is None:
            if raw_deny is None:
                raise ValueError(f"role '{role_name}' resource '{resource_key}': deny must not be null; omit the key for no deny list")
            denied: frozenset[str] = frozenset()
        elif isinstance(raw_deny, (list, tuple)):
            for item in raw_deny:
                if not isinstance(item, str) or not item:
                    raise ValueError(f"role '{role_name}' resource '{resource_key}': deny list contains non-string or empty item {item!r}")
            denied = frozenset(raw_deny)
        else:
            raise ValueError(f"role '{role_name}' resource '{resource_key}': deny must be a list of strings, got {type(raw_deny).__name__}")

        return _CompiledPolicy(allowed=allowed, denied=denied)

    def _resolve_policy(
        self,
        principal: Principal,
        resource: str,
        *,
        resource_field: str = "resource",
    ) -> _CompiledPolicy | None:
        """Look up the compiled policy for (role, resource_type).

        Returns ``None`` if no policy is configured for this role+resource
        (meaning: unrestricted). Raises ``ValueError`` for invalid resource
        identifiers and unknown or missing roles.
        """
        role = principal.role
        if role is None or role == "":
            raise ValueError("Principal has no role; cannot evaluate RBAC policy")

        self.validate_role(role)

        resource = _require_non_empty_string(resource, field=resource_field)
        resource_key = _RESOURCE_POLICY_KEYS.get(resource, resource)
        return self._policies.get((role, resource_key))

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        """Evaluate a single authorization request."""
        policy = self._resolve_policy(request.principal, request.resource)
        target = _require_non_empty_string(request.target, field="target")
        if policy is None:
            # No policy for this role+resource → unrestricted.
            return AuthzDecision(
                allow=True,
                reasons=[AuthzReason(code="authz.no_policy", message="no policy configured")],
                policy_id="rbac:unrestricted",
            )

        if policy.is_allowed(target):
            return AuthzDecision(
                allow=True,
                reasons=[AuthzReason(code="authz.allowed")],
                policy_id="rbac:allow",
            )
        return AuthzDecision(
            allow=False,
            reasons=[
                AuthzReason(
                    code="authz.denied",
                    message=f"role '{request.principal.role}' is denied '{target}' on resource '{request.resource}'",
                )
            ],
            policy_id="rbac:deny",
        )

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        return self.authorize(request)

    def filter_resources(
        self,
        principal: Principal,
        resource_type: str,
        candidates: list[str],
    ) -> list[str]:
        """Batch visibility filter.

        Preserves candidate order and duplicates, never adds items, and raises
        the same role/resource errors as :meth:`authorize`.
        """
        policy = self._resolve_policy(principal, resource_type, resource_field="resource_type")
        if not isinstance(candidates, list):
            raise ValueError(f"candidates must be a list, got {type(candidates).__name__}")
        validated_candidates = [_require_non_empty_string(candidate, field=f"candidates[{index}]") for index, candidate in enumerate(candidates)]
        if policy is None:
            return validated_candidates

        return [candidate for candidate in validated_candidates if policy.is_allowed(candidate)]

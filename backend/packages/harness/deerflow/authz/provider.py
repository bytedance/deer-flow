"""AuthorizationProvider protocol and data structures for fine-grained resource authorization.

This is the policy brain for resource-level authorization (RBAC and beyond),
deliberately kept as a sibling to :mod:`deerflow.guardrails` rather than folded
into it. PR #3665 (which added ``user_role``/``user_id`` to
``GuardrailRequest``) explicitly scoped guardrails to *execution-time* checks
only — *"保持 Guardrail 的职责边界不变：不新增 policy engine、RBAC 系统、
governance 子系统"*. This module is the RBAC brain that #3665 deferred.

The provider is enforced at **two layers** from one policy:

1. **Assembly-time capability filter** — removes tools a role can never use
   *before* they are bound to the agent, so the model never sees them and
   ``tool_search`` can never promote them back (fail-closed).
2. **Run-time execution deny** — reuses :class:`~deerflow.guardrails.middleware.GuardrailMiddleware`
   via a thin adapter (see :mod:`deerflow.authz.adapter`), catching dynamic
   resources and argument-based restrictions.

See ``docs/plans/2026-07-10-pluggable-authorization-rfc.md`` (issue #4063) for
the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Principal:
    """The actor resolved from trusted runtime identity context.

    Identity fields mirror what ``inject_authenticated_user_context``
    (``app/gateway/services.py``) already stamps into the run context, so the
    provider sees one consistent identity shape. Layer 1 and the execution-time
    guardrail adapter both use ``build_principal_from_context``; the adapter
    rebuilds the value per request so it never caches stale runtime identity.
    """

    user_id: str | None = None
    role: str | None = None
    oauth_provider: str | None = None
    oauth_id: str | None = None
    channel_user_id: str | None = None
    is_internal: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthzRequest:
    """Context passed to the provider for each authorization check."""

    principal: Principal
    resource: str
    """Resource type, e.g. ``"tool"``, ``"model"``, ``"skill"``, ``"sandbox"``, ``"mcp_server"``, ``"route"``."""

    action: str
    """Action on the resource, e.g. ``"call"``, ``"list"``, ``"use"``, ``"activate"``, ``"execute"``, ``"read"``, ``"write"``."""

    target: str
    """Resource identifier: tool name, model name, skill name, ``"route:threads:read"``, etc."""

    context: dict[str, Any] = field(default_factory=dict)
    """Additional context: ``thread_id``, ``run_id``, ``tool_call_id``, ``tool_input``, ``is_subagent``, etc."""


@dataclass
class AuthzReason:
    """Structured reason for an allow/deny decision."""

    code: str
    message: str = ""


@dataclass
class AuthzDecision:
    """Provider's allow/deny verdict."""

    allow: bool
    reasons: list[AuthzReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuthorizationProvider(Protocol):
    """Contract for pluggable fine-grained authorization.

    Any class with these methods works - no base class required.
    Providers are loaded by class path via ``resolve_variable()``, the same
    mechanism DeerFlow uses for models, tools, sandbox, and guardrails.

    ``resource``, ``action``, and ``target`` are free-form strings (not an
    enum) so new resource types and provider-specific resources need no schema
    change. The built-in RBAC provider interprets them; custom providers
    define their own.
    """

    name: str

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        """Per-call decision. Feeds Layer 2 (execution) and route checks."""
        ...

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        """Async variant."""
        ...

    def filter_resources(
        self,
        principal: Principal,
        resource_type: str,
        candidates: list[str],
    ) -> list[str]:
        """Layer 1: batch visibility filter at assembly time.

        Returns the subset of *candidates* the principal is allowed to see.
        This is a required method — providers that do not have a static
        role→resource map should delegate to :meth:`authorize` per item and
        return only the allowed subset. Providers with a static map can
        override this for O(1) filtering and fail-closed visibility.
        """
        ...

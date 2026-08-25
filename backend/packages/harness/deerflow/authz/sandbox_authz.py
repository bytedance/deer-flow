"""Sandbox execution authorization gate.

Checks ``authorize("sandbox", "execute")`` before sandbox acquisition so a
role-scoped policy can deny sandbox execution entirely. On deny, a
:class:`~deerflow.sandbox.exceptions.SandboxAuthorizationError` propagates up
through the tool's execution; the agent's tool-error handling converts it to a
friendly ``ToolMessage`` ("sandbox not permitted for your role") rather than
crashing the run (RFC §9).

Mirrors the Principal/provider pattern of ``apply_tool_authorization``
(``tool_filter.py``) and ``_authorize_model_name`` (``lead_agent/agent.py``)
so the sandbox path shares one identity source with the tool and model paths.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthzDecision, AuthzRequest
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.app_config import AppConfig
from deerflow.sandbox.exceptions import SandboxAuthorizationError

logger = logging.getLogger(__name__)


def safe_app_config() -> AppConfig | None:
    """Load the global AppConfig, returning None when unavailable.

    Authorization can only be enabled via config, so no readable config ⇒ the
    sandbox gate is a no-op (``authorize_sandbox_execution`` treats a ``None``
    app_config the same as ``authorization.enabled: false``). This keeps the
    gate safe in environments without a ``config.yaml`` (e.g. CI runners and
    direct-call tests) where ``get_app_config`` would raise ``FileNotFoundError``.
    """
    try:
        from deerflow.config import get_app_config

        return get_app_config()
    except Exception:
        logger.debug("App config unavailable; sandbox:execute gate is a no-op", exc_info=True)
        return None


# Sandbox is a single shared resource (the execution environment), not a named
# catalog like tools/models/skills. The target is therefore a sentinel "*" that
# means "the sandbox as a whole"; RBAC ``allow: ["*"]`` / ``allow: true`` permits
# it, ``allow: []`` / ``allow: false`` denies it.
_SANDBOX_TARGET = "*"


def authorize_sandbox_execution(*, context: Mapping[str, Any], app_config: AppConfig | None) -> None:
    """Check ``authorize("sandbox", "execute")`` before sandbox acquisition.

    ``app_config=None`` (unreadable config) is treated the same as
    ``authorization.enabled: false`` — a no-op. On deny (or provider error
    with ``fail_closed``), raises :class:`SandboxAuthorizationError`; on
    provider error with fail-open, returns silently (legacy allow behavior).
    """
    # Guard against Mock/SimpleNamespace app_config objects in tests that
    # don't carry a real AuthorizationConfig. getattr avoids AttributeError
    # and the ``is not True`` identity check avoids truthy Mock attributes
    # (mirrors filter_available_skills_by_authorization in skill_filter.py).
    authz_config = getattr(app_config, "authorization", None)
    if authz_config is None or getattr(authz_config, "enabled", None) is not True:
        return

    # Provider *resolution* failures follow the same fail_closed/fail_open
    # decision as authorize() errors — a raw ValueError here would otherwise
    # effectively deny under fail_open (inverted semantics).
    try:
        provider = resolve_authorization_provider(authz_config)
    except Exception:
        logger.warning("Failed to resolve authorization provider for sandbox:execute", exc_info=True)
        if authz_config.fail_closed:
            raise SandboxAuthorizationError() from None
        # fail-open: allow sandbox acquisition despite the resolution error.
        return
    if provider is None:
        return

    principal = build_principal_from_context(context, default_role=authz_config.default_role)
    try:
        decision = provider.authorize(AuthzRequest(principal=principal, resource="sandbox", action="execute", target=_SANDBOX_TARGET))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
        if decision.allow:
            return
        # Explicit deny → block sandbox acquisition with a friendly error.
        raise SandboxAuthorizationError(role=principal.role)
    except SandboxAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking sandbox:execute", exc_info=True)
        if authz_config.fail_closed:
            raise SandboxAuthorizationError(role=principal.role)
        # fail-open: allow sandbox acquisition despite the provider error.
        return

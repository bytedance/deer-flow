"""Sandbox execution authorization gate.

Checks ``authorize("sandbox", "execute")`` before sandbox use so a role-scoped
policy can deny sandbox execution entirely. On deny, a
:class:`~deerflow.sandbox.exceptions.SandboxAuthorizationError` propagates up
through the tool's execution; the agent's tool-error handling converts it to a
friendly ``ToolMessage`` ("sandbox not permitted for your role") rather than
crashing the run (RFC §9).

Mirrors the Principal/provider pattern of ``apply_tool_authorization``
(``tool_filter.py``) and ``_authorize_model_name`` (``lead_agent/agent.py``)
so the sandbox path shares one identity source with the tool and model paths.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.authz.runtime import construct_authorization_provider, resolve_authorization_provider, resolve_authorization_provider_spec
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


async def safe_app_config_async() -> AppConfig | None:
    """Load AppConfig without running config file I/O on the event loop."""
    return await asyncio.to_thread(safe_app_config)


# Sandbox is a single shared resource (the execution environment), not a named
# catalog like tools/models/skills. The target is therefore a sentinel "*" that
# means "the sandbox as a whole"; RBAC ``allow: ["*"]`` / ``allow: true`` permits
# it, ``allow: []`` / ``allow: false`` denies it.
_SANDBOX_TARGET = "*"


def _resolve_authorization_inputs(
    *,
    context: Mapping[str, Any],
    app_config: AppConfig | None,
) -> tuple[AuthorizationProvider, Any, Principal] | None:
    """Resolve the enabled provider and principal shared by both call paths."""
    # Guard against Mock/SimpleNamespace app_config objects in tests that
    # don't carry a real AuthorizationConfig. getattr avoids AttributeError
    # and the ``is not True`` identity check avoids truthy Mock attributes
    # (mirrors filter_available_skills_by_authorization in skill_filter.py).
    authz_config = getattr(app_config, "authorization", None)
    if authz_config is None or getattr(authz_config, "enabled", None) is not True:
        return None

    # Provider *resolution* failures follow the same fail_closed/fail_open
    # decision as authorize() errors — a raw ValueError here would otherwise
    # effectively deny under fail_open (inverted semantics).
    try:
        provider = resolve_authorization_provider(authz_config)
    except Exception:
        logger.warning("Failed to resolve authorization provider for sandbox:execute", exc_info=True)
        if authz_config.fail_closed:
            raise SandboxAuthorizationError() from None
        # fail-open: allow sandbox use despite the resolution error.
        return None
    if provider is None:
        return None

    principal = build_principal_from_context(context, default_role=authz_config.default_role)
    return provider, authz_config, principal


async def _resolve_authorization_inputs_async(
    *,
    context: Mapping[str, Any],
    app_config: AppConfig | None,
) -> tuple[AuthorizationProvider, Any, Principal] | None:
    """Discover off-loop, then construct custom providers on this event loop."""
    authz_config = getattr(app_config, "authorization", None)
    if authz_config is None or getattr(authz_config, "enabled", None) is not True:
        return None

    try:
        if getattr(authz_config, "provider", None) is None:
            # There is no module to import. Preserve the synchronous resolver's
            # missing-provider validation without an unnecessary worker hop.
            provider = resolve_authorization_provider(authz_config)
        else:
            spec = await asyncio.to_thread(resolve_authorization_provider_spec, authz_config)
            # Async providers may create loop-affine clients in __init__.
            provider = construct_authorization_provider(spec, authz_config)
    except Exception:
        logger.warning("Failed to resolve authorization provider for sandbox:execute", exc_info=True)
        if authz_config.fail_closed:
            raise SandboxAuthorizationError() from None
        return None
    if provider is None:
        return None

    principal = build_principal_from_context(context, default_role=authz_config.default_role)
    return provider, authz_config, principal


def _authorization_request(principal: Principal) -> AuthzRequest:
    return AuthzRequest(principal=principal, resource="sandbox", action="execute", target=_SANDBOX_TARGET)


def _enforce_decision(decision: AuthzDecision, *, principal: Principal, method_name: str) -> None:
    if not isinstance(decision, AuthzDecision):
        raise TypeError(f"AuthorizationProvider.{method_name} must return AuthzDecision")
    if not decision.allow:
        raise SandboxAuthorizationError(role=principal.role)


def authorize_sandbox_execution(*, context: Mapping[str, Any], app_config: AppConfig | None) -> None:
    """Synchronously check ``authorize("sandbox", "execute")`` before use.

    ``app_config=None`` (unreadable config) is treated the same as
    ``authorization.enabled: false`` — a no-op. On deny (or provider error
    with ``fail_closed``), raises :class:`SandboxAuthorizationError`; on
    provider error with fail-open, returns silently (legacy allow behavior).
    """
    inputs = _resolve_authorization_inputs(context=context, app_config=app_config)
    if inputs is None:
        return
    provider, authz_config, principal = inputs

    try:
        decision = provider.authorize(_authorization_request(principal))
        _enforce_decision(decision, principal=principal, method_name="authorize")
    except SandboxAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking sandbox:execute", exc_info=True)
        if authz_config.fail_closed:
            raise SandboxAuthorizationError(role=principal.role)
        # fail-open: allow sandbox use despite the provider error.
        return


async def authorize_sandbox_execution_async(*, context: Mapping[str, Any], app_config: AppConfig | None) -> None:
    """Asynchronously check ``authorize("sandbox", "execute")`` before use.

    Provider discovery may import a custom module, so it runs off the event
    loop. Provider construction stays on the event loop because a valid async
    provider may create loop-affine clients in ``__init__``.
    """
    context_snapshot = dict(context)
    inputs = await _resolve_authorization_inputs_async(
        context=context_snapshot,
        app_config=app_config,
    )
    if inputs is None:
        return
    provider, authz_config, principal = inputs

    try:
        decision = await provider.aauthorize(_authorization_request(principal))
        _enforce_decision(decision, principal=principal, method_name="aauthorize")
    except SandboxAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking sandbox:execute", exc_info=True)
        if authz_config.fail_closed:
            raise SandboxAuthorizationError(role=principal.role)
        # fail-open: allow sandbox use despite the provider error.
        return

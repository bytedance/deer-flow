"""Authorization decisions for plugin resources (harness-side decision layer).

The plugin entry points — a registered backend action, a declared page, an
enterprise-contributed management route — ask the same configured
:class:`~deerflow.authz.provider.AuthorizationProvider` the tool path uses, with
the same trusted ``Principal`` construction. This module owns the *decision*;
the Gateway owns request scoping and the public extension guard lives in
``deerflow_extension_api.auth``.

Semantics, uniform across every function here:

* ``authorization.enabled is not True`` → no-op (allow). The identity check
  mirrors :mod:`deerflow.authz.tool_filter`, so a ``Mock``/``SimpleNamespace``
  app config cannot turn a non-bool into an enabled gate.
* A caller-supplied ``provider`` is reused, so one request resolves the provider
  once (the Gateway hands in the instance from its loop-keyed cache).
* An explicit deny raises :class:`PluginAuthorizationError`.
* A provider exception, a resolution failure, a malformed decision or a missing
  principal follows ``fail_closed``: raise the same error, or log a warning and
  allow. This mirrors the sandbox / route-scoped semantics — not the tool
  filter's silent-set behavior.

Execution placement (identical to :mod:`deerflow.authz.sandbox_authz`, and the
reason this module reuses its config helpers): on the async path config load and
provider *discovery* are offloaded, while provider *construction* stays on the
calling loop because a valid async provider may create loop-affine clients in
``__init__``; a sync caller loads the config inline, which is what makes it a
sync caller. The async batch helpers hand the provider to a worker thread, which
is why ``filter_resources`` must be thread-safe. The sync helpers serve
genuinely synchronous callers (a FastAPI ``def`` endpoint runs in the thread
pool); an async endpoint uses the ``a*`` variant.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from deerflow.authz.plugin_targets import (
    ManagementPart,
    plugin_action_target,
    plugin_management_target,
)
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzReason, AuthzRequest, Principal
from deerflow.authz.runtime import (
    construct_authorization_provider,
    resolve_authorization_provider,
    resolve_authorization_provider_spec,
)
from deerflow.authz.sandbox_authz import safe_app_config, safe_app_config_async

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

RESOURCE_PLUGIN_ACTION = "plugin_action"
RESOURCE_PLUGIN_PAGE = "plugin_page"
RESOURCE_PLUGIN_MANAGEMENT = "plugin_management"

#: A batch question covers the whole candidate list, so it has no single target.
_BATCH_TARGET = "*"


class PluginAuthorizationError(Exception):
    """A plugin resource decision denied, or could not be answered under ``fail_closed``."""

    def __init__(self, *, resource: str, target: str, reason_code: str, fail_closed: bool = False) -> None:
        super().__init__(f"plugin authorization denied for {resource} '{target}' ({reason_code})")
        self.resource = resource
        self.target = target
        self.reason_code = reason_code
        self.fail_closed = fail_closed


def _authorization_request(
    principal: Principal,
    resource: str,
    action: str,
    target: str,
    context: Mapping[str, Any] | None,
) -> AuthzRequest:
    return AuthzRequest(
        principal=principal,
        resource=resource,
        action=action,
        target=target,
        context=dict(context) if context else {},
    )


def _unanswerable(*, resource: str, target: str, reason_code: str, fail_closed: bool) -> None:
    """Apply the failure policy for a question the host cannot answer."""
    if fail_closed:
        raise PluginAuthorizationError(resource=resource, target=target, reason_code=reason_code, fail_closed=True)
    logger.warning(
        "Plugin authorization for %s '%s' could not be answered (%s); allowing because fail_closed is false",
        resource,
        target,
        reason_code,
    )


def _deny_reason_code(decision: AuthzDecision) -> str:
    for reason in decision.reasons:
        if isinstance(reason, AuthzReason) and reason.code:
            return reason.code
    return "authz.denied"


def _enabled_config(app_config: AppConfig | None) -> Any | None:
    """Return the authorization config when it is actually enabled, else ``None``."""
    authz_config = getattr(app_config, "authorization", None) if app_config is not None else None
    if authz_config is None or getattr(authz_config, "enabled", None) is not True:
        return None
    return authz_config


def _fail_closed(authz_config: Any) -> bool:
    return getattr(authz_config, "fail_closed", False) is True


async def _aresolve_provider(authz_config: Any) -> AuthorizationProvider:
    """Resolve off-loop discovery, then construct on this loop (see module docstring)."""
    if getattr(authz_config, "provider", None) is None:
        # Nothing to import; preserve the resolver's own "enabled but unconfigured" error.
        provider = resolve_authorization_provider(authz_config)
    else:
        spec = await asyncio.to_thread(resolve_authorization_provider_spec, authz_config)
        provider = construct_authorization_provider(spec, authz_config)
    if provider is None:
        raise ValueError("authorization is enabled but provider resolution returned None")
    return provider


def _enforce_single(*, principal, app_config, resource, action, target, provider, context) -> None:
    if app_config is None:
        # A sync caller (or a FastAPI ``def`` worker) loads the config inline;
        # the async twin offloads the same load instead.
        app_config = safe_app_config()
    authz_config = _enabled_config(app_config)
    if authz_config is None:
        return
    fail_closed = _fail_closed(authz_config)
    if principal is None:
        _unanswerable(resource=resource, target=target, reason_code="authz.no_principal", fail_closed=fail_closed)
        return
    try:
        active_provider = provider if provider is not None else resolve_authorization_provider(authz_config)
        if active_provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
        decision = active_provider.authorize(_authorization_request(principal, resource, action, target, context))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
    except PluginAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking %s '%s'", resource, target, exc_info=True)
        _unanswerable(resource=resource, target=target, reason_code="authz.provider_error", fail_closed=fail_closed)
        return
    if not decision.allow:
        raise PluginAuthorizationError(resource=resource, target=target, reason_code=_deny_reason_code(decision), fail_closed=fail_closed)


async def _aenforce_single(*, principal, app_config, resource, action, target, provider, context) -> None:
    if app_config is None:
        app_config = await safe_app_config_async()
    authz_config = _enabled_config(app_config)
    if authz_config is None:
        return
    fail_closed = _fail_closed(authz_config)
    if principal is None:
        _unanswerable(resource=resource, target=target, reason_code="authz.no_principal", fail_closed=fail_closed)
        return
    try:
        active_provider = provider if provider is not None else await _aresolve_provider(authz_config)
        decision = await active_provider.aauthorize(_authorization_request(principal, resource, action, target, context))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.aauthorize must return AuthzDecision")
    except PluginAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking %s '%s'", resource, target, exc_info=True)
        _unanswerable(resource=resource, target=target, reason_code="authz.provider_error", fail_closed=fail_closed)
        return
    if not decision.allow:
        raise PluginAuthorizationError(resource=resource, target=target, reason_code=_deny_reason_code(decision), fail_closed=fail_closed)


async def _afilter(*, principal, app_config, resource, candidates: Iterable[str], provider) -> frozenset[str]:
    candidate_list = list(candidates)
    if app_config is None:
        app_config = await safe_app_config_async()
    authz_config = _enabled_config(app_config)
    if authz_config is None:
        return frozenset(candidate_list)
    if not candidate_list:
        # No candidate means no provider round trip (the projection's cost rule).
        return frozenset()
    fail_closed = _fail_closed(authz_config)
    if principal is None:
        _unanswerable(resource=resource, target=_BATCH_TARGET, reason_code="authz.no_principal", fail_closed=fail_closed)
        return frozenset(candidate_list)
    try:
        active_provider = provider if provider is not None else await _aresolve_provider(authz_config)
        # filter_resources is synchronous and may do blocking work; keep it off the loop.
        allowed = await asyncio.to_thread(active_provider.filter_resources, principal, resource, candidate_list)
        if not isinstance(allowed, list) or any(not isinstance(name, str) for name in allowed):
            raise TypeError("AuthorizationProvider.filter_resources must return list[str]")
    except PluginAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while filtering %s candidates", resource, exc_info=True)
        _unanswerable(resource=resource, target=_BATCH_TARGET, reason_code="authz.provider_error", fail_closed=fail_closed)
        return frozenset(candidate_list)
    return frozenset(allowed)


def enforce_plugin_action(
    *,
    principal: Principal | None,
    app_config: AppConfig | None = None,
    namespace: str,
    action_name: str,
    provider: AuthorizationProvider | None = None,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Allow or raise for ``plugin_action``/``invoke`` on ``namespace/action_name``."""
    target = plugin_action_target(namespace, action_name)
    _enforce_single(
        principal=principal,
        app_config=app_config,
        resource=RESOURCE_PLUGIN_ACTION,
        action="invoke",
        target=target,
        provider=provider,
        context=context,
    )


async def aenforce_plugin_action(
    *,
    principal: Principal | None,
    app_config: AppConfig | None = None,
    namespace: str,
    action_name: str,
    provider: AuthorizationProvider | None = None,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Async :func:`enforce_plugin_action` for async callers (the action route)."""
    target = plugin_action_target(namespace, action_name)
    await _aenforce_single(
        principal=principal,
        app_config=app_config,
        resource=RESOURCE_PLUGIN_ACTION,
        action="invoke",
        target=target,
        provider=provider,
        context=context,
    )


def enforce_plugin_management(
    *,
    principal: Principal | None,
    app_config: AppConfig | None = None,
    namespace: str,
    write: bool,
    provider: AuthorizationProvider | None = None,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Allow or raise for ``plugin_management`` read/write on *namespace*."""
    part: ManagementPart = "permissions.write" if write else "permissions.read"
    target = plugin_management_target(namespace, part)
    _enforce_single(
        principal=principal,
        app_config=app_config,
        resource=RESOURCE_PLUGIN_MANAGEMENT,
        action="write" if write else "read",
        target=target,
        provider=provider,
        context=context,
    )


async def aenforce_plugin_management(
    *,
    principal: Principal | None,
    app_config: AppConfig | None = None,
    namespace: str,
    write: bool,
    provider: AuthorizationProvider | None = None,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Async :func:`enforce_plugin_management` for async callers."""
    part: ManagementPart = "permissions.write" if write else "permissions.read"
    target = plugin_management_target(namespace, part)
    await _aenforce_single(
        principal=principal,
        app_config=app_config,
        resource=RESOURCE_PLUGIN_MANAGEMENT,
        action="write" if write else "read",
        target=target,
        provider=provider,
        context=context,
    )


async def afilter_plugin_pages(
    *,
    principal: Principal | None,
    app_config: AppConfig | None = None,
    candidates: Iterable[str],
    provider: AuthorizationProvider | None = None,
) -> frozenset[str]:
    """Return the visible subset of ``plugin_page`` targets (one provider round trip)."""
    return await _afilter(
        principal=principal,
        app_config=app_config,
        resource=RESOURCE_PLUGIN_PAGE,
        candidates=candidates,
        provider=provider,
    )


async def afilter_plugin_management(
    *,
    principal: Principal | None,
    app_config: AppConfig | None = None,
    candidates: Iterable[str],
    provider: AuthorizationProvider | None = None,
) -> frozenset[str]:
    """Return the permitted subset of ``plugin_management`` targets (one round trip)."""
    return await _afilter(
        principal=principal,
        app_config=app_config,
        resource=RESOURCE_PLUGIN_MANAGEMENT,
        candidates=candidates,
        provider=provider,
    )

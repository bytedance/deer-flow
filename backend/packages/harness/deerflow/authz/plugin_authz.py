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
* The caller supplies ``app_config``: the *same* request-scoped snapshot it used
  to resolve ``provider``. This module never reads the configuration itself, so
  a config file that disappears or fails to parse mid-request cannot be mistaken
  for a disabled policy. ``app_config=None`` means the caller could not read it
  at all — *unavailable*, not disabled — and the check fails closed
  (``authz.config_unavailable``) because the flag that would permit an allow is
  unreadable.
* A caller-supplied ``provider`` is reused, so one request resolves the provider
  once (the Gateway hands in the instance from its loop-keyed cache).
* An explicit deny raises :class:`PluginAuthorizationError`.
* A batch answer is intersected with the candidates it was asked about, so a
  provider that names a target the host never offered cannot widen a projection.
* A provider exception, a resolution failure, a malformed decision (a non-
  :class:`AuthzDecision`, or one whose ``allow`` is not a real ``bool``) or a
  missing principal follows ``fail_closed``: raise the same error, or log a
  warning and allow. This mirrors the sandbox / route-scoped semantics — not the
  tool filter's silent-set behavior. A denial whose ``reasons`` cannot be read —
  non-iterable, or an iterable that raises while consumed — is *not* malformed:
  the verdict stands and only its ``reason_code`` degrades to ``authz.denied``, so
  a bad reason list can never turn a deny into an allow or into a ``500``.

Execution placement: provider *discovery* is offloaded on the async path while
provider *construction* stays on the calling loop, because a valid async
provider may create loop-affine clients in ``__init__``; the configuration read
belongs to the caller (the Gateway performs it off-loop). The async batch
helpers hand the provider to a worker thread, which is why ``filter_resources``
must be thread-safe. The sync helpers serve genuinely synchronous callers (a
FastAPI ``def`` endpoint runs in the thread pool); an async endpoint uses the
``a*`` variant.
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
    """Extract the provider's machine-readable denial code, tolerating bad ``reasons``.

    ``AuthzDecision`` is a plain dataclass, so a provider can return a verdict
    whose ``reasons`` is not an iterable of :class:`AuthzReason` — or is an
    iterable that raises from ``__iter__``/``__next__`` while being consumed. The
    verdict is still a valid denial (``allow`` is a real ``bool``, and this runs
    only after that check), so the denial stands and only the informative code
    degrades: extraction must never raise, or a denial would escape as an
    unhandled error instead of the configured authorization failure (a ``403``).
    """
    try:
        reasons = decision.reasons
        if not isinstance(reasons, Iterable):
            return "authz.denied"
        for reason in reasons:
            if isinstance(reason, AuthzReason) and isinstance(reason.code, str) and reason.code:
                return reason.code
    except Exception:
        # A generator or custom iterable passes the ``Iterable`` check and can
        # still raise while iterated; the verdict stays a denial.
        logger.debug("Authorization denial carried unreadable reasons", exc_info=True)
    return "authz.denied"


def _enabled_config(app_config: AppConfig | None) -> Any | None:
    """Return the authorization config when it is actually enabled, else ``None``."""
    authz_config = getattr(app_config, "authorization", None) if app_config is not None else None
    if authz_config is None or getattr(authz_config, "enabled", None) is not True:
        return None
    return authz_config


def _fail_closed(authz_config: Any) -> bool:
    return getattr(authz_config, "fail_closed", False) is True


def _authorization_config(app_config: AppConfig | None, *, resource: str, target: str) -> Any | None:
    """Return the enabled authorization config, or ``None`` when policy is explicitly disabled.

    ``app_config is None`` means the caller could not read the configuration,
    which is not the same as an explicitly disabled policy: the flag that would
    permit an allow is unreadable, so the check fails closed.
    """
    if app_config is None:
        raise PluginAuthorizationError(resource=resource, target=target, reason_code="authz.config_unavailable", fail_closed=True)
    return _enabled_config(app_config)


def _validated_decision(decision: object, *, method_name: str) -> AuthzDecision:
    """Reject a verdict that is not an ``AuthzDecision`` with a real ``bool`` allow.

    ``AuthzDecision`` is a plain dataclass, so a custom provider can return
    ``AuthzDecision(allow="false")``; the truthy string would otherwise be read
    as an allow. A malformed verdict follows ``fail_closed`` like any other
    provider failure.
    """
    if not isinstance(decision, AuthzDecision) or type(decision.allow) is not bool:
        raise TypeError(f"AuthorizationProvider.{method_name} must return AuthzDecision with a bool allow")
    return decision


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
    authz_config = _authorization_config(app_config, resource=resource, target=target)
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
        decision = _validated_decision(
            active_provider.authorize(_authorization_request(principal, resource, action, target, context)),
            method_name="authorize",
        )
    except PluginAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking %s '%s'", resource, target, exc_info=True)
        _unanswerable(resource=resource, target=target, reason_code="authz.provider_error", fail_closed=fail_closed)
        return
    if not decision.allow:
        raise PluginAuthorizationError(resource=resource, target=target, reason_code=_deny_reason_code(decision), fail_closed=fail_closed)


async def _aenforce_single(*, principal, app_config, resource, action, target, provider, context) -> None:
    authz_config = _authorization_config(app_config, resource=resource, target=target)
    if authz_config is None:
        return
    fail_closed = _fail_closed(authz_config)
    if principal is None:
        _unanswerable(resource=resource, target=target, reason_code="authz.no_principal", fail_closed=fail_closed)
        return
    try:
        active_provider = provider if provider is not None else await _aresolve_provider(authz_config)
        decision = _validated_decision(
            await active_provider.aauthorize(_authorization_request(principal, resource, action, target, context)),
            method_name="aauthorize",
        )
    except PluginAuthorizationError:
        raise
    except Exception:
        logger.warning("Authorization provider failed while checking %s '%s'", resource, target, exc_info=True)
        _unanswerable(resource=resource, target=target, reason_code="authz.provider_error", fail_closed=fail_closed)
        return
    if not decision.allow:
        raise PluginAuthorizationError(resource=resource, target=target, reason_code=_deny_reason_code(decision), fail_closed=fail_closed)


async def _afilter(*, principal, app_config, resource, candidates: Iterable[str], provider) -> frozenset[str]:
    """Return the subset of *candidates* the provider allows (one round trip).

    The result is a subset of *candidates* on every path, including the provider
    answer: ``filter_resources`` is documented to return "only the allowed
    subset", but it is a plain method on a custom provider, so an answer naming a
    target that was never asked about (``"*"``, another namespace, a phantom
    page) is intersected away rather than projected as visible.
    """
    candidate_list = list(candidates)
    authz_config = _authorization_config(app_config, resource=resource, target=_BATCH_TARGET)
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
    return frozenset(allowed) & frozenset(candidate_list)


def enforce_plugin_action(
    *,
    principal: Principal | None,
    app_config: AppConfig | None,
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
    app_config: AppConfig | None,
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
    app_config: AppConfig | None,
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
    app_config: AppConfig | None,
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
    app_config: AppConfig | None,
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
    app_config: AppConfig | None,
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

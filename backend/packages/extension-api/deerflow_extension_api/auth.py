"""The caller's identity, for contributed routes.

Contributed routers are constructed during install(), long before any request
exists, so identity cannot be handed to them at registration time. The host
instead installs a resolver on ``app.state`` and this module reads it back.

``request`` is duck-typed rather than annotated as a Starlette Request: this
package must not depend on a web framework.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

logger = logging.getLogger(__name__)

EXTENSION_PRINCIPAL_RESOLVER_KEY = "deerflow_extension_principal_resolver"
EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY = "deerflow_extension_plugin_authz_resolver"
EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY = "deerflow_extension_plugin_authz_resolver_async"

# Mirrors the host's plugin-namespace registration rule
# (deerflow.config.plugin_settings). Kept local because this package must not
# import the host; tests/test_plugin_targets.py asserts every copy agrees.
_NAMESPACE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,95}\Z")

_ManagementScope = Literal["read", "write"]


@dataclass(frozen=True)
class ExtensionPrincipal:
    user_id: str
    is_admin: bool = False
    is_internal: bool = False
    roles: tuple[str, ...] = field(default_factory=tuple)


def resolve_principal(request: object) -> ExtensionPrincipal | None:
    """Return the caller's principal, or ``None`` when it cannot be determined."""
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    resolver = getattr(state, EXTENSION_PRINCIPAL_RESOLVER_KEY, None)
    if not callable(resolver):
        return None
    try:
        principal = resolver(request)
    except Exception as exc:  # noqa: BLE001 - an unanswerable identity is not an error to propagate
        logger.warning("extension principal resolver failed: %s", type(exc).__name__)
        return None
    return principal if isinstance(principal, ExtensionPrincipal) else None


def require_admin(request: object) -> ExtensionPrincipal:
    """Return the principal when it is an admin, else raise ``PermissionError``.

    Fails closed on an absent or failing resolver: an authorization question the
    host cannot answer must never resolve to "allowed".
    """
    principal = resolve_principal(request)
    if principal is None or not principal.is_admin:
        raise PermissionError("this endpoint requires an administrator account")
    return principal


def _plugin_management_resolver(request: object, key: str) -> Callable | None:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    resolver = getattr(state, key, None)
    return resolver if callable(resolver) else None


def _plugin_management_scope(scope: str) -> _ManagementScope:
    if scope not in ("read", "write"):
        raise ValueError(f"scope must be 'read' or 'write', got {scope!r}")
    return cast("_ManagementScope", scope)


def _require_plugin_namespace(namespace: object) -> str:
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise ValueError(f"invalid plugin namespace {namespace!r}")
    return namespace


def require_plugin_management(request: object, namespace: str, *, scope: _ManagementScope = "read") -> ExtensionPrincipal:
    """Return the caller when it holds ``plugin_management`` *scope* for *namespace*.

    The host answers through the resolver installed at
    :data:`EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY`. This helper **fails closed**:
    an absent, failing or ``None`` answer, an unknown registered namespace, or a
    non-``True`` decision raises ``PermissionError`` — the same rule
    :func:`require_admin` documents. A deployment with ``authorization.enabled:
    false`` has the host answer ``True``, so turning authorization off does not
    start rejecting enterprise routes; an enterprise that needs an
    unconditional floor keeps calling :func:`require_admin` in addition.

    Use the ``a`` variant from an async endpoint: this one runs in the caller's
    thread and the host's sync answer may read configuration.
    """
    scope = _plugin_management_scope(scope)
    namespace = _require_plugin_namespace(namespace)
    principal = resolve_principal(request)
    if principal is None:
        raise PermissionError("this endpoint requires an authenticated account")
    resolver = _plugin_management_resolver(request, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)
    answer = None
    if resolver is not None:
        try:
            answer = resolver(request, namespace, scope)
        except Exception as exc:  # noqa: BLE001 - an unanswerable question is a denial
            logger.warning("extension plugin authorization resolver failed: %s", type(exc).__name__)
            answer = None
    if answer is not True:
        raise PermissionError(f"plugin management ({scope}) is not permitted for {namespace}")
    return principal


async def arequire_plugin_management(request: object, namespace: str, *, scope: _ManagementScope = "read") -> ExtensionPrincipal:
    """Async :func:`require_plugin_management`, for async endpoints.

    Reads :data:`EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY` only. A sync
    resolver installed without its async counterpart is not a fallback: running
    it here would put the host's configuration read back on the event loop.
    """
    scope = _plugin_management_scope(scope)
    namespace = _require_plugin_namespace(namespace)
    principal = resolve_principal(request)
    if principal is None:
        raise PermissionError("this endpoint requires an authenticated account")
    resolver = _plugin_management_resolver(request, EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY)
    answer = None
    if resolver is not None:
        try:
            answer = await resolver(request, namespace, scope)
        except Exception as exc:  # noqa: BLE001 - an unanswerable question is a denial
            logger.warning("extension plugin authorization resolver failed: %s", type(exc).__name__)
            answer = None
    if answer is not True:
        raise PermissionError(f"plugin management ({scope}) is not permitted for {namespace}")
    return principal

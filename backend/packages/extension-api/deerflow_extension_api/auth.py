"""The caller's identity, for contributed routes.

Contributed routers are constructed during install(), long before any request
exists, so identity cannot be handed to them at registration time. The host
instead installs a resolver on ``app.state`` and this module reads it back.

``request`` is duck-typed rather than annotated as a Starlette Request: this
package must not depend on a web framework.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

EXTENSION_PRINCIPAL_RESOLVER_KEY = "deerflow_extension_principal_resolver"


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

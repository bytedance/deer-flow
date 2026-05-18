"""Enterprise RBAC ``PermissionProvider`` (RFC §4.2, plan M1-4).

Implements the duck-typed contract declared by
``app.gateway.authz:PermissionProvider`` — note the harness layer does
**not** import that module (``test_harness_boundary``); we rely on
structural typing instead.

Resolution algorithm (:meth:`resolve_permissions`):

1. Determine the user's :class:`Role` list via :meth:`_resolve_roles`,
   which has three branches:

   * ``user.roles`` is non-empty → cast each known value to :class:`Role`
     and use that.
   * Fallback to the legacy ``user.system_role`` mapping
     (``"admin"`` → :data:`Role.ADMIN`, ``"user"`` → :data:`Role.MEMBER`).
   * Default to ``config.default_role`` for fully unconfigured users.

2. Union the enterprise permissions
   (:data:`DEFAULT_ROLE_PERMISSIONS` resolved via the repository so
   admin overrides persist) with
   :data:`LEGACY_PERMISSIONS_FOR_ROLE` so the existing ``threads:*`` /
   ``runs:*`` routes keep working (RFC §4.3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deerflow.enterprise.config import RbacConfig
from deerflow.enterprise.rbac.models import LEGACY_PERMISSIONS_FOR_ROLE, Role
from deerflow.enterprise.rbac.repository import RbacRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Importing ``app.gateway.auth.models.User`` here would violate the
    # harness boundary; we keep it as ``Any`` and rely on duck typing.
    pass


logger = logging.getLogger(__name__)


# Mapping from the legacy ``User.system_role`` string ("admin" / "user")
# to a :class:`Role`. The function falls back to ``config.default_role``
# when ``system_role`` is unrecognised, keeping the system usable even
# when an OIDC provisioning bug writes an unexpected role label.
_SYSTEM_ROLE_MAPPING: dict[str, Role] = {
    "admin": Role.ADMIN,
    "user": Role.MEMBER,
}


class RbacPermissionProvider:
    """Resolve a ``User`` to its permission set using the RBAC repository.

    Satisfies the ``PermissionProvider`` protocol declared in
    ``app.gateway.authz`` via duck typing. The harness layer cannot
    import that protocol directly without breaking
    ``test_harness_boundary`` — duck typing is the explicit RFC design.
    """

    def __init__(self, config: RbacConfig, repo: RbacRepository) -> None:
        self._config = config
        self._repo = repo

    async def resolve_permissions(self, user: Any) -> set[str]:
        """Return the union of enterprise + legacy permission strings for ``user``.

        Returns a :class:`set` (not :class:`list`) so callers can rely on
        deduplication; ``app.gateway.authz._resolve_permissions_for_user``
        converts to a list on the way out.
        """
        roles = self._resolve_roles(user)

        permissions: set[str] = set()
        for role in roles:
            # Enterprise permissions: load from the repo so operator
            # overrides via ``PUT /api/enterprise/rbac/roles/{id}/permissions``
            # take effect immediately. ``DEFAULT_ROLE_PERMISSIONS`` lives
            # in the data migration; the runtime path only reads.
            enterprise_perms = await self._repo.get_role_permissions(role)
            permissions.update(p.value for p in enterprise_perms)

            # Legacy permissions for the existing ``threads:*`` and
            # ``runs:*`` routes (RFC §4.3). Without this branch, enabling
            # RBAC would 403 every pre-existing route — see plan §3.4
            # risk register.
            permissions.update(LEGACY_PERMISSIONS_FOR_ROLE.get(role, set()))

        return permissions

    def _resolve_roles(self, user: Any) -> list[Role]:
        """Determine the user's effective roles.

        Three branches, evaluated in order:

        1. ``user.roles`` non-empty: take its known values verbatim.
        2. ``user.system_role`` in :data:`_SYSTEM_ROLE_MAPPING`: return
           the mapped enterprise role.
        3. Otherwise fall back to ``config.default_role``. Unknown
           default role strings are dropped with a warning rather than
           crashing, in which case the user gets the empty permission
           set.
        """
        user_roles = getattr(user, "roles", None) or []
        if user_roles:
            resolved: list[Role] = []
            for value in user_roles:
                try:
                    resolved.append(Role(value))
                except ValueError:
                    logger.warning(
                        "User %s has unknown role %r — dropping (configure /api/enterprise/rbac/users to fix)",
                        getattr(user, "id", "<unknown>"),
                        value,
                    )
            if resolved:
                return resolved
            # All custom values were unknown — fall through to the
            # system_role / default branch so the user is not left
            # completely unauthenticated.

        system_role = getattr(user, "system_role", None) or ""
        mapped = _SYSTEM_ROLE_MAPPING.get(system_role)
        if mapped is not None:
            return [mapped]

        default_value = self._config.default_role
        try:
            return [Role(default_value)]
        except ValueError:
            logger.warning(
                "Configured default_role %r is not a known Role — user %s receives no permissions until fixed",
                default_value,
                getattr(user, "id", "<unknown>"),
            )
            return []


__all__ = ["RbacPermissionProvider"]

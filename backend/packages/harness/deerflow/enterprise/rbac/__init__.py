"""Enterprise RBAC sub-package.

Houses the role / permission enums (``models``), the RBAC repository
(``repository``), and the :class:`PermissionProvider`-implementing
:class:`RbacPermissionProvider` (``permission_provider``).

Harness-layer rule (see ``tests/test_harness_boundary.py``): nothing in
``deerflow.enterprise.rbac`` may import from ``app.*``. The plug-in point
exposed to the gateway is the ``PermissionProvider`` Protocol declared in
``app.gateway.authz`` — but harness code references that contract
*structurally* (duck typing), never via import.
"""

from __future__ import annotations

from deerflow.enterprise.rbac.models import (
    DEFAULT_ROLE_PERMISSIONS,
    LEGACY_PERMISSIONS_FOR_ROLE,
    Permission,
    Role,
)

__all__ = [
    "DEFAULT_ROLE_PERMISSIONS",
    "LEGACY_PERMISSIONS_FOR_ROLE",
    "Permission",
    "Role",
]

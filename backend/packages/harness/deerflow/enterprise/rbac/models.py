"""RBAC role and permission enums (RFC §4.1, plan M1-1).

The enterprise ``Permission`` namespace is **additive** — it does not
replace the legacy ``app.gateway.authz.Permissions`` string constants
(``threads:read``, ``runs:create``, etc.). When ``RbacPermissionProvider``
resolves a user's permissions it returns the **union** of:

1. The enterprise permissions wired to each of the user's roles
   (:data:`DEFAULT_ROLE_PERMISSIONS`), and
2. The legacy ``threads:*`` / ``runs:*`` strings the existing routes
   expect (:data:`LEGACY_PERMISSIONS_FOR_ROLE`).

Without (2) the existing ``/api/threads/*`` and ``/api/runs/*`` routes
would 403 the moment RBAC is enabled — this is the regression the plan
§3.4 risk register flags as the top priority.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Built-in roles (RFC §4.1).

    Stored on ``User.roles`` as their string value (e.g. ``"admin"``). The
    ``roles`` table's primary key uses the same string so look-ups can go
    in both directions without translation.
    """

    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Enterprise permission strings (RFC §4.1).

    All values follow the ``{resource}:{action}`` convention so they can
    coexist with the legacy ``Permissions`` constants in
    ``AuthContext.permissions`` without ambiguity.

    Some values are *defined but not yet consumed* by the routes in RFC
    §9.1 — they are reserved for future migration of the existing
    ``/api/agents/*`` and ``/api/threads/*`` routes to the enterprise
    permission model. See RFC §4.1 "Pre-allocated enum values" for the
    inventory.
    """

    # Agent
    AGENT_CREATE = "agent:create"
    AGENT_DELETE = "agent:delete"
    AGENT_VIEW = "agent:view"
    AGENT_EXECUTE = "agent:execute"
    # Thread
    THREAD_CREATE = "thread:create"
    THREAD_READ = "thread:read"
    THREAD_WRITE = "thread:write"
    THREAD_DELETE = "thread:delete"
    # Approval
    APPROVAL_CREATE = "approval:create"
    APPROVAL_GRANT = "approval:grant"
    APPROVAL_REJECT = "approval:reject"
    APPROVAL_VIEW = "approval:view"
    # Data
    DATA_READ = "data:read"
    DATA_WRITE = "data:write"
    DATA_DELETE = "data:delete"
    DATA_EXPORT = "data:export"
    # Admin
    USER_MANAGE = "user:manage"
    ROLE_MANAGE = "role:manage"
    SYSTEM_SETTINGS = "system:settings"


# Built-in role -> permission mapping (RFC §4.1). Repositories seed this
# on first boot via the Alembic data migration (M1-3) so operators can
# override individual rows in the ``role_permissions`` table later
# without losing the defaults.
DEFAULT_ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        Permission.AGENT_CREATE,
        Permission.AGENT_DELETE,
        Permission.AGENT_VIEW,
        Permission.AGENT_EXECUTE,
        Permission.THREAD_CREATE,
        Permission.THREAD_READ,
        Permission.THREAD_WRITE,
        Permission.THREAD_DELETE,
        Permission.APPROVAL_CREATE,
        Permission.APPROVAL_GRANT,
        Permission.APPROVAL_REJECT,
        Permission.APPROVAL_VIEW,
        Permission.DATA_READ,
        Permission.DATA_WRITE,
        Permission.DATA_DELETE,
        Permission.DATA_EXPORT,
        Permission.USER_MANAGE,
        Permission.ROLE_MANAGE,
        Permission.SYSTEM_SETTINGS,
    },
    Role.PROJECT_MANAGER: {
        Permission.AGENT_CREATE,
        Permission.AGENT_VIEW,
        Permission.AGENT_EXECUTE,
        Permission.THREAD_CREATE,
        Permission.THREAD_READ,
        Permission.THREAD_WRITE,
        Permission.APPROVAL_CREATE,
        Permission.APPROVAL_GRANT,
        Permission.APPROVAL_REJECT,
        Permission.APPROVAL_VIEW,
        Permission.DATA_READ,
        Permission.DATA_WRITE,
    },
    Role.MEMBER: {
        Permission.AGENT_VIEW,
        Permission.AGENT_EXECUTE,
        Permission.THREAD_CREATE,
        Permission.THREAD_READ,
        Permission.THREAD_WRITE,
        Permission.APPROVAL_VIEW,
        Permission.DATA_READ,
        Permission.DATA_WRITE,
    },
    Role.VIEWER: {
        Permission.AGENT_VIEW,
        Permission.THREAD_READ,
        Permission.DATA_READ,
        Permission.APPROVAL_VIEW,
    },
}


# Legacy permission strings used by the existing routes
# (``app.gateway.authz.Permissions``). Returning these alongside the
# enterprise permissions is mandatory — see RFC §4.3 — otherwise the
# moment ``RbacPermissionProvider`` is registered the existing
# ``/api/threads/*`` and ``/api/runs/*`` routes 403.
LEGACY_PERMISSIONS_FOR_ROLE: dict[Role, set[str]] = {
    Role.ADMIN: {
        "threads:read",
        "threads:write",
        "threads:delete",
        "runs:create",
        "runs:read",
        "runs:cancel",
    },
    Role.PROJECT_MANAGER: {
        "threads:read",
        "threads:write",
        "runs:create",
        "runs:read",
        "runs:cancel",
    },
    Role.MEMBER: {
        "threads:read",
        "threads:write",
        "runs:create",
        "runs:read",
        "runs:cancel",
    },
    Role.VIEWER: {
        "threads:read",
        "runs:read",
    },
}


__all__ = [
    "DEFAULT_ROLE_PERMISSIONS",
    "LEGACY_PERMISSIONS_FOR_ROLE",
    "Permission",
    "Role",
]

"""Enterprise RBAC HTTP routes (plan M1-8, RFC §9.1).

Mounted under ``/api/enterprise/rbac`` by
``app.gateway.app.create_app`` when ``enterprise.enabled`` is true.

Permission decorators follow RFC §9.1:

============ ============================== =======================
Method       Path                           Permission
============ ============================== =======================
GET          /roles                         role:manage
GET          /roles/{id}                    role:manage
PUT          /roles/{id}/permissions        role:manage
GET          /users/{id}/role               user:manage
PUT          /users/{id}/role               user:manage
GET          /permissions                   role:manage
GET          /my-permissions                authenticated user
============ ============================== =======================

The router relies on the gateway's ``AuthMiddleware`` to populate
``request.state.user`` and ``request.state.auth``. ``@require_auth`` is
applied (alongside ``@require_permission``) so direct unit calls and
ASGI-stack calls both behave consistently.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from app.enterprise.deps import get_rbac_repo
from app.gateway.authz import AuthContext, require_auth, require_permission
from app.gateway.deps import get_local_provider
from deerflow.enterprise.rbac.models import DEFAULT_ROLE_PERMISSIONS, Permission, Role

logger = logging.getLogger(__name__)


router = APIRouter(tags=["enterprise:rbac"])


# ── Request / response models ──────────────────────────────────────────


class RoleResponse(BaseModel):
    """Single role row returned by ``GET /roles`` and ``GET /roles/{id}``."""

    id: str = Field(description="Role id (matches :class:`Role` enum value)")
    name: str = Field(description="Display name (defaults to id for built-in roles)")
    description: str | None = Field(default=None)
    is_default: bool = Field(default=True, description="True for built-in roles")
    permissions: list[str] = Field(default_factory=list, description="Permission strings currently granted to the role")


class RolesListResponse(BaseModel):
    roles: list[RoleResponse]


class PermissionsListResponse(BaseModel):
    """Catalog of every enterprise :class:`Permission` value."""

    permissions: list[str]


class MyPermissionsResponse(BaseModel):
    """Permissions resolved for the calling user."""

    user_id: str
    roles: list[str]
    permissions: list[str]


class RolePermissionsUpdate(BaseModel):
    """Payload for ``PUT /roles/{id}/permissions``."""

    permissions: list[str] = Field(description="Complete desired permission set for the role (replaces existing rows)")


class UserRoleResponse(BaseModel):
    user_id: str
    roles: list[str]
    system_role: str


class UserRoleUpdate(BaseModel):
    """Payload for ``PUT /users/{id}/role``."""

    roles: list[str] = Field(description="Complete desired role list for the user (replaces existing value)")


# ── Helpers ────────────────────────────────────────────────────────────


def _parse_role(role_id: str) -> Role:
    try:
        return Role(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown role: {role_id}") from exc


def _parse_permissions(values: list[str]) -> list[Permission]:
    """Validate and convert raw strings to :class:`Permission` values.

    Raises 400 on unknown strings rather than silently dropping them so
    the operator notices a typo instead of granting a permission that
    will never be enforced.
    """
    parsed: list[Permission] = []
    for value in values:
        try:
            parsed.append(Permission(value))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown permission: {value}") from exc
    return parsed


def _auth_context(request: Request) -> AuthContext:
    """Return the request's :class:`AuthContext`, asserting it exists."""
    ctx: AuthContext | None = getattr(request.state, "auth", None)
    if ctx is None or ctx.user is None:  # defensive — AuthMiddleware should have stamped this
        raise HTTPException(status_code=401, detail="Authentication required")
    return ctx


# ── Routes ─────────────────────────────────────────────────────────────


@router.get("/roles", response_model=RolesListResponse)
@require_auth
@require_permission("role", "manage")
async def list_roles(request: Request) -> RolesListResponse:
    """Return every known role plus the permissions currently granted to it."""
    repo = await get_rbac_repo()
    persisted_roles = set(await repo.list_roles())

    response_rows: list[RoleResponse] = []
    # Always present every enum value, even if the DB row is missing —
    # avoids confusing UX where the admin UI cannot see ``viewer`` until
    # someone tweaks its permissions.
    for role in Role:
        permissions = await repo.get_role_permissions(role)
        if not permissions:
            permissions = DEFAULT_ROLE_PERMISSIONS.get(role, set())
        response_rows.append(
            RoleResponse(
                id=role.value,
                name=role.value,
                description=None,
                is_default=role in persisted_roles or role in DEFAULT_ROLE_PERMISSIONS,
                permissions=sorted(p.value for p in permissions),
            )
        )
    return RolesListResponse(roles=response_rows)


@router.get("/roles/{role_id}", response_model=RoleResponse)
@require_auth
@require_permission("role", "manage")
async def get_role(role_id: str, request: Request) -> RoleResponse:
    role = _parse_role(role_id)
    repo = await get_rbac_repo()
    permissions = await repo.get_role_permissions(role) or DEFAULT_ROLE_PERMISSIONS.get(role, set())
    return RoleResponse(
        id=role.value,
        name=role.value,
        description=None,
        is_default=True,
        permissions=sorted(p.value for p in permissions),
    )


@router.put("/roles/{role_id}/permissions", response_model=RoleResponse)
@require_auth
@require_permission("role", "manage")
async def set_role_permissions(role_id: str, payload: RolePermissionsUpdate, request: Request) -> RoleResponse:
    role = _parse_role(role_id)
    permissions = _parse_permissions(payload.permissions)
    repo = await get_rbac_repo()

    ctx = _auth_context(request)
    granted_by = str(ctx.user.id) if ctx.user else "system:unknown"

    await repo.replace_role_permissions(role, set(permissions), granted_by)
    refreshed = await repo.get_role_permissions(role)
    return RoleResponse(
        id=role.value,
        name=role.value,
        description=None,
        is_default=True,
        permissions=sorted(p.value for p in refreshed),
    )


@router.get("/permissions", response_model=PermissionsListResponse)
@require_auth
@require_permission("role", "manage")
async def list_permissions(request: Request) -> PermissionsListResponse:
    return PermissionsListResponse(permissions=sorted(p.value for p in Permission))


@router.get("/users/{user_id}/role", response_model=UserRoleResponse)
@require_auth
@require_permission("user", "manage")
async def get_user_role(user_id: str, request: Request) -> UserRoleResponse:
    provider = get_local_provider()
    user = await provider.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
    return UserRoleResponse(user_id=str(user.id), roles=list(user.roles), system_role=user.system_role)


@router.put("/users/{user_id}/role", response_model=UserRoleResponse)
@require_auth
@require_permission("user", "manage")
async def set_user_role(user_id: str, payload: UserRoleUpdate, request: Request) -> UserRoleResponse:
    # Validate every role value before touching persistence — partial
    # success would leave the user in an inconsistent state.
    for value in payload.roles:
        try:
            Role(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown role: {value}") from exc

    provider = get_local_provider()
    user = await provider.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")

    user.roles = list(payload.roles)
    await provider.update_user(user)
    return UserRoleResponse(user_id=str(user.id), roles=list(user.roles), system_role=user.system_role)


@router.get("/my-permissions", response_model=MyPermissionsResponse)
@require_auth
async def my_permissions(request: Request) -> MyPermissionsResponse:
    """Echo the calling user's resolved permissions — handy for the UI."""
    ctx = _auth_context(request)
    assert ctx.user is not None  # narrowed by _auth_context
    return MyPermissionsResponse(
        user_id=str(ctx.user.id),
        roles=list(ctx.user.roles),
        permissions=sorted(ctx.permissions),
    )


# Some routes accept a request body but the OpenAPI ``Body`` import is
# only used implicitly via Pydantic models; ``Body`` is re-exported so
# linters do not warn about an unused import when readers extend this
# module in M5.
_ = Body  # noqa: B018


__all__ = ["router"]

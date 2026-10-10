"""Admin user-management surface: list users and assign system roles.

RFC #4063 / issue #3462 gap 2: the RBAC provider accepts arbitrary configured
role names (``guest``, ...), but no surface could assign them to real users —
``User.system_role`` was pinned to admin/user at the API layer while the DB
column stayed a plain string for exactly this future. This router is that
surface: admin-only (§12 Q6 — management surfaces stay admin-gated), role
names validated against the provider's configured roles, and the last
remaining admin cannot be demoted (bootstrap lockout protection).

Enforcement is unchanged: the assignment only changes which role the
principal carries; the Gateway's ``@require_permission`` route guards and the
runtime provider decisions remain the single enforcement points.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.gateway.auth.repositories.base import LastAdminRemainsError, UserNotFoundError
from app.gateway.authz import assignable_role_names
from app.gateway.deps import get_user_repository, require_admin_user

if TYPE_CHECKING:
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

from app.gateway.auth.models import UserResponse

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin-users"])


class UserRoleUpdate(BaseModel):
    """Assignment payload: a built-in or provider-configured role name."""

    system_role: str = Field(..., min_length=1, max_length=16, description="Built-in (admin/user) or a role configured in the authorization provider's roles mapping")


def _to_response(user) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=str(user.email),
        system_role=str(user.system_role),
        needs_setup=bool(getattr(user, "needs_setup", False)),
        oauth_provider=getattr(user, "oauth_provider", None),
    )


@router.get("")
async def list_users(request: Request, repository: SQLiteUserRepository = Depends(get_user_repository)) -> list[UserResponse]:
    """List all users with their system role (admin-only)."""
    await require_admin_user(request, detail="admin user listing requires an admin credential")
    users = await repository.list_users()
    return [_to_response(user) for user in users]


@router.patch("/{user_id}")
async def update_user_role(
    request: Request,
    user_id: UUID,
    update: UserRoleUpdate,
    repository: SQLiteUserRepository = Depends(get_user_repository),
) -> UserResponse:
    """Assign a user's system role (admin-only).

    The role must be a built-in ("admin"/"user") or declared in the
    authorization provider's roles configuration — an unknown name would make
    the user's principal fall through to ``default_role`` on every decision,
    which is never what an operator intended. Demoting the last remaining
    admin is rejected so a deployment cannot lock itself out of management.
    """
    await require_admin_user(request, detail="role assignment requires an admin credential")

    assignable = assignable_role_names()
    if update.system_role not in assignable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown role '{update.system_role}'; assignable roles: {sorted(assignable)}",
        )

    try:
        # Single serialized column write: the last-admin count and the write
        # share one transaction (two concurrent demotions cannot both pass),
        # and credential writers can never race this — see
        # SQLiteUserRepository.update_system_role / update_user.
        user = await repository.update_system_role(str(user_id), update.system_role)
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from None
    except LastAdminRemainsError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot demote the last remaining admin") from None

    return _to_response(user)

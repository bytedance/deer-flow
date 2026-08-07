"""Administrator-only user listing and role management endpoints."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.gateway.auth.models import SystemRole, User
from app.gateway.auth.repositories.base import (
    AdminRoleRequiredError,
    LastAdminError,
    UserNotFoundError,
)
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION, is_auth_disabled
from app.gateway.deps import get_local_provider, require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin-users"])


class AdminUserResponse(BaseModel):
    """Safe account fields exposed to administrators."""

    id: str
    email: str
    system_role: SystemRole
    created_at: datetime
    needs_setup: bool
    oauth_provider: str | None

    @classmethod
    def from_user(cls, user: User) -> AdminUserResponse:
        return cls(
            id=str(user.id),
            email=user.email,
            system_role=user.system_role,
            created_at=user.created_at,
            needs_setup=user.needs_setup,
            oauth_provider=user.oauth_provider,
        )


class AdminUserListResponse(BaseModel):
    users: list[AdminUserResponse]
    total: int


class UserRoleChangeRequest(BaseModel):
    system_role: SystemRole


class UserRoleChangeResponse(BaseModel):
    user: AdminUserResponse
    previous_role: SystemRole
    sessions_invalidated: bool


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


async def _require_session_admin(request: Request) -> User:
    """Require a real database-backed administrator session.

    Auth-disabled and static deployments intentionally expose a synthetic
    administrator for ordinary workspace features. That identity is not a
    registered account and must not unlock account administration.
    """
    # CSRFMiddleware intentionally skips checks in auth-disabled mode. Reject
    # this security-sensitive API outright even if the browser happens to keep
    # a previously issued real admin cookie, rather than serving a session
    # mutation without CSRF protection.
    if is_auth_disabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error("admin_required", "User management is unavailable when authentication is disabled."),
        )

    actor = await require_admin_user(
        request,
        detail=_error("admin_required", "A signed-in administrator is required."),
    )
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error("admin_required", "A signed-in administrator is required."),
        )
    return actor


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> AdminUserListResponse:
    """List registered local and OIDC users for an administrator."""
    await _require_session_admin(request)
    users, total = await get_local_provider().list_users(offset=offset, limit=limit)
    return AdminUserListResponse(
        users=[AdminUserResponse.from_user(user) for user in users],
        total=total,
    )


@router.patch("/{user_id}/role", response_model=UserRoleChangeResponse)
async def change_user_role(
    user_id: str,
    body: UserRoleChangeRequest,
    request: Request,
) -> UserRoleChangeResponse:
    """Change a user's role and revoke that user's existing JWT sessions."""
    actor = await _require_session_admin(request)
    try:
        result = await get_local_provider().change_user_role(
            actor_id=str(actor.id),
            user_id=user_id,
            system_role=body.system_role,
        )
    except AdminRoleRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error("admin_required", "Administrator privileges changed; refresh and try again."),
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("user_not_found", "User not found."),
        ) from exc
    except LastAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error("last_admin", "The final administrator cannot be demoted."),
        ) from exc

    if result.changed:
        logger.info(
            "User role changed actor_user_id=%s target_user_id=%s previous_role=%s new_role=%s sessions_invalidated=true",
            actor.id,
            result.user.id,
            result.previous_role,
            result.user.system_role,
        )

    return UserRoleChangeResponse(
        user=AdminUserResponse.from_user(result.user),
        previous_role=result.previous_role,
        sessions_invalidated=result.changed,
    )

"""Authorization context and capability constants for the auth plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from app.plugins.auth.domain.models import User


class Permissions:
    """Permission constants for resource:action format."""

    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"

    RUNS_CREATE = "runs:create"
    RUNS_READ = "runs:read"
    RUNS_CANCEL = "runs:cancel"


class AuthContext:
    """Authentication context for the current request."""

    __slots__ = ("user", "permissions")

    def __init__(self, user: User | None = None, permissions: list[str] | None = None):
        self.user = user
        self.permissions = permissions or []

    @property
    def is_authenticated(self) -> bool:
        return self.user is not None

    @property
    def principal_id(self) -> str | None:
        if self.user is None:
            return None
        return str(self.user.id)

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(self.permissions)

    def has_permission(self, resource: str, action: str) -> bool:
        return f"{resource}:{action}" in self.permissions

    def require_user(self) -> User:
        if not self.user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self.user


ALL_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


__all__ = ["ALL_PERMISSIONS", "AuthContext", "Permissions"]

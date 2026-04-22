"""Default permission provider hooks for auth-plugin authorization."""

from __future__ import annotations

from collections.abc import Callable

from app.plugins.auth.authorization.types import ALL_PERMISSIONS

PermissionProvider = Callable[[object], list[str]]


def default_permission_provider(user: object) -> list[str]:
    """Return the current static permission set for an authenticated user."""

    return list(ALL_PERMISSIONS)


__all__ = ["PermissionProvider", "default_permission_provider"]

"""Access control logic for knowledge base operations.

Implements the three-level permission model:
- CAN_READ: visibility-based (private/tenant/public)
- CAN_WRITE: owner, tenant_admin, explicit permission grant, or platform_admin
- CAN_ADMIN: owner, tenant_admin, explicit admin grant, or platform_admin
- CAN_CREATE: role-based per visibility level
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deerflow.persistence.knowledge_base.permission_repository import KbPermissionRepository


@dataclass(frozen=True)
class UserContext:
    """Minimal user info needed for access control checks."""

    user_id: str
    tenant_id: str
    role: str  # "superadmin" | "tenant_admin" | "user"


class KbAccessControl:
    def __init__(self, permission_repo: KbPermissionRepository) -> None:
        self._perm_repo = permission_repo

    def can_read(self, user: UserContext, kb: dict[str, Any]) -> bool:
        if kb.get("deleted_at") is not None:
            return False
        visibility = kb["visibility"]
        if visibility == "private":
            return kb["owner_user_id"] == user.user_id and kb["tenant_id"] == user.tenant_id
        if visibility == "tenant":
            return kb["tenant_id"] == user.tenant_id
        if visibility == "public":
            return True
        return False

    async def can_write(self, user: UserContext, kb: dict[str, Any]) -> bool:
        if kb.get("deleted_at") is not None:
            return False
        visibility = kb["visibility"]

        if visibility == "private":
            return kb["owner_user_id"] == user.user_id

        if visibility == "tenant":
            if user.role in ("superadmin", "tenant_admin") and kb["tenant_id"] == user.tenant_id:
                return True
            return await self._perm_repo.has_write_access(
                knowledge_base_id=kb["id"], user_id=user.user_id
            )

        if visibility == "public":
            return user.role == "superadmin"

        return False

    async def can_admin(self, user: UserContext, kb: dict[str, Any]) -> bool:
        if kb.get("deleted_at") is not None:
            return False
        visibility = kb["visibility"]

        if visibility == "private":
            return kb["owner_user_id"] == user.user_id

        if visibility == "tenant":
            if kb["tenant_id"] != user.tenant_id:
                return False
            if user.role in ("superadmin", "tenant_admin"):
                return True
            if kb["owner_user_id"] == user.user_id:
                return True
            role = await self._perm_repo.get_user_role(
                knowledge_base_id=kb["id"], user_id=user.user_id
            )
            return role == "admin"

        if visibility == "public":
            return user.role == "superadmin"

        return False

    def can_create(self, user: UserContext, visibility: str) -> bool:
        if visibility == "private":
            return True
        if visibility == "tenant":
            return user.role in ("superadmin", "tenant_admin")
        if visibility == "public":
            return user.role == "superadmin"
        return False

    async def get_user_kb_role(self, user: UserContext, kb: dict[str, Any]) -> str | None:
        """Determine the effective role a user has on a KB.

        Returns: "owner", "admin", "editor", "viewer", or None.
        """
        if kb["owner_user_id"] == user.user_id:
            return "owner"

        visibility = kb["visibility"]

        if visibility == "private":
            return None

        if visibility == "tenant":
            if kb["tenant_id"] != user.tenant_id:
                return None
            if user.role in ("superadmin", "tenant_admin"):
                return "admin"
            granted = await self._perm_repo.get_user_role(
                knowledge_base_id=kb["id"], user_id=user.user_id
            )
            if granted:
                return granted
            return "viewer"

        if visibility == "public":
            if user.role == "superadmin":
                return "admin"
            granted = await self._perm_repo.get_user_role(
                knowledge_base_id=kb["id"], user_id=user.user_id
            )
            if granted:
                return granted
            return "viewer"

        return None

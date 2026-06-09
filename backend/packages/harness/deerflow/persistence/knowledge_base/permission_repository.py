"""Repository for kb_permissions table — fine-grained write access grants."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.knowledge_base.model import KbPermissionRow


class KbPermissionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: KbPermissionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "knowledge_base_id": row.knowledge_base_id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "role": row.role,
            "granted_by": row.granted_by,
            "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
        }

    async def grant(
        self,
        *,
        knowledge_base_id: str,
        tenant_id: str,
        user_id: str,
        role: str,
        granted_by: str,
    ) -> dict[str, Any]:
        """Grant or update a permission. Upserts on (knowledge_base_id, user_id)."""
        async with self._sf() as session:
            stmt = select(KbPermissionRow).where(
                and_(
                    KbPermissionRow.knowledge_base_id == knowledge_base_id,
                    KbPermissionRow.user_id == user_id,
                )
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is not None:
                existing.role = role
                existing.granted_by = granted_by
                await session.commit()
                await session.refresh(existing)
                return self._row_to_dict(existing)

            row = KbPermissionRow(
                id=uuid4().hex,
                knowledge_base_id=knowledge_base_id,
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                granted_by=granted_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def revoke(self, *, knowledge_base_id: str, user_id: str) -> bool:
        """Remove a permission grant. Returns True if a row was deleted."""
        async with self._sf() as session:
            stmt = delete(KbPermissionRow).where(
                and_(
                    KbPermissionRow.knowledge_base_id == knowledge_base_id,
                    KbPermissionRow.user_id == user_id,
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def delete_by_kb(self, knowledge_base_id: str) -> int:
        """Remove all explicit permission grants for a knowledge base."""
        async with self._sf() as session:
            stmt = delete(KbPermissionRow).where(
                KbPermissionRow.knowledge_base_id == knowledge_base_id
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount

    async def list_by_kb(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        """List all permission grants for a knowledge base."""
        async with self._sf() as session:
            stmt = select(KbPermissionRow).where(
                KbPermissionRow.knowledge_base_id == knowledge_base_id
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars().all()]

    async def get_user_role(self, *, knowledge_base_id: str, user_id: str) -> str | None:
        """Get the granted role for a user on a KB, or None if no grant exists."""
        async with self._sf() as session:
            stmt = select(KbPermissionRow.role).where(
                and_(
                    KbPermissionRow.knowledge_base_id == knowledge_base_id,
                    KbPermissionRow.user_id == user_id,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def has_write_access(self, *, knowledge_base_id: str, user_id: str) -> bool:
        """Check if user has editor or admin role on the KB."""
        role = await self.get_user_role(knowledge_base_id=knowledge_base_id, user_id=user_id)
        return role in ("editor", "admin")

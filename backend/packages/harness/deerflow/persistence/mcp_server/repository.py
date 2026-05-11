"""SQLAlchemy-backed repository for tenant MCP server configurations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.mcp_server.model import TenantMcpServerRow


class TenantMcpServerRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        tenant_id: str,
        server_name: str,
        config: dict,
        created_by: str,
        display_name: str | None = None,
        description: str | None = None,
        enabled: bool = True,
    ) -> dict:
        row = TenantMcpServerRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            server_name=server_name,
            display_name=display_name,
            description=description,
            config=config,
            enabled=enabled,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def get_by_name(self, tenant_id: str, server_name: str) -> dict | None:
        async with self._sf() as session:
            stmt = select(TenantMcpServerRow).where(
                TenantMcpServerRow.tenant_id == tenant_id,
                TenantMcpServerRow.server_name == server_name,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def list_by_tenant(self, tenant_id: str, *, include_disabled: bool = False) -> list[dict]:
        async with self._sf() as session:
            stmt = select(TenantMcpServerRow).where(TenantMcpServerRow.tenant_id == tenant_id)
            if not include_disabled:
                stmt = stmt.where(TenantMcpServerRow.enabled == True)  # noqa: E712
            stmt = stmt.order_by(TenantMcpServerRow.server_name)
            result = await session.execute(stmt)
            return [row.to_dict() for row in result.scalars().all()]

    async def update(self, tenant_id: str, server_name: str, **fields) -> dict | None:
        fields["updated_at"] = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(TenantMcpServerRow)
                .where(TenantMcpServerRow.tenant_id == tenant_id, TenantMcpServerRow.server_name == server_name)
                .values(**fields)
            )
            await session.execute(stmt)
            await session.commit()
            return await self.get_by_name(tenant_id, server_name)

    async def set_enabled(self, tenant_id: str, server_name: str, enabled: bool) -> dict | None:
        return await self.update(tenant_id, server_name, enabled=enabled)

    async def delete(self, tenant_id: str, server_name: str) -> bool:
        async with self._sf() as session:
            stmt = delete(TenantMcpServerRow).where(
                TenantMcpServerRow.tenant_id == tenant_id,
                TenantMcpServerRow.server_name == server_name,
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

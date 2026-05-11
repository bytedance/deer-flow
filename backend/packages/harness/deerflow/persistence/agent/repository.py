"""SQLAlchemy-backed repository for tenant agents and permissions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.agent.model import AgentPermissionRow, AgentRow


class AgentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        tenant_id: str,
        name: str,
        created_by: str,
        display_name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        visibility: str = "tenant_public",
        model: str | None = None,
        tool_groups: list[str] | None = None,
        skills: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        row = AgentRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            display_name=display_name,
            description=description,
            icon=icon,
            visibility=visibility,
            model=model,
            tool_groups=tool_groups,
            skills=skills,
            mcp_servers=mcp_servers,
            tags=tags,
            enabled=True,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def get_by_name(self, tenant_id: str, name: str) -> dict | None:
        async with self._sf() as session:
            stmt = select(AgentRow).where(AgentRow.tenant_id == tenant_id, AgentRow.name == name)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def list_by_tenant(self, tenant_id: str, *, include_disabled: bool = False) -> list[dict]:
        async with self._sf() as session:
            stmt = select(AgentRow).where(AgentRow.tenant_id == tenant_id)
            if not include_disabled:
                stmt = stmt.where(AgentRow.enabled == True)  # noqa: E712
            stmt = stmt.order_by(AgentRow.name)
            result = await session.execute(stmt)
            return [row.to_dict() for row in result.scalars().all()]

    async def list_visible(self, tenant_id: str, user_id: str) -> list[dict]:
        """List agents visible to a specific user (public + restricted with permission)."""
        async with self._sf() as session:
            public_stmt = select(AgentRow).where(
                AgentRow.tenant_id == tenant_id,
                AgentRow.visibility == "tenant_public",
                AgentRow.enabled == True,  # noqa: E712
            )
            public_result = await session.execute(public_stmt)
            agents = list(public_result.scalars().all())

            restricted_stmt = (
                select(AgentRow)
                .join(AgentPermissionRow, AgentPermissionRow.agent_id == AgentRow.id)
                .where(
                    AgentRow.tenant_id == tenant_id,
                    AgentRow.visibility == "tenant_restricted",
                    AgentRow.enabled == True,  # noqa: E712
                    AgentPermissionRow.principal_type == "user",
                    AgentPermissionRow.principal_id == user_id,
                )
            )
            restricted_result = await session.execute(restricted_stmt)
            agents.extend(restricted_result.scalars().all())

            return [row.to_dict() for row in sorted(agents, key=lambda r: r.name)]

    async def update(self, tenant_id: str, name: str, **fields) -> dict | None:
        fields["updated_at"] = datetime.now(UTC)
        async with self._sf() as session:
            stmt = update(AgentRow).where(AgentRow.tenant_id == tenant_id, AgentRow.name == name).values(**fields)
            await session.execute(stmt)
            await session.commit()
            return await self.get_by_name(tenant_id, name)

    async def set_enabled(self, tenant_id: str, name: str, enabled: bool) -> dict | None:
        return await self.update(tenant_id, name, enabled=enabled)

    async def delete(self, tenant_id: str, name: str) -> bool:
        async with self._sf() as session:
            stmt = delete(AgentRow).where(AgentRow.tenant_id == tenant_id, AgentRow.name == name)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0


class AgentPermissionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def grant(self, *, agent_id: str, principal_type: str, principal_id: str) -> dict:
        row = AgentPermissionRow(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            principal_type=principal_type,
            principal_id=principal_id,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def revoke(self, *, agent_id: str, principal_type: str, principal_id: str) -> bool:
        async with self._sf() as session:
            stmt = delete(AgentPermissionRow).where(
                AgentPermissionRow.agent_id == agent_id,
                AgentPermissionRow.principal_type == principal_type,
                AgentPermissionRow.principal_id == principal_id,
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def list_for_agent(self, agent_id: str) -> list[dict]:
        async with self._sf() as session:
            stmt = select(AgentPermissionRow).where(AgentPermissionRow.agent_id == agent_id)
            result = await session.execute(stmt)
            return [row.to_dict() for row in result.scalars().all()]

    async def set_permissions(self, agent_id: str, permissions: list[dict]) -> list[dict]:
        """Replace all permissions for an agent."""
        async with self._sf() as session:
            await session.execute(delete(AgentPermissionRow).where(AgentPermissionRow.agent_id == agent_id))
            rows = []
            for perm in permissions:
                row = AgentPermissionRow(
                    id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    principal_type=perm["principal_type"],
                    principal_id=perm["principal_id"],
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                rows.append(row)
            await session.commit()
            return [r.to_dict() for r in rows]

"""Repository for agent usage statistics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.agent.usage_model import AgentUsageRow


class AgentUsageRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(self, *, tenant_id: str, agent_name: str, user_id: str) -> None:
        row = AgentUsageRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            agent_name=agent_name,
            user_id=user_id,
            used_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    async def count_by_agent(self, tenant_id: str, agent_name: str) -> int:
        async with self._sf() as session:
            stmt = select(func.count()).where(
                AgentUsageRow.tenant_id == tenant_id,
                AgentUsageRow.agent_name == agent_name,
            )
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def count_by_tenant(self, tenant_id: str) -> list[dict]:
        async with self._sf() as session:
            stmt = (
                select(AgentUsageRow.agent_name, func.count().label("count"))
                .where(AgentUsageRow.tenant_id == tenant_id)
                .group_by(AgentUsageRow.agent_name)
                .order_by(func.count().desc())
            )
            result = await session.execute(stmt)
            return [{"agent_name": row[0], "count": row[1]} for row in result.all()]

    async def count_by_user(self, user_id: str) -> list[dict]:
        async with self._sf() as session:
            stmt = (
                select(AgentUsageRow.agent_name, func.count().label("count"))
                .where(AgentUsageRow.user_id == user_id)
                .group_by(AgentUsageRow.agent_name)
                .order_by(func.count().desc())
            )
            result = await session.execute(stmt)
            return [{"agent_name": row[0], "count": row[1]} for row in result.all()]

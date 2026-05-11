"""Repository for agent usage statistics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.agent.usage_model import AgentUsageRow


class AgentUsageRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(
        self,
        *,
        tenant_id: str,
        agent_name: str,
        user_id: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        token_input: int = 0,
        token_output: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        row = AgentUsageRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            agent_name=agent_name,
            user_id=user_id,
            thread_id=thread_id,
            run_id=run_id,
            token_input=token_input,
            token_output=token_output,
            duration_ms=duration_ms,
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

    async def stats_by_tenant(self, tenant_id: str, *, period_days: int | None = None) -> list[dict]:
        """Aggregate usage stats grouped by agent_name for a tenant."""
        async with self._sf() as session:
            conditions = [AgentUsageRow.tenant_id == tenant_id]
            if period_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=period_days)
                conditions.append(AgentUsageRow.used_at >= cutoff)

            stmt = (
                select(
                    AgentUsageRow.agent_name,
                    func.count().label("count"),
                    func.sum(AgentUsageRow.token_input).label("token_input_total"),
                    func.sum(AgentUsageRow.token_output).label("token_output_total"),
                    func.avg(AgentUsageRow.duration_ms).label("avg_duration_ms"),
                    func.max(AgentUsageRow.used_at).label("last_used_at"),
                )
                .where(*conditions)
                .group_by(AgentUsageRow.agent_name)
                .order_by(func.count().desc())
            )
            result = await session.execute(stmt)
            return [
                {
                    "agent_name": row.agent_name,
                    "count": row.count,
                    "token_input_total": row.token_input_total or 0,
                    "token_output_total": row.token_output_total or 0,
                    "avg_duration_ms": int(row.avg_duration_ms) if row.avg_duration_ms else None,
                    "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                }
                for row in result.all()
            ]

    async def stats_for_agent(self, tenant_id: str, agent_name: str, *, period_days: int | None = None) -> dict:
        """Detailed stats for a single agent within a tenant."""
        async with self._sf() as session:
            conditions = [AgentUsageRow.tenant_id == tenant_id, AgentUsageRow.agent_name == agent_name]
            if period_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=period_days)
                conditions.append(AgentUsageRow.used_at >= cutoff)

            stmt = select(
                func.count().label("count"),
                func.sum(AgentUsageRow.token_input).label("token_input_total"),
                func.sum(AgentUsageRow.token_output).label("token_output_total"),
                func.avg(AgentUsageRow.duration_ms).label("avg_duration_ms"),
                func.max(AgentUsageRow.used_at).label("last_used_at"),
                func.count(func.distinct(AgentUsageRow.user_id)).label("unique_users"),
            ).where(*conditions)

            result = await session.execute(stmt)
            row = result.one()
            return {
                "agent_name": agent_name,
                "count": row.count or 0,
                "token_input_total": row.token_input_total or 0,
                "token_output_total": row.token_output_total or 0,
                "avg_duration_ms": int(row.avg_duration_ms) if row.avg_duration_ms else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "unique_users": row.unique_users or 0,
            }

    async def stats_by_user(self, user_id: str, *, period_days: int | None = None) -> list[dict]:
        """Aggregate usage stats grouped by agent_name for a specific user."""
        async with self._sf() as session:
            conditions = [AgentUsageRow.user_id == user_id]
            if period_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=period_days)
                conditions.append(AgentUsageRow.used_at >= cutoff)

            stmt = (
                select(
                    AgentUsageRow.agent_name,
                    func.count().label("count"),
                    func.sum(AgentUsageRow.token_input).label("token_input_total"),
                    func.sum(AgentUsageRow.token_output).label("token_output_total"),
                    func.avg(AgentUsageRow.duration_ms).label("avg_duration_ms"),
                    func.max(AgentUsageRow.used_at).label("last_used_at"),
                )
                .where(*conditions)
                .group_by(AgentUsageRow.agent_name)
                .order_by(func.count().desc())
            )
            result = await session.execute(stmt)
            return [
                {
                    "agent_name": row.agent_name,
                    "count": row.count,
                    "token_input_total": row.token_input_total or 0,
                    "token_output_total": row.token_output_total or 0,
                    "avg_duration_ms": int(row.avg_duration_ms) if row.avg_duration_ms else None,
                    "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                }
                for row in result.all()
            ]

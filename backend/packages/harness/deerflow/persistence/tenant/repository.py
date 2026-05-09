"""Async SQLAlchemy-backed tenant repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.config.tenant_storage import TenantConfig
from deerflow.persistence.tenant.model import TenantRow


class TenantRepository:
    """Database-backed tenant storage. Replaces JSON-file TenantStorage."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_config(row: TenantRow) -> TenantConfig:
        return TenantConfig(
            tenant_id=row.tenant_id,
            name=row.name,
            created_at=row.created_at.isoformat() if row.created_at else "",
            is_active=row.is_active,
            daily_quota_usd=row.daily_quota_usd,
            monthly_quota_usd=row.monthly_quota_usd,
        )

    async def list_all(self) -> list[TenantConfig]:
        stmt = select(TenantRow).order_by(TenantRow.created_at)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_config(row) for row in result.scalars().all()]

    async def get(self, tenant_id: str) -> TenantConfig | None:
        async with self._sf() as session:
            row = await session.get(TenantRow, tenant_id)
            return self._row_to_config(row) if row else None

    async def create(self, config: TenantConfig) -> TenantConfig:
        async with self._sf() as session:
            existing = await session.get(TenantRow, config.tenant_id)
            if existing is not None:
                raise ValueError(f"Tenant {config.tenant_id!r} already exists")
            now = datetime.now(UTC)
            row = TenantRow(
                tenant_id=config.tenant_id,
                name=config.name,
                is_active=config.is_active,
                daily_quota_usd=config.daily_quota_usd,
                monthly_quota_usd=config.monthly_quota_usd,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_config(row)

    async def update(self, tenant_id: str, **fields) -> TenantConfig | None:
        async with self._sf() as session:
            row = await session.get(TenantRow, tenant_id)
            if row is None:
                return None
            for key, value in fields.items():
                if value is not None and hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_config(row)

    async def delete(self, tenant_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(TenantRow, tenant_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def ensure_default(self) -> TenantConfig:
        existing = await self.get("default")
        if existing is not None:
            return existing
        config = TenantConfig(
            tenant_id="default",
            name="Default Tenant",
            created_at=datetime.now(UTC).isoformat(),
        )
        return await self.create(config)

"""SQLAlchemy-backed repository for tenant HTTP connector configurations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.http_connector.model import TenantHttpConnectorRow


class TenantHttpConnectorRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        tenant_id: str,
        connector_name: str,
        url: str,
        method: str = "GET",
        created_by: str,
        display_name: str | None = None,
        description: str | None = None,
        headers: dict | None = None,
        auth_type: str = "none",
        auth_token_env: str | None = None,
        auth_header: str = "Authorization",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 524288,
        max_retries: int = 1,
        retry_on_status: list[int] | None = None,
        cache_ttl_seconds: int | None = None,
        enabled: bool = True,
    ) -> dict:
        row = TenantHttpConnectorRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            connector_name=connector_name,
            display_name=display_name,
            description=description,
            url=url,
            method=method,
            headers=headers or {},
            auth_type=auth_type,
            auth_token_env=auth_token_env,
            auth_header=auth_header,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            max_retries=max_retries,
            retry_on_status=retry_on_status or [502, 503, 504],
            cache_ttl_seconds=cache_ttl_seconds,
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

    async def get_by_name(self, tenant_id: str, connector_name: str) -> dict | None:
        async with self._sf() as session:
            stmt = select(TenantHttpConnectorRow).where(
                TenantHttpConnectorRow.tenant_id == tenant_id,
                TenantHttpConnectorRow.connector_name == connector_name,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def list_by_tenant(self, tenant_id: str, *, include_disabled: bool = False) -> list[dict]:
        async with self._sf() as session:
            stmt = select(TenantHttpConnectorRow).where(TenantHttpConnectorRow.tenant_id == tenant_id)
            if not include_disabled:
                stmt = stmt.where(TenantHttpConnectorRow.enabled.is_(True))
            stmt = stmt.order_by(TenantHttpConnectorRow.connector_name)
            result = await session.execute(stmt)
            return [row.to_dict() for row in result.scalars().all()]

    async def update(self, tenant_id: str, connector_name: str, **fields) -> dict | None:
        fields["updated_at"] = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(TenantHttpConnectorRow)
                .where(
                    TenantHttpConnectorRow.tenant_id == tenant_id,
                    TenantHttpConnectorRow.connector_name == connector_name,
                )
                .values(**fields)
            )
            await session.execute(stmt)
            await session.commit()
            return await self.get_by_name(tenant_id, connector_name)

    async def delete(self, tenant_id: str, connector_name: str) -> bool:
        async with self._sf() as session:
            stmt = delete(TenantHttpConnectorRow).where(
                TenantHttpConnectorRow.tenant_id == tenant_id,
                TenantHttpConnectorRow.connector_name == connector_name,
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def set_enabled(self, tenant_id: str, connector_name: str, enabled: bool) -> dict | None:
        return await self.update(tenant_id, connector_name, enabled=enabled)

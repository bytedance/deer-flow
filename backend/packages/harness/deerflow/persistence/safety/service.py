"""Transactional creation and handling of content-safety incidents."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .model import AdminAuditLogRow, RiskEventRow


class ContentSafetyService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_risk_event(
        self,
        *,
        user_id: str,
        thread_id: str,
        run_id: str | None,
        direction: str,
        category: str,
        severity: str,
        rule_version: str,
        confidence_bps: int,
        redacted_excerpt: str,
    ) -> RiskEventRow:
        event = RiskEventRow(
            id=uuid4().hex,
            user_id=user_id,
            thread_id=thread_id,
            run_id=run_id,
            direction=direction,
            category=category,
            severity=severity,
            rule_version=rule_version,
            confidence_bps=confidence_bps,
            redacted_excerpt=redacted_excerpt,
        )
        async with self._sf() as session:
            async with session.begin():
                session.add(event)
                session.add(self._audit("safety.detected", event.id, actor_user_id=None))
            return event

    async def record_context_access(self, event_id: str, *, actor_user_id: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("A context access reason is required")
        async with self._sf() as session:
            async with session.begin():
                event = await session.get(RiskEventRow, event_id, with_for_update=True)
                if event is None:
                    raise LookupError("Risk event not found")
                session.add(self._audit("safety.context_viewed", event_id, actor_user_id=actor_user_id, reason=reason.strip()))

    async def list_audit_actions(self, event_id: str) -> list[str]:
        async with self._sf() as session:
            rows = await session.scalars(select(AdminAuditLogRow.action).where(AdminAuditLogRow.target_type == "risk_event", AdminAuditLogRow.target_id == event_id).order_by(AdminAuditLogRow.created_at, AdminAuditLogRow.id))
            return list(rows)

    async def record_admin_action(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        actor_user_id: str | None,
        reason: str | None = None,
        before_summary: dict | None = None,
        after_summary: dict | None = None,
    ) -> None:
        """Persist a metadata-only audit record for a privileged operation."""
        async with self._sf() as session:
            async with session.begin():
                session.add(
                    AdminAuditLogRow(
                        id=uuid4().hex,
                        actor_user_id=actor_user_id,
                        action=action,
                        target_type=target_type,
                        target_id=target_id,
                        reason=reason,
                        before_summary=before_summary or {},
                        after_summary=after_summary or {},
                    )
                )

    async def resolve_risk_event(
        self,
        event_id: str,
        *,
        actor_user_id: str,
        resolution: str,
        reason: str,
    ) -> RiskEventRow:
        if not reason.strip():
            raise ValueError("A resolution reason is required")
        async with self._sf() as session:
            async with session.begin():
                event = await session.get(RiskEventRow, event_id, with_for_update=True)
                if event is None:
                    raise LookupError("Risk event not found")
                event.status = "resolved"
                event.resolution = resolution
                event.resolution_reason = reason.strip()
                event.resolved_at = datetime.now(UTC)
                session.add(self._audit("safety.resolved", event.id, actor_user_id=actor_user_id, reason=reason.strip()))
            return event

    @staticmethod
    def _audit(action: str, target_id: str, *, actor_user_id: str | None, reason: str | None = None) -> AdminAuditLogRow:
        return AdminAuditLogRow(
            id=uuid4().hex,
            actor_user_id=actor_user_id,
            action=action,
            target_type="risk_event",
            target_id=target_id,
            reason=reason,
        )

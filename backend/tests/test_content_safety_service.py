"""Persistence contracts for content-safety incidents and administrator audit logs."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.anyio
async def test_creating_risk_event_writes_an_immutable_detection_record_and_audit_log(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.safety.service import ContentSafetyService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'safety.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        service = ContentSafetyService(sessions)

        event = await service.create_risk_event(
            user_id="tenant-a",
            thread_id="thread-1",
            run_id="run-1",
            direction="output",
            category="unsafe_content",
            severity="high",
            rule_version="local-v1",
            confidence_bps=9800,
            redacted_excerpt="危险***",
        )

        assert event.user_id == "tenant-a"
        assert event.status == "open"
        async with sessions() as session:
            from deerflow.persistence.safety.model import AdminAuditLogRow

            logs = list(await session.scalars(select(AdminAuditLogRow)))
        assert [(log.action, log.target_id) for log in logs] == [("safety.detected", event.id)]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_context_access_requires_a_reason_and_is_audited(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.safety.service import ContentSafetyService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'safety.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        service = ContentSafetyService(async_sessionmaker(engine, expire_on_commit=False))
        event = await service.create_risk_event(
            user_id="tenant-a",
            thread_id="thread-1",
            run_id="run-1",
            direction="input",
            category="unsafe_content",
            severity="high",
            rule_version="local-v1",
            confidence_bps=9800,
            redacted_excerpt="危险***",
        )

        with pytest.raises(ValueError, match="reason"):
            await service.record_context_access(event.id, actor_user_id="reviewer-1", reason=" ")
        await service.record_context_access(event.id, actor_user_id="reviewer-1", reason="处理风险事件")

        assert await service.list_audit_actions(event.id) == [
            "safety.detected",
            "safety.context_viewed",
        ]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_admin_operation_is_recorded_with_safe_before_and_after_summaries(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.safety.model import AdminAuditLogRow
    from deerflow.persistence.safety.service import ContentSafetyService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'safety.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        await ContentSafetyService(sessions).record_admin_action(
            action="billing.credits_adjusted",
            target_type="tenant",
            target_id="tenant-a",
            actor_user_id="admin-a",
            reason="补偿",
            before_summary={"available_credits": 10},
            after_summary={"available_credits": 30},
        )

        async with sessions() as session:
            log = await session.scalar(select(AdminAuditLogRow))
        assert log is not None
        assert log.action == "billing.credits_adjusted"
        assert log.before_summary == {"available_credits": 10}
        assert log.after_summary == {"available_credits": 30}
    finally:
        await engine.dispose()

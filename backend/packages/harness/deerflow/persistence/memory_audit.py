"""Audit logging for memory CRUD operations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.models.memory_audit import MemoryAuditRow

logger = logging.getLogger(__name__)


async def log_memory_audit(
    tenant_id: str,
    user_id: str,
    action: str,
    layer: str,
    fact_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Log a memory operation to the audit table.

    Args:
        tenant_id: Tenant identifier.
        user_id: User who performed the action.
        action: Operation type ("create", "update", "delete").
        layer: Memory layer ("user", "session", "domain").
        fact_id: Identifier of the affected fact.
        before: Fact state before the operation (for update/delete).
        after: Fact state after the operation (for create/update).
    """
    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("Persistence not available, skipping audit log")
        return

    try:
        async with session_factory() as session:
            row = MemoryAuditRow(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                layer=layer,
                fact_id=fact_id,
                before=before,
                after=after,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
    except Exception:
        logger.exception("Failed to log memory audit entry")

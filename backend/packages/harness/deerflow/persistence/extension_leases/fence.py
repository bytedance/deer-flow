"""Validate under a row lock retained through Agent admission commit."""

from sqlalchemy import select, text

from .model import ExtensionExecutionLeaseRow


async def lock_execution_fence(session, fence, user_id):
    from deerflow.runtime.runs.manager import ConflictError

    row = (
        await session.execute(
            select(ExtensionExecutionLeaseRow)
            .where(
                ExtensionExecutionLeaseRow.namespace == fence.namespace,
                ExtensionExecutionLeaseRow.resource_id == fence.resource_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    # Read the database clock AFTER any lock wait, never transaction-start now().
    postgres = session.get_bind().dialect.name == "postgresql"
    now = await session.scalar(text("SELECT extract(epoch from clock_timestamp())" if postgres else "SELECT (julianday('now') - 2440587.5) * 86400.0"))
    if row is None or row.user_id != user_id or row.holder_id != fence.holder_id or row.epoch != fence.epoch or row.expires_at <= float(now):
        raise ConflictError("Stale or unavailable extension execution fence")

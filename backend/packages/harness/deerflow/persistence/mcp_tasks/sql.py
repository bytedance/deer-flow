from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.mcp.tasks import ATTENTION_TASK_STATUSES, POLLABLE_TASK_STATUSES, TERMINAL_TASK_STATUSES
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.utils.time import coerce_iso

_POLLABLE_STATUS_VALUES = tuple(status.value for status in POLLABLE_TASK_STATUSES)
_ATTENTION_STATUS_VALUES = frozenset(status.value for status in ATTENTION_TASK_STATUSES)
_TERMINAL_STATUS_VALUES = frozenset(status.value for status in TERMINAL_TASK_STATUSES)
_TIMESTAMP_FIELDS = (
    "next_poll_at",
    "last_polled_at",
    "lease_expires_at",
    "cancel_requested_at",
    "completed_at",
    "created_at",
    "updated_at",
)


class DuplicateMcpRemoteTaskError(RuntimeError):
    """The current user already tracks this server's remote task handle."""


def _is_remote_task_unique_conflict(exc: IntegrityError) -> bool:
    original = exc.orig
    diagnostic = getattr(original, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "uq_mcp_tasks_user_server_remote":
        return True
    message = str(original)
    return "uq_mcp_tasks_user_server_remote" in message or "mcp_tasks.user_id, mcp_tasks.server_name, mcp_tasks.remote_task_id" in message


class McpTaskRepository:
    """Durable source of truth for long-running MCP task lifecycle state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: McpTaskRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in _TIMESTAMP_FIELDS:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        task_id: str,
        user_id: str,
        thread_id: str,
        run_id: str | None,
        tool_call_id: str | None,
        server_name: str,
        driver_name: str,
        remote_task_id: str,
        task_name: str,
        status: str,
        result: Any | None,
        result_preview: str | None,
        result_truncated: bool,
        result_artifact: dict[str, str] | None,
        error: str | None,
        input_required: dict[str, Any] | None,
        next_poll_at: datetime | None,
        driver_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        needs_attention = status in _ATTENTION_STATUS_VALUES
        row = McpTaskRow(
            id=task_id,
            user_id=user_id,
            thread_id=thread_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            server_name=server_name,
            driver_name=driver_name,
            remote_task_id=remote_task_id,
            task_name=task_name,
            status=status,
            result=result,
            result_preview=result_preview,
            result_truncated=result_truncated,
            result_artifact=result_artifact,
            error=error,
            input_required=input_required,
            driver_data=dict(driver_data or {}),
            notification_status="pending" if needs_attention else "none",
            next_poll_at=next_poll_at,
            completed_at=now if status in _TERMINAL_STATUS_VALUES else None,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if _is_remote_task_unique_conflict(exc):
                    raise DuplicateMcpRemoteTaskError(f"Remote MCP task {remote_task_id!r} is already tracked for server {server_name!r} by this user") from exc
                raise
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, task_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(McpTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str,
        limit: int = 50,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        stmt = select(McpTaskRow).where(
            McpTaskRow.thread_id == thread_id,
            McpTaskRow.user_id == user_id,
        )
        if active_only:
            stmt = stmt.where(McpTaskRow.status.in_(_POLLABLE_STATUS_VALUES))
        stmt = stmt.order_by(McpTaskRow.created_at.desc(), McpTaskRow.id.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def claim_due_tasks(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(McpTaskRow)
            .where(
                McpTaskRow.status.in_(_POLLABLE_STATUS_VALUES),
                McpTaskRow.next_poll_at.is_not(None),
                McpTaskRow.next_poll_at <= now,
                or_(
                    McpTaskRow.lease_expires_at.is_(None),
                    McpTaskRow.lease_expires_at < now,
                ),
            )
            .order_by(McpTaskRow.next_poll_at.asc(), McpTaskRow.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.lease_owner = lease_owner
                row.lease_expires_at = lease_expires_at
                row.poll_attempt_count += 1
                row.updated_at = now
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def apply_snapshot(
        self,
        task_id: str,
        *,
        lease_owner: str,
        status: str,
        result: Any | None,
        result_preview: str | None,
        result_truncated: bool,
        result_artifact: dict[str, str] | None,
        error: str | None,
        input_required: dict[str, Any] | None,
        next_poll_at: datetime | None,
        polled_at: datetime,
    ) -> bool:
        values: dict[str, Any] = {
            "status": status,
            "result": result,
            "result_preview": result_preview,
            "result_truncated": result_truncated,
            "result_artifact": result_artifact,
            "error": error,
            "input_required": input_required,
            "next_poll_at": next_poll_at,
            "last_polled_at": polled_at,
            "last_poll_error": None,
            "consecutive_poll_error_count": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": polled_at,
        }
        if status in _ATTENTION_STATUS_VALUES:
            values["notification_status"] = "pending"
        if status in _TERMINAL_STATUS_VALUES:
            values["completed_at"] = polled_at

        stmt = (
            update(McpTaskRow)
            .where(
                McpTaskRow.id == task_id,
                McpTaskRow.lease_owner == lease_owner,
                McpTaskRow.lease_expires_at >= polled_at,
            )
            .values(**values)
        )
        async with self._sf() as session:
            result_proxy = await session.execute(stmt)
            await session.commit()
            return bool(result_proxy.rowcount)

    async def release_claim(
        self,
        task_id: str,
        *,
        lease_owner: str,
        next_poll_at: datetime,
        error: str,
    ) -> bool:
        stmt = (
            update(McpTaskRow)
            .where(
                McpTaskRow.id == task_id,
                McpTaskRow.lease_owner == lease_owner,
            )
            .values(
                next_poll_at=next_poll_at,
                last_poll_error=error,
                consecutive_poll_error_count=McpTaskRow.consecutive_poll_error_count + 1,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=datetime.now(UTC),
            )
        )
        async with self._sf() as session:
            result_proxy = await session.execute(stmt)
            await session.commit()
            return bool(result_proxy.rowcount)

from __future__ import annotations

import hashlib
import json
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
    "notification_lease_expires_at",
    "next_notification_at",
    "cancel_requested_at",
    "next_cancel_at",
    "completed_at",
    "created_at",
    "updated_at",
)

_INFLIGHT_NOTIFICATION_STATUSES = frozenset({"claimed", "dispatched", "retry"})


def _notification_event(row: McpTaskRow, *, tracking_degraded: bool) -> dict[str, Any] | None:
    if row.status not in _ATTENTION_STATUS_VALUES and not tracking_degraded:
        return None
    return {
        "task_id": row.id,
        "task_name": row.task_name,
        "status": row.status,
        "result": row.result,
        "result_preview": row.result_preview,
        "result_truncated": bool(row.result_truncated),
        "result_artifact": row.result_artifact,
        "error": row.error,
        "input_required": row.input_required,
        "tracking_degraded": tracking_degraded,
        "last_poll_error": row.last_poll_error if tracking_degraded else None,
    }


def _event_fingerprint(event: dict[str, Any]) -> str:
    encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_event_if_changed(row: McpTaskRow, *, tracking_degraded: bool, now: datetime) -> bool:
    event = _notification_event(row, tracking_degraded=tracking_degraded)
    if event is None:
        return False
    fingerprint = _event_fingerprint(event)
    if fingerprint == row.event_fingerprint:
        return False
    row.event_fingerprint = fingerprint
    row.event_version = int(row.event_version or 0) + 1
    if row.notification_status not in _INFLIGHT_NOTIFICATION_STATUSES:
        row.notification_status = "pending"
        row.next_notification_at = now
        row.notification_error = None
        row.notification_attempt_count = 0
        row.dispatch_version = None
        row.dispatch_attempt = 0
        row.dispatch_event = None
        row.notification_run_id = None
    return True


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
            notification_status="none",
            next_poll_at=next_poll_at,
            completed_at=now if status in _TERMINAL_STATUS_VALUES else None,
            created_at=now,
            updated_at=now,
        )
        _record_event_if_changed(row, tracking_degraded=False, now=now)
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
                McpTaskRow.cancel_requested_at.is_(None),
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
        async with self._sf() as session:
            stmt = (
                select(McpTaskRow)
                .where(
                    McpTaskRow.id == task_id,
                    McpTaskRow.lease_owner == lease_owner,
                    McpTaskRow.lease_expires_at >= polled_at,
                    McpTaskRow.status.not_in(_TERMINAL_STATUS_VALUES),
                    McpTaskRow.cancel_requested_at.is_(None),
                )
                .with_for_update()
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return False
            row.status = status
            row.result = result
            row.result_preview = result_preview
            row.result_truncated = result_truncated
            row.result_artifact = result_artifact
            row.error = error
            row.input_required = input_required
            row.next_poll_at = next_poll_at
            row.last_polled_at = polled_at
            row.last_poll_error = None
            row.consecutive_poll_error_count = 0
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = polled_at
            if status in _TERMINAL_STATUS_VALUES:
                row.completed_at = polled_at
            _record_event_if_changed(row, tracking_degraded=False, now=polled_at)
            await session.commit()
            return True

    async def release_claim(
        self,
        task_id: str,
        *,
        lease_owner: str,
        next_poll_at: datetime,
        error: str,
        tracking_degraded_after_errors: int = 3,
    ) -> bool:
        async with self._sf() as session:
            stmt = select(McpTaskRow).where(McpTaskRow.id == task_id, McpTaskRow.lease_owner == lease_owner).with_for_update()
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return False
            now = datetime.now(UTC)
            row.next_poll_at = next_poll_at
            row.last_poll_error = error
            row.consecutive_poll_error_count = int(row.consecutive_poll_error_count or 0) + 1
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = now
            _record_event_if_changed(
                row,
                tracking_degraded=row.consecutive_poll_error_count >= tracking_degraded_after_errors,
                now=now,
            )
            await session.commit()
            return True

    async def request_cancel(
        self,
        task_id: str,
        *,
        user_id: str,
        thread_id: str,
        requested_at: datetime,
    ) -> dict[str, Any] | None:
        """Persist a user-scoped cancellation request without exposing the remote id."""
        async with self._sf() as session:
            stmt = (
                select(McpTaskRow)
                .where(
                    McpTaskRow.id == task_id,
                    McpTaskRow.user_id == user_id,
                    McpTaskRow.thread_id == thread_id,
                )
                .with_for_update()
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            if row.status not in _TERMINAL_STATUS_VALUES and row.cancel_requested_at is None:
                row.cancel_requested_at = requested_at
                if row.next_cancel_at is None:
                    row.next_cancel_at = requested_at
                # A cancel request fences any in-flight poll result, so its
                # poll lease can be released immediately for the cancellation
                # worker. A repeated request must preserve an existing cancel
                # lease so it cannot trigger a concurrent remote cancellation.
                row.lease_owner = None
                row.lease_expires_at = None
                row.updated_at = requested_at
                await session.commit()
            return self._row_to_dict(row)

    async def claim_cancel_requests(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(McpTaskRow).where(
            McpTaskRow.cancel_requested_at.is_not(None),
            McpTaskRow.status.not_in(_TERMINAL_STATUS_VALUES),
            McpTaskRow.next_cancel_at.is_not(None),
            McpTaskRow.next_cancel_at <= now,
            or_(McpTaskRow.lease_expires_at.is_(None), McpTaskRow.lease_expires_at < now),
        )
        if task_id is not None:
            stmt = stmt.where(McpTaskRow.id == task_id)
        stmt = stmt.order_by(McpTaskRow.next_cancel_at.asc(), McpTaskRow.id.asc()).limit(limit).with_for_update(skip_locked=True)
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
            expires_at = now + timedelta(seconds=lease_seconds)
            for row in rows:
                row.lease_owner = lease_owner
                row.lease_expires_at = expires_at
                row.cancel_attempt_count = int(row.cancel_attempt_count or 0) + 1
                row.updated_at = now
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def apply_cancel_snapshot(
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
        completed_at: datetime,
    ) -> bool:
        if status not in _TERMINAL_STATUS_VALUES:
            raise ValueError("A cancellation response must report a terminal task status")
        async with self._sf() as session:
            stmt = (
                select(McpTaskRow)
                .where(
                    McpTaskRow.id == task_id,
                    McpTaskRow.lease_owner == lease_owner,
                    McpTaskRow.lease_expires_at >= completed_at,
                    McpTaskRow.status.not_in(_TERMINAL_STATUS_VALUES),
                )
                .with_for_update()
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return False
            row.status = status
            row.result = result
            row.result_preview = result_preview
            row.result_truncated = result_truncated
            row.result_artifact = result_artifact
            row.error = error
            row.input_required = input_required
            row.next_poll_at = None
            row.next_cancel_at = None
            row.last_cancel_error = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.completed_at = completed_at
            row.updated_at = completed_at
            _record_event_if_changed(row, tracking_degraded=False, now=completed_at)
            await session.commit()
            return True

    async def release_cancel_claim(
        self,
        task_id: str,
        *,
        lease_owner: str,
        next_cancel_at: datetime,
        error: str,
    ) -> bool:
        stmt = (
            update(McpTaskRow)
            .where(McpTaskRow.id == task_id, McpTaskRow.lease_owner == lease_owner)
            .values(
                next_cancel_at=next_cancel_at,
                last_cancel_error=error,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=datetime.now(UTC),
            )
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def claim_notification_work(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
        tracking_degraded_after_errors: int,
    ) -> list[dict[str, Any]]:
        statuses = ("pending", "claimed", "retry", "dispatched")
        stmt = (
            select(McpTaskRow)
            .where(
                McpTaskRow.event_version > McpTaskRow.notified_version,
                McpTaskRow.notification_status.in_(statuses),
                or_(McpTaskRow.next_notification_at.is_(None), McpTaskRow.next_notification_at <= now),
                or_(McpTaskRow.notification_lease_expires_at.is_(None), McpTaskRow.notification_lease_expires_at < now),
            )
            .order_by(McpTaskRow.next_notification_at.asc(), McpTaskRow.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
            expires_at = now + timedelta(seconds=lease_seconds)
            for row in rows:
                row.notification_lease_owner = lease_owner
                row.notification_lease_expires_at = expires_at
                rebuild_snapshot = row.notification_status in ("pending", "claimed") or (row.notification_status == "retry" and row.dispatch_version != row.event_version)
                if rebuild_snapshot:
                    if row.dispatch_version != row.event_version:
                        row.dispatch_attempt = 0
                        row.notification_attempt_count = 0
                    row.dispatch_version = row.event_version
                    row.dispatch_event = _notification_event(
                        row,
                        tracking_degraded=int(row.consecutive_poll_error_count or 0) >= tracking_degraded_after_errors,
                    )
                    row.notification_run_id = None
                    row.notification_status = "claimed"
                row.updated_at = now
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def mark_notification_dispatched(
        self,
        task_id: str,
        *,
        lease_owner: str,
        dispatch_version: int,
        run_id: str,
        now: datetime,
    ) -> bool:
        stmt = (
            update(McpTaskRow)
            .where(
                McpTaskRow.id == task_id,
                McpTaskRow.notification_lease_owner == lease_owner,
                McpTaskRow.notification_lease_expires_at >= now,
                McpTaskRow.dispatch_version == dispatch_version,
                McpTaskRow.notification_status.in_(("claimed", "retry")),
            )
            .values(
                notification_status="dispatched",
                notification_run_id=run_id,
                notification_error=None,
                next_notification_at=now,
                notification_lease_owner=None,
                notification_lease_expires_at=None,
                updated_at=now,
            )
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def release_notification_claim(
        self,
        task_id: str,
        *,
        lease_owner: str,
        next_notification_at: datetime,
        error: str,
        replace_with_latest: bool,
        count_failure: bool = False,
    ) -> bool:
        values: dict[str, Any] = {
            "notification_status": "pending" if replace_with_latest else "retry",
            "notification_error": error,
            "next_notification_at": next_notification_at,
            "notification_lease_owner": None,
            "notification_lease_expires_at": None,
            "updated_at": datetime.now(UTC),
        }
        if replace_with_latest:
            values.update(
                dispatch_event=None,
                notification_run_id=None,
            )
        if count_failure:
            values["notification_attempt_count"] = McpTaskRow.notification_attempt_count + 1
        stmt = update(McpTaskRow).where(McpTaskRow.id == task_id, McpTaskRow.notification_lease_owner == lease_owner).values(**values)
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def finish_notification_run(
        self,
        task_id: str,
        *,
        lease_owner: str,
        dispatch_version: int,
        delivered: bool,
        next_notification_at: datetime | None,
        error: str | None,
        now: datetime,
    ) -> bool:
        async with self._sf() as session:
            stmt = (
                select(McpTaskRow)
                .where(
                    McpTaskRow.id == task_id,
                    McpTaskRow.notification_lease_owner == lease_owner,
                    McpTaskRow.notification_lease_expires_at >= now,
                    McpTaskRow.dispatch_version == dispatch_version,
                    McpTaskRow.notification_status == "dispatched",
                )
                .with_for_update()
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return False
            if delivered:
                row.notified_version = dispatch_version
                row.notification_status = "pending" if row.event_version > dispatch_version else "delivered"
                row.dispatch_version = None
                row.dispatch_attempt = 0
                row.dispatch_event = None
                row.notification_run_id = None
                row.notification_error = None
                row.notification_attempt_count = 0
                row.next_notification_at = now if row.event_version > dispatch_version else None
            else:
                row.notification_status = "retry"
                row.dispatch_attempt = int(row.dispatch_attempt or 0) + 1
                row.notification_attempt_count = int(row.notification_attempt_count or 0) + 1
                row.notification_run_id = None
                row.notification_error = error
                row.next_notification_at = next_notification_at
            row.notification_lease_owner = None
            row.notification_lease_expires_at = None
            row.updated_at = now
            await session.commit()
            return True

    async def release_notification_lease(
        self,
        task_id: str,
        *,
        lease_owner: str,
        next_notification_at: datetime,
        error: str,
        count_failure: bool = False,
    ) -> bool:
        """Release unexpected notification work without changing its phase."""
        values: dict[str, Any] = {
            "notification_error": error,
            "next_notification_at": next_notification_at,
            "notification_lease_owner": None,
            "notification_lease_expires_at": None,
            "updated_at": datetime.now(UTC),
        }
        if count_failure:
            values["notification_attempt_count"] = McpTaskRow.notification_attempt_count + 1
        stmt = (
            update(McpTaskRow)
            .where(
                McpTaskRow.id == task_id,
                McpTaskRow.notification_lease_owner == lease_owner,
            )
            .values(**values)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def dead_letter_notification(
        self,
        task_id: str,
        *,
        lease_owner: str,
        dispatch_version: int,
        error: str,
        count_failure: bool,
        now: datetime,
    ) -> bool:
        """Stop one failed snapshot, preserving any newer event for delivery."""
        base_filters = (
            McpTaskRow.id == task_id,
            McpTaskRow.notification_lease_owner == lease_owner,
            McpTaskRow.notification_lease_expires_at >= now,
            McpTaskRow.dispatch_version == dispatch_version,
            McpTaskRow.notification_status.in_(("claimed", "retry", "dispatched")),
        )
        dead_letter_values: dict[str, Any] = {
            "notification_status": "dead_letter",
            "notification_error": error,
            "next_notification_at": None,
            "notification_lease_owner": None,
            "notification_lease_expires_at": None,
            "dispatch_version": None,
            "dispatch_attempt": 0,
            "dispatch_event": None,
            "notification_run_id": None,
            "updated_at": now,
        }
        if count_failure:
            dead_letter_values["notification_attempt_count"] = McpTaskRow.notification_attempt_count + 1

        async with self._sf() as session:
            dead_lettered = await session.execute(update(McpTaskRow).where(*base_filters, McpTaskRow.event_version <= dispatch_version).values(**dead_letter_values))
            if dead_lettered.rowcount:
                await session.commit()
                return True

            replaced_by_latest = await session.execute(
                update(McpTaskRow)
                .where(*base_filters, McpTaskRow.event_version > dispatch_version)
                .values(
                    notification_status="pending",
                    notification_error=None,
                    notification_attempt_count=0,
                    next_notification_at=now,
                    notification_lease_owner=None,
                    notification_lease_expires_at=None,
                    dispatch_version=None,
                    dispatch_attempt=0,
                    dispatch_event=None,
                    notification_run_id=None,
                    updated_at=now,
                )
            )
            await session.commit()
            return bool(replaced_by_latest.rowcount)

    async def defer_dispatched_notification(
        self,
        task_id: str,
        *,
        lease_owner: str,
        dispatch_version: int,
        next_notification_at: datetime,
        now: datetime,
    ) -> bool:
        """Release a notification lease while its Agent run is still active."""
        stmt = (
            update(McpTaskRow)
            .where(
                McpTaskRow.id == task_id,
                McpTaskRow.notification_lease_owner == lease_owner,
                McpTaskRow.notification_lease_expires_at >= now,
                McpTaskRow.dispatch_version == dispatch_version,
                McpTaskRow.notification_status == "dispatched",
            )
            .values(
                next_notification_at=next_notification_at,
                notification_lease_owner=None,
                notification_lease_expires_at=None,
                updated_at=now,
            )
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

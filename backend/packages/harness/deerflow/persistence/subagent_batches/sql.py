from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow, SubagentBatchRow
from deerflow.utils.time import coerce_iso

BATCH_ACTIVE_STATUSES = ("queued", "running", "paused")
BATCH_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
ITEM_ACTIVE_STATUSES = ("queued", "leased", "running")
ITEM_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
_BATCH_PUBLIC_FIELDS = (
    "id",
    "thread_id",
    "title",
    "subagent_type",
    "status",
    "total_items",
    "max_live_items",
    "max_running_items",
    "max_attempts",
    "created_at",
    "updated_at",
    "completed_at",
)
_BATCH_TIMESTAMP_FIELDS = ("created_at", "updated_at", "completed_at")
_ITEM_PUBLIC_FIELDS = (
    "id",
    "batch_id",
    "item_key",
    "position",
    "status",
    "attempt",
    "model_name",
    "result_preview",
    "result_truncated",
    "error",
    "stop_reason",
    "token_usage",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
)
_ITEM_TIMESTAMP_FIELDS = ("started_at", "completed_at", "created_at", "updated_at")


class SubagentBatchRepository:
    """Durable batch/item state with lease-based multi-worker claiming."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _batch_dict(row: SubagentBatchRow) -> dict[str, Any]:
        """Return the stable owner-facing projection, never execution context."""
        data = {key: getattr(row, key) for key in _BATCH_PUBLIC_FIELDS}
        for key in _BATCH_TIMESTAMP_FIELDS:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    @staticmethod
    def _execution_batch_dict(row: SubagentBatchRow) -> dict[str, Any]:
        """Return worker-only fields required to reconstruct an execution."""
        return {
            "id": row.id,
            "user_id": row.user_id,
            "thread_id": row.thread_id,
            "run_id": row.run_id,
            "execution_spec": row.execution_spec,
        }

    @staticmethod
    def _item_dict(row: SubagentBatchItemRow, *, include_result: bool = False) -> dict[str, Any]:
        data = {key: getattr(row, key) for key in _ITEM_PUBLIC_FIELDS}
        if include_result:
            data["result"] = row.result
        for key in _ITEM_TIMESTAMP_FIELDS:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create_batch(
        self,
        *,
        batch_id: str,
        user_id: str,
        thread_id: str,
        run_id: str | None,
        tool_call_id: str | None,
        submission_key: str,
        title: str,
        subagent_type: str,
        items: list[dict[str, str]],
        max_live_items: int,
        max_running_items: int,
        max_attempts: int,
        execution_spec: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        batch = SubagentBatchRow(
            id=batch_id,
            user_id=user_id,
            thread_id=thread_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            submission_key=submission_key,
            title=title,
            subagent_type=subagent_type,
            status="queued",
            total_items=len(items),
            max_live_items=max_live_items,
            max_running_items=max_running_items,
            max_attempts=max_attempts,
            execution_spec=execution_spec,
            created_at=now,
            updated_at=now,
        )
        rows = [
            SubagentBatchItemRow(
                id=f"batch-item-{uuid.uuid4().hex}",
                batch_id=batch_id,
                item_key=item["key"],
                position=position,
                prompt=item["prompt"],
                status="pending",
                attempt=0,
                result_truncated=False,
                created_at=now,
                updated_at=now,
            )
            for position, item in enumerate(items)
        ]
        async with self._sf() as session:
            try:
                session.add(batch)
                # The models intentionally do not declare an ORM relationship;
                # flush the parent explicitly so SQLite's immediate FK check
                # never observes item inserts before their batch row. Keep the
                # flush inside the idempotency handler: a duplicate submission
                # key can fail here before commit.
                await session.flush()
                session.add_all(rows)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = (
                    await session.execute(
                        select(SubagentBatchRow).where(
                            SubagentBatchRow.user_id == user_id,
                            SubagentBatchRow.submission_key == submission_key,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return await self._with_counts(session, existing)
                raise
            return await self._with_counts(session, batch)

    async def _counts(self, session: AsyncSession, batch_id: str) -> Counter[str]:
        rows = await session.execute(select(SubagentBatchItemRow.status, func.count()).where(SubagentBatchItemRow.batch_id == batch_id).group_by(SubagentBatchItemRow.status))
        return Counter({status: int(count) for status, count in rows})

    async def _with_counts(self, session: AsyncSession, batch: SubagentBatchRow) -> dict[str, Any]:
        counts = await self._counts(session, batch.id)
        data = self._batch_dict(batch)
        data["counts"] = {status: counts.get(status, 0) for status in ("pending", "queued", "leased", "running", "succeeded", "failed", "cancelled")}
        return data

    async def get_batch(self, batch_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            batch = await session.get(SubagentBatchRow, batch_id)
            if batch is None or batch.user_id != user_id:
                return None
            return await self._with_counts(session, batch)

    async def list_by_thread(self, thread_id: str, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = list(
                (
                    await session.execute(
                        select(SubagentBatchRow)
                        .where(
                            SubagentBatchRow.thread_id == thread_id,
                            SubagentBatchRow.user_id == user_id,
                        )
                        .order_by(SubagentBatchRow.created_at.desc(), SubagentBatchRow.id.desc())
                        .limit(limit)
                    )
                ).scalars()
            )
            return [await self._with_counts(session, row) for row in rows]

    async def list_items(
        self,
        batch_id: str,
        *,
        user_id: str,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
        include_prompt: bool = False,
        include_result: bool = False,
    ) -> list[dict[str, Any]] | None:
        async with self._sf() as session:
            batch = await session.get(SubagentBatchRow, batch_id)
            if batch is None or batch.user_id != user_id:
                return None
            stmt = select(SubagentBatchItemRow).where(SubagentBatchItemRow.batch_id == batch_id)
            if status is not None:
                stmt = stmt.where(SubagentBatchItemRow.status == status)
            stmt = stmt.order_by(SubagentBatchItemRow.position).offset(offset).limit(limit)
            rows = list((await session.execute(stmt)).scalars())
            values = []
            for row in rows:
                value = self._item_dict(row, include_result=include_result)
                if include_prompt:
                    value["prompt"] = row.prompt
                values.append(value)
            return values

    async def claim_items(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Promote pending work and atomically claim runnable items."""
        if limit <= 0:
            return []
        claimed: list[dict[str, Any]] = []
        async with self._sf() as session:
            batches = list((await session.execute(select(SubagentBatchRow).where(SubagentBatchRow.status.in_(("queued", "running"))).order_by(SubagentBatchRow.created_at, SubagentBatchRow.id).with_for_update(skip_locked=True))).scalars())
            for batch in batches:
                if len(claimed) >= limit:
                    break

                expired = list(
                    (
                        await session.execute(
                            select(SubagentBatchItemRow)
                            .where(
                                SubagentBatchItemRow.batch_id == batch.id,
                                SubagentBatchItemRow.status.in_(("leased", "running")),
                                SubagentBatchItemRow.lease_expires_at < now,
                            )
                            .with_for_update(skip_locked=True)
                        )
                    ).scalars()
                )
                for item in expired:
                    item.lease_owner = None
                    item.lease_expires_at = None
                    item.updated_at = now
                    if item.cancel_requested_at is not None:
                        item.status = "cancelled"
                        item.completed_at = now
                    elif item.attempt >= batch.max_attempts:
                        item.status = "failed"
                        item.error = item.error or "Execution lease expired after the maximum retry count"
                        item.completed_at = now
                    else:
                        item.status = "queued"
                        item.error = "Previous worker lease expired; retrying"

                counts = await self._counts(session, batch.id)
                live = counts["queued"] + counts["leased"] + counts["running"]
                promote_count = max(0, batch.max_live_items - live)
                if promote_count:
                    pending = list(
                        (
                            await session.execute(
                                select(SubagentBatchItemRow)
                                .where(
                                    SubagentBatchItemRow.batch_id == batch.id,
                                    SubagentBatchItemRow.status == "pending",
                                )
                                .order_by(SubagentBatchItemRow.position)
                                .limit(promote_count)
                                .with_for_update(skip_locked=True)
                            )
                        ).scalars()
                    )
                    for item in pending:
                        item.status = "queued"
                        item.updated_at = now

                counts = await self._counts(session, batch.id)
                batch_available = max(0, batch.max_running_items - counts["leased"] - counts["running"])
                take = min(limit - len(claimed), batch_available)
                if take <= 0:
                    continue
                runnable = list(
                    (
                        await session.execute(
                            select(SubagentBatchItemRow)
                            .where(
                                SubagentBatchItemRow.batch_id == batch.id,
                                SubagentBatchItemRow.status == "queued",
                                SubagentBatchItemRow.cancel_requested_at.is_(None),
                            )
                            .order_by(SubagentBatchItemRow.position)
                            .limit(take)
                            .with_for_update(skip_locked=True)
                        )
                    ).scalars()
                )
                expires_at = now + timedelta(seconds=lease_seconds)
                for item in runnable:
                    item.status = "leased"
                    item.attempt += 1
                    item.lease_owner = lease_owner
                    item.lease_expires_at = expires_at
                    item.started_at = now
                    item.updated_at = now
                    item.error = None
                    value = self._item_dict(item)
                    value["prompt"] = item.prompt
                    value["batch"] = self._execution_batch_dict(batch)
                    claimed.append(value)
                if runnable:
                    batch.status = "running"
                    batch.updated_at = now
            await session.commit()
        return claimed

    async def renew_item_lease(
        self,
        item_id: str,
        *,
        lease_owner: str,
        lease_seconds: int,
        now: datetime,
    ) -> dict[str, bool]:
        async with self._sf() as session:
            item = (
                await session.execute(
                    select(SubagentBatchItemRow)
                    .where(
                        SubagentBatchItemRow.id == item_id,
                        SubagentBatchItemRow.status.in_(("leased", "running")),
                        SubagentBatchItemRow.lease_owner == lease_owner,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if item is None:
                return {"valid": False, "cancel_requested": True}
            batch = await session.get(SubagentBatchRow, item.batch_id)
            cancel_requested = item.cancel_requested_at is not None or batch is None or batch.status == "cancelled"
            if not cancel_requested:
                item.lease_expires_at = now + timedelta(seconds=lease_seconds)
                item.updated_at = now
                await session.commit()
            return {"valid": not cancel_requested, "cancel_requested": cancel_requested}

    async def mark_item_running(self, item_id: str, *, lease_owner: str, now: datetime) -> bool:
        async with self._sf() as session:
            item = (
                await session.execute(
                    select(SubagentBatchItemRow)
                    .where(
                        SubagentBatchItemRow.id == item_id,
                        SubagentBatchItemRow.status == "leased",
                        SubagentBatchItemRow.lease_owner == lease_owner,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if item is None or item.cancel_requested_at is not None:
                return False
            item.status = "running"
            item.started_at = now
            item.updated_at = now
            await session.commit()
            return True

    async def finalize_item(
        self,
        item_id: str,
        *,
        lease_owner: str,
        succeeded: bool,
        result: str | None,
        result_preview: str | None,
        result_truncated: bool,
        error: str | None,
        stop_reason: str | None,
        token_usage: dict[str, Any] | None,
        model_name: str | None,
        completed_at: datetime,
    ) -> bool:
        async with self._sf() as session:
            item = (
                await session.execute(
                    select(SubagentBatchItemRow)
                    .where(
                        SubagentBatchItemRow.id == item_id,
                        SubagentBatchItemRow.status.in_(("leased", "running")),
                        SubagentBatchItemRow.lease_owner == lease_owner,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if item is None:
                return False
            batch = await session.get(SubagentBatchRow, item.batch_id, with_for_update=True)
            cancelled = item.cancel_requested_at is not None or batch is None or batch.status == "cancelled"
            item.lease_owner = None
            item.lease_expires_at = None
            item.model_name = model_name
            item.stop_reason = stop_reason
            item.token_usage = token_usage
            item.updated_at = completed_at
            if cancelled:
                item.status = "cancelled"
                item.error = "Cancelled by user"
                item.completed_at = completed_at
            elif succeeded:
                item.status = "succeeded"
                item.result = result
                item.result_preview = result_preview
                item.result_truncated = result_truncated
                item.error = None
                item.completed_at = completed_at
            elif item.attempt < batch.max_attempts:
                item.status = "queued"
                item.error = error
                item.started_at = None
            else:
                item.status = "failed"
                item.error = error
                item.completed_at = completed_at
            if batch is not None:
                await self._refresh_batch_status(session, batch, now=completed_at)
            await session.commit()
            return True

    async def requeue_item_after_admission_failure(
        self,
        item_id: str,
        *,
        lease_owner: str,
        error: str | None,
        now: datetime,
    ) -> bool:
        """Undo a claim rejected before execution admission.

        Claiming increments ``attempt`` so crash recovery can bound real
        executions. A process-wide capacity rejection happens before an
        execution starts, so it must release the lease and restore that
        attempt instead of consuming the batch's retry budget.
        """
        async with self._sf() as session:
            item = (
                await session.execute(
                    select(SubagentBatchItemRow)
                    .where(
                        SubagentBatchItemRow.id == item_id,
                        SubagentBatchItemRow.status.in_(("leased", "running")),
                        SubagentBatchItemRow.lease_owner == lease_owner,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if item is None:
                return False
            batch = await session.get(SubagentBatchRow, item.batch_id, with_for_update=True)
            cancelled = item.cancel_requested_at is not None or batch is None or batch.status == "cancelled"
            item.lease_owner = None
            item.lease_expires_at = None
            item.updated_at = now
            if cancelled:
                item.status = "cancelled"
                item.error = "Cancelled by user"
                item.completed_at = now
            else:
                item.status = "queued"
                item.attempt = max(0, item.attempt - 1)
                item.started_at = None
                item.error = error
            if batch is not None:
                await self._refresh_batch_status(session, batch, now=now)
            await session.commit()
            return True

    async def _refresh_batch_status(self, session: AsyncSession, batch: SubagentBatchRow, *, now: datetime) -> None:
        counts = await self._counts(session, batch.id)
        terminal = sum(counts[state] for state in ITEM_TERMINAL_STATUSES)
        if terminal >= batch.total_items:
            if batch.status != "cancelled":
                batch.status = "failed" if counts["failed"] > 0 and counts["succeeded"] == 0 else "completed"
            batch.completed_at = now
        elif batch.status not in ("paused", "cancelled"):
            batch.status = "running"
        batch.updated_at = now

    async def pause_batch(self, batch_id: str, *, user_id: str) -> dict[str, Any] | None:
        return await self._set_control(batch_id, user_id=user_id, action="pause")

    async def resume_batch(self, batch_id: str, *, user_id: str) -> dict[str, Any] | None:
        return await self._set_control(batch_id, user_id=user_id, action="resume")

    async def cancel_batch(self, batch_id: str, *, user_id: str) -> dict[str, Any] | None:
        return await self._set_control(batch_id, user_id=user_id, action="cancel")

    async def _set_control(self, batch_id: str, *, user_id: str, action: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            batch = await session.get(SubagentBatchRow, batch_id, with_for_update=True)
            if batch is None or batch.user_id != user_id:
                return None
            if action == "pause" and batch.status in ("queued", "running"):
                batch.status = "paused"
            elif action == "resume" and batch.status == "paused":
                batch.status = "queued"
            elif action == "cancel" and batch.status not in BATCH_TERMINAL_STATUSES:
                batch.status = "cancelled"
                batch.completed_at = now
                items = list(
                    (
                        await session.execute(
                            select(SubagentBatchItemRow)
                            .where(
                                SubagentBatchItemRow.batch_id == batch_id,
                                SubagentBatchItemRow.status.not_in(ITEM_TERMINAL_STATUSES),
                            )
                            .with_for_update()
                        )
                    ).scalars()
                )
                for item in items:
                    item.cancel_requested_at = now
                    item.updated_at = now
                    item.status = "cancelled"
                    item.error = "Cancelled by user"
                    item.lease_owner = None
                    item.lease_expires_at = None
                    item.completed_at = now
            batch.updated_at = now
            await session.commit()
            return await self._with_counts(session, batch)

    async def retry_item(self, batch_id: str, item_id: str, *, user_id: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            batch = await session.get(SubagentBatchRow, batch_id, with_for_update=True)
            if batch is None or batch.user_id != user_id:
                return None
            item = await session.get(SubagentBatchItemRow, item_id, with_for_update=True)
            if item is None or item.batch_id != batch_id or item.status != "failed":
                return None
            item.status = "pending"
            item.attempt = 0
            item.error = None
            item.result = None
            item.result_preview = None
            item.result_truncated = False
            item.completed_at = None
            item.cancel_requested_at = None
            item.updated_at = now
            batch.status = "queued"
            batch.completed_at = None
            batch.updated_at = now
            await session.commit()
            return self._item_dict(item)

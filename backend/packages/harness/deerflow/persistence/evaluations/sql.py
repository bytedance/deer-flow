"""SQLAlchemy-backed evaluation persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.evaluations.model import (
    EVAL_ATTEMPT_STATUS_FAILED,
    EVAL_ATTEMPT_STATUS_QUEUED,
    EVAL_ATTEMPT_STATUS_RUNNING,
    EVAL_ITEM_STATUS_QUEUED,
    EVAL_ITEM_STATUS_RUNNING,
    EVAL_RUN_STATUS_QUEUED,
    EvalItemAttemptRow,
    EvalRunItemRow,
    EvalRunRow,
)
from deerflow.utils.time import coerce_iso

_INCOMPLETE_ATTEMPT_STATUSES = (EVAL_ATTEMPT_STATUS_QUEUED, EVAL_ATTEMPT_STATUS_RUNNING)
_STALE_RECOVERY_ERROR = "eval platform stale recovery: lease expired before attempt completed"


class EvaluationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: EvalRunRow | EvalRunItemRow | EvalItemAttemptRow) -> dict[str, Any]:
        data = row.to_dict()
        for key, value in list(data.items()):
            if isinstance(value, datetime):
                data[key] = coerce_iso(value)
        return data

    async def create_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        suite_name: str,
        suite_digest: str,
        suite_snapshot: dict[str, Any],
        environment_fingerprint: dict[str, Any] | None = None,
        suite_version: str | None = None,
        idempotency_key: str | None = None,
        config: dict[str, Any] | None = None,
        variants: dict[str, Any] | None = None,
        total_items: int = 0,
        status: str = EVAL_RUN_STATUS_QUEUED,
    ) -> dict[str, Any]:
        async with self._sf() as session:
            if idempotency_key is not None:
                existing = await session.execute(
                    select(EvalRunRow).where(
                        EvalRunRow.owner_id == owner_id,
                        EvalRunRow.idempotency_key == idempotency_key,
                    )
                )
                row = existing.scalar_one_or_none()
                if row is not None:
                    return self._row_to_dict(row)

            row = EvalRunRow(
                id=run_id,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                suite_name=suite_name,
                suite_version=suite_version,
                suite_digest=suite_digest,
                suite_snapshot=suite_snapshot,
                environment_fingerprint_json=environment_fingerprint or {},
                config_json=config or {},
                variants_json=variants or {},
                status=status,
                total_items=total_items,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_run(self, run_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(EvalRunRow, run_id)
            if row is None or (owner_id is not None and row.owner_id != owner_id):
                return None
            return self._row_to_dict(row)

    async def create_item(
        self,
        *,
        item_id: str,
        eval_run_id: str,
        suite_item_id: str,
        execution_key: str,
        variant_id: str = "default",
        sample_index: int = 0,
        max_attempts: int = 1,
        checks: list[dict[str, Any]] | None = None,
        status: str = EVAL_ITEM_STATUS_QUEUED,
    ) -> dict[str, Any]:
        row = EvalRunItemRow(
            id=item_id,
            eval_run_id=eval_run_id,
            suite_item_id=suite_item_id,
            execution_key=execution_key,
            variant_id=variant_id,
            sample_index=sample_index,
            max_attempts=max_attempts,
            checks_json=checks or [],
            status=status,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_items(self, eval_run_id: str) -> list[dict[str, Any]]:
        stmt = select(EvalRunItemRow).where(EvalRunItemRow.eval_run_id == eval_run_id).order_by(EvalRunItemRow.suite_item_id.asc(), EvalRunItemRow.variant_id.asc(), EvalRunItemRow.sample_index.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def create_attempt(
        self,
        *,
        attempt_id: str,
        eval_run_id: str,
        eval_run_item_id: str,
        attempt_index: int | None = None,
        status: str = EVAL_ATTEMPT_STATUS_QUEUED,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: IntegrityError | None = None
        for _ in range(3):
            async with self._sf() as session:
                try:
                    item_row = await session.get(EvalRunItemRow, eval_run_item_id, with_for_update=True)
                    resolved_attempt_index = attempt_index
                    if resolved_attempt_index is None:
                        resolved_attempt_index = await self._next_attempt_index(session, eval_run_item_id, item_row=item_row)
                    if item_row is not None:
                        now = datetime.now(UTC)
                        item_row.status = EVAL_ITEM_STATUS_RUNNING
                        item_row.attempt_count = max(int(item_row.attempt_count or 0), resolved_attempt_index + 1)
                        item_row.started_at = item_row.started_at or now
                        item_row.updated_at = now

                    row = EvalItemAttemptRow(
                        id=attempt_id,
                        eval_run_id=eval_run_id,
                        eval_run_item_id=eval_run_item_id,
                        attempt_index=resolved_attempt_index,
                        status=status,
                        metadata_json=metadata or {},
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    return self._row_to_dict(row)
                except IntegrityError as exc:
                    await session.rollback()
                    if attempt_index is not None:
                        raise
                    last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("evaluation repository failed to create attempt")

    async def list_attempts(self, eval_run_item_id: str) -> list[dict[str, Any]]:
        stmt = select(EvalItemAttemptRow).where(EvalItemAttemptRow.eval_run_item_id == eval_run_item_id).order_by(EvalItemAttemptRow.attempt_index.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def fail_incomplete_attempts_for_item(
        self,
        eval_run_item_id: str,
        *,
        failure_kind: str,
        error: str,
        now: datetime,
    ) -> int:
        async with self._sf() as session:
            item_row = await session.get(EvalRunItemRow, eval_run_item_id, with_for_update=True)
            result = await session.execute(
                select(EvalItemAttemptRow)
                .where(
                    EvalItemAttemptRow.eval_run_item_id == eval_run_item_id,
                    EvalItemAttemptRow.status.in_(_INCOMPLETE_ATTEMPT_STATUSES),
                )
                .order_by(EvalItemAttemptRow.attempt_index.asc())
                .with_for_update()
            )
            attempts = list(result.scalars())
            self._fail_attempt_rows(attempts, failure_kind=failure_kind, error=error, now=now)
            if item_row is not None and attempts:
                max_attempt_index = max(int(attempt.attempt_index) for attempt in attempts)
                item_row.status = EVAL_ITEM_STATUS_QUEUED
                item_row.attempt_count = max(int(item_row.attempt_count or 0), max_attempt_index + 1)
                item_row.updated_at = now
            await session.commit()
            return len(attempts)

    async def update_item_result(
        self,
        item_id: str,
        *,
        status: str,
        selected_attempt_id: str | None = None,
        selected_attempt_index: int | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        workspace_path: str | None = None,
        check_results: dict[str, Any] | list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
        comparison: dict[str, Any] | None = None,
        run_event_summary: dict[str, Any] | None = None,
        failure_kind: str | None = None,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(EvalRunItemRow, item_id)
            if row is None:
                return False
            row.status = status
            row.selected_attempt_id = selected_attempt_id
            row.selected_attempt_index = selected_attempt_index
            row.thread_id = thread_id
            row.run_id = run_id
            row.workspace_path = workspace_path
            if check_results is not None:
                row.check_results_json = check_results
            if metrics is not None:
                row.metrics_json = metrics
            if comparison is not None:
                row.comparison_json = comparison
            if run_event_summary is not None:
                row.run_event_summary_json = run_event_summary
            row.failure_kind = failure_kind
            row.error = error
            row.finished_at = finished_at
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def update_attempt_result(
        self,
        attempt_id: str,
        *,
        status: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        workspace_path: str | None = None,
        check_results: dict[str, Any] | list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
        comparison: dict[str, Any] | None = None,
        run_event_summary: dict[str, Any] | None = None,
        failure_kind: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(EvalItemAttemptRow, attempt_id)
            if row is None:
                return False
            row.status = status
            row.thread_id = thread_id
            row.run_id = run_id
            row.workspace_path = workspace_path
            if check_results is not None:
                row.check_results_json = check_results
            if metrics is not None:
                row.metrics_json = metrics
            if comparison is not None:
                row.comparison_json = comparison
            if run_event_summary is not None:
                row.run_event_summary_json = run_event_summary
            row.failure_kind = failure_kind
            row.error = error
            if started_at is not None:
                row.started_at = started_at
            row.finished_at = finished_at
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def claim_queued_runs(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(EvalRunRow)
            .where(
                or_(
                    EvalRunRow.status == EVAL_RUN_STATUS_QUEUED,
                    and_(
                        EvalRunRow.status == "running",
                        EvalRunRow.lease_expires_at.is_not(None),
                        EvalRunRow.lease_expires_at < now,
                    ),
                )
            )
            .order_by(EvalRunRow.created_at.asc(), EvalRunRow.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                if row.status == "running":
                    await self._fail_incomplete_attempts_for_run(
                        session,
                        eval_run_id=row.id,
                        failure_kind="platform_defect",
                        error=_STALE_RECOVERY_ERROR,
                        now=now,
                    )
                row.status = "running"
                row.lease_owner = lease_owner
                row.lease_expires_at = lease_expires_at
                row.heartbeat_at = now
                row.started_at = row.started_at or now
                row.updated_at = datetime.now(UTC)
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def renew_lease(
        self,
        run_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(EvalRunRow, run_id)
            if row is None or row.status != "running" or row.lease_owner != lease_owner:
                return False
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.heartbeat_at = now
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def requeue_stale_runs(self, *, now: datetime) -> int:
        stmt = select(EvalRunRow).where(
            EvalRunRow.status == "running",
            EvalRunRow.lease_expires_at.is_not(None),
            EvalRunRow.lease_expires_at < now,
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                await self._fail_incomplete_attempts_for_run(
                    session,
                    eval_run_id=row.id,
                    failure_kind="platform_defect",
                    error=_STALE_RECOVERY_ERROR,
                    now=now,
                )
                row.status = EVAL_RUN_STATUS_QUEUED
                row.lease_owner = None
                row.lease_expires_at = None
                row.heartbeat_at = None
                row.updated_at = datetime.now(UTC)
            await session.commit()
            return len(rows)

    async def update_report(
        self,
        run_id: str,
        *,
        summary: dict[str, Any] | None = None,
        effect_summary: dict[str, Any] | None = None,
        comparison: dict[str, Any] | None = None,
        report_json: dict[str, Any] | None = None,
        report_markdown: str | None = None,
        status: str | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(EvalRunRow, run_id)
            if row is None:
                return False
            if summary is not None:
                row.summary_json = summary
            if effect_summary is not None:
                row.effect_summary_json = effect_summary
            if comparison is not None:
                row.comparison_json = comparison
            if report_json is not None:
                row.report_json = report_json
            if report_markdown is not None:
                row.report_markdown = report_markdown
            if status is not None:
                row.status = status
            if finished_at is not None:
                row.finished_at = finished_at
            if error is not None:
                row.error = error
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    @staticmethod
    async def _next_attempt_index(
        session: AsyncSession,
        eval_run_item_id: str,
        *,
        item_row: EvalRunItemRow | None,
    ) -> int:
        result = await session.execute(select(func.max(EvalItemAttemptRow.attempt_index)).where(EvalItemAttemptRow.eval_run_item_id == eval_run_item_id))
        max_attempt_index = result.scalar_one_or_none()
        next_from_attempts = int(max_attempt_index) + 1 if max_attempt_index is not None else 0
        next_from_item = int(item_row.attempt_count or 0) if item_row is not None else 0
        return max(next_from_attempts, next_from_item)

    async def _fail_incomplete_attempts_for_run(
        self,
        session: AsyncSession,
        *,
        eval_run_id: str,
        failure_kind: str,
        error: str,
        now: datetime,
    ) -> int:
        result = await session.execute(
            select(EvalItemAttemptRow)
            .where(
                EvalItemAttemptRow.eval_run_id == eval_run_id,
                EvalItemAttemptRow.status.in_(_INCOMPLETE_ATTEMPT_STATUSES),
            )
            .order_by(EvalItemAttemptRow.eval_run_item_id.asc(), EvalItemAttemptRow.attempt_index.asc())
            .with_for_update()
        )
        attempts = list(result.scalars())
        self._fail_attempt_rows(attempts, failure_kind=failure_kind, error=error, now=now)
        max_attempt_index_by_item: dict[str, int] = {}
        for attempt in attempts:
            current = max_attempt_index_by_item.get(attempt.eval_run_item_id, -1)
            max_attempt_index_by_item[attempt.eval_run_item_id] = max(current, int(attempt.attempt_index))
        if max_attempt_index_by_item:
            item_result = await session.execute(select(EvalRunItemRow).where(EvalRunItemRow.id.in_(list(max_attempt_index_by_item))).with_for_update())
            for item in item_result.scalars():
                item.status = EVAL_ITEM_STATUS_QUEUED
                item.attempt_count = max(int(item.attempt_count or 0), max_attempt_index_by_item[item.id] + 1)
                item.updated_at = now
        return len(attempts)

    @staticmethod
    def _fail_attempt_rows(
        attempts: list[EvalItemAttemptRow],
        *,
        failure_kind: str,
        error: str,
        now: datetime,
    ) -> None:
        for attempt in attempts:
            attempt.status = EVAL_ATTEMPT_STATUS_FAILED
            attempt.failure_kind = failure_kind
            attempt.error = error
            if not attempt.run_event_summary_json:
                attempt.run_event_summary_json = {"event_count": 0, "event_types": {}, "recovery": "stale_attempt_closed"}
            attempt.finished_at = now
            attempt.updated_at = now

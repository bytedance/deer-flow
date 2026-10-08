from __future__ import annotations

import operator
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.finalization import FinalizationObserver, end_condition_reached, finalize_occurrence, finish_task_at_end_condition, is_host_pause_marker
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.projection import account_launch, can_project
from deerflow.persistence.scheduled_tasks.model import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    ScheduledTaskRow,
    ScheduledTaskRunStatus,
)
from deerflow.scheduler.host_notes import RUN_ERROR_END_REACHED
from deerflow.scheduler.schedules import next_run_at as compute_next_run_at
from deerflow.utils.time import coerce_iso

EXECUTING_RUN_STATUSES: tuple[str, ...] = ("launching", "running")
_SCHEDULER_BUDGET_LOCK_KEY = 4694001


def _lease_is_alive(lease_expires_at: datetime | None, *, now: datetime, grace_seconds: int) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at >= now - timedelta(seconds=grace_seconds)


_SUMMARY_MAX_CHARS = 160
_MARKDOWN_PREFIX = re.compile(r"^(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)+")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_MARKERS = re.compile(r"(\*\*|__|~~|`+)")
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_TASK_CHECKBOX = re.compile(r"^\[[ xX]\]\s*")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]")


def _summary_line(line: str) -> str:
    """One reply line as plain text: no list/heading/quote prefix, checkbox, links or emphasis markers."""
    text = _MARKDOWN_PREFIX.sub("", line.strip())
    text = _TASK_CHECKBOX.sub("", text)
    text = _MARKDOWN_MARKERS.sub("", _MARKDOWN_LINK.sub(r"\1", text)).strip()
    if text.startswith(("*", "_")) and text.endswith(("*", "_")) and len(text) > 2:
        text = text[1:-1].strip()
    return text


def _lead_in_items(lines: list[str]) -> list[str]:
    """The list that follows a lead-in line ("Two items are still open:"), as plain text.

    Blank lines before and between items are skipped; the first other line ends the list.
    """
    items: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if not _LIST_ITEM.match(line.strip()):
            break
        item = _summary_line(line)
        if item:
            items.append(item)
    return items


def run_summary(last_ai_message: str | None) -> str | None:
    """One readable line from the agent's final reply, without markdown markers.

    It is the reply's first non-empty line. When that line only introduces a
    list (it ends with ":" or "："), the list items follow it, joined with
    "；" for CJK text and "; " otherwise, so the line still says something.
    The result is capped at ``_SUMMARY_MAX_CHARS`` with an ellipsis.
    """
    if not isinstance(last_ai_message, str):
        return None
    lines = last_ai_message.splitlines()
    for index, line in enumerate(lines):
        text = _summary_line(line)
        if not (text and set(text) - set("-*_=|: ")):
            continue
        if text.endswith((":", "：")):
            items = _lead_in_items(lines[index + 1 :])
            if items:
                if _CJK.search(text):
                    # "：" needs no space after it; an ASCII ":" does.
                    text = f"{text}{' ' if text.endswith(':') else ''}{'；'.join(items)}"
                else:
                    text = f"{text} {'; '.join(items)}"
        return text if len(text) <= _SUMMARY_MAX_CHARS else text[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return None


def run_number_expression(outer: Any):
    """SQL expression numbering automatic runs exactly like the safety cap counts them.

    A launch-accounted scheduled row is number N when N accounted scheduled
    rows of its task have ``occurrence_seq <=`` its own. A launching/running
    row not yet accounted gets the number it will have (accounted-before + 1),
    so the launch-time number and the history number agree. Manual,
    unsequenced and never-launched rows have no number.
    """
    inner = aliased(ScheduledTaskRunRow)

    def accounted(compare):
        condition = and_(inner.task_id == outer.task_id, inner.trigger == "scheduled", inner.launch_accounted.is_(True), compare(inner.occurrence_seq, outer.occurrence_seq))
        return select(func.count()).select_from(inner).where(condition).correlate(outer).scalar_subquery()

    sequenced = and_(outer.trigger == "scheduled", outer.occurrence_seq.is_not(None))
    return case(
        (and_(sequenced, outer.launch_accounted.is_(True)), accounted(operator.le)),
        (and_(sequenced, outer.status.in_(("launching", "running"))), accounted(operator.lt) + 1),
        else_=None,
    )


class ActiveScheduledRunConflict(Exception):
    """A concurrent dispatch already holds the task's active-occurrence slot.

    Coordinated admission serializes on the parent task before inserting the
    queue row. The partial unique index remains the database backstop for
    direct repository callers and legacy interleavings. Both paths surface the
    same domain exception without coupling the service to SQLAlchemy errors.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"scheduled task {task_id!r} already has an active run")


class ScheduledTaskAdmissionRejected(Exception):
    """The parent task changed or disappeared before queue admission."""

    def __init__(self, task_id: str, *, reason: str) -> None:
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"scheduled task {task_id!r} admission rejected: {reason}")


class ScheduledTaskRunRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_repository: RunRepository | None = None,
    ) -> None:
        self._sf = session_factory
        self._run_repository = run_repository or RunRepository(session_factory)
        self._finalization_observer: FinalizationObserver | None = None

    def set_finalization_observer(self, callback: FinalizationObserver | None) -> None:
        self._finalization_observer = callback

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRunRow) -> dict[str, Any]:
        data = row.to_dict(exclude={"occurrence_seq", "launch_accounted"})
        for key in (
            "scheduled_for",
            "lease_expires_at",
            "started_at",
            "finished_at",
            "created_at",
        ):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    @staticmethod
    async def _lock_task(session: AsyncSession, task_id: str) -> ScheduledTaskRow | None:
        # SQLite ignores SELECT ... FOR UPDATE. Touch the parent first so its
        # single-writer lock provides the same serialization point used by
        # Postgres row locking for admission, mutation, pause, and delete.
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).values(updated_at=ScheduledTaskRow.updated_at))
        return await session.get(ScheduledTaskRow, task_id, with_for_update=True)

    @staticmethod
    def _associate_scheduled_run(
        row: ScheduledTaskRunRow,
        candidate: RunRow,
    ) -> None:
        """Fill launch bookkeeping that the durable run already proves."""
        row.run_id = candidate.run_id
        if row.started_at is None:
            row.started_at = candidate.created_at

    @staticmethod
    def _associate_task_with_run(
        task: ScheduledTaskRow | None,
        row: ScheduledTaskRunRow,
        candidate: RunRow,
    ) -> None:
        """Repair the parent update if launch committed before bookkeeping."""
        if task is None:
            return
        account_launch(task, row, candidate.run_id)
        if task.last_run_id == candidate.run_id or not can_project(task, row):
            return
        launched_at = candidate.created_at
        if launched_at.tzinfo is None:
            launched_at = launched_at.replace(tzinfo=UTC)
        task.last_run_at = launched_at
        task.last_run_id = candidate.run_id
        task.last_thread_id = row.thread_id
        task.next_run_at = compute_next_run_at(
            task.schedule_type,
            task.schedule_spec,
            task.timezone,
            now=launched_at,
        )
        task.lease_owner = None
        task.lease_expires_at = None
        task.updated_at = datetime.now(UTC)
        if task.schedule_type == "once":
            if candidate.status == "success":
                task.status = "completed"
                task.last_error = None
            elif candidate.status in {"error", "timeout"}:
                task.status = "failed"
                task.last_error = candidate.error
            elif candidate.status == "interrupted":
                task.status = "cancelled"
                task.last_error = candidate.error
            else:
                task.status = "running"
                task.last_error = None
        elif not (row.trigger == "manual" and task.status == "paused"):
            task.status = "enabled"
            task.last_error = candidate.error if candidate.status in {"error", "timeout", "interrupted"} else None

    async def create(
        self,
        *,
        run_record_id: str,
        task_id: str,
        thread_id: str,
        scheduled_for: datetime,
        trigger: str,
        status: str,
        coordinate_with_task: bool = False,
        expected_task_user_id: str | None = None,
        expected_task_status: str | None = None,
        expected_task_updated_at: datetime | str | None = None,
        expected_task_lease_owner: str | None = None,
        release_task_lease_status: str | None = None,
    ) -> dict[str, Any]:
        row = ScheduledTaskRunRow(
            id=run_record_id,
            task_id=task_id,
            thread_id=thread_id,
            scheduled_for=scheduled_for,
            trigger=trigger,
            status=status,
            launch_accounted=False,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            # Every occurrence with a parent participates in the same DB
            # ordering, including terminal records and uncoordinated callers.
            task = await self._lock_task(session, task_id)
            if coordinate_with_task:
                if task is None or (expected_task_user_id is not None and task.user_id != expected_task_user_id):
                    await session.rollback()
                    raise ScheduledTaskAdmissionRejected(task_id, reason="not_found")
                if expected_task_lease_owner is not None:
                    if task.lease_owner != expected_task_lease_owner:
                        await session.rollback()
                        raise ScheduledTaskAdmissionRejected(task_id, reason="stale")
                else:
                    if expected_task_status is not None and task.status != expected_task_status:
                        await session.rollback()
                        raise ScheduledTaskAdmissionRejected(task_id, reason="stale")
                    if expected_task_updated_at is not None and coerce_iso(task.updated_at) != coerce_iso(expected_task_updated_at):
                        await session.rollback()
                        raise ScheduledTaskAdmissionRejected(task_id, reason="stale")
                if trigger == "scheduled" and await end_condition_reached(session, task, now=scheduled_for):
                    # The row being admitted is never persisted, so this is an
                    # idle finish (no occurrence anchor).
                    await finish_task_at_end_condition(session, task, occurrence=None, now=scheduled_for, observer=self._finalization_observer)
                    await session.commit()
                    raise ScheduledTaskAdmissionRejected(task_id, reason="ended")
                active_status = await session.scalar(
                    select(ScheduledTaskRunRow.status)
                    .where(
                        ScheduledTaskRunRow.task_id == task_id,
                        ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .limit(1)
                )
                if active_status is not None:
                    await session.rollback()
                    raise ActiveScheduledRunConflict(task_id)
            if task is not None:
                row.goal_objective = task.goal_objective
                row.occurrence_seq = await session.scalar(
                    update(ScheduledTaskRow)
                    .where(ScheduledTaskRow.id == task_id)
                    .values(
                        last_occurrence_seq=ScheduledTaskRow.last_occurrence_seq + 1,
                        # Sequence allocation is not a user-visible task edit.
                        updated_at=ScheduledTaskRow.updated_at,
                    )
                    .returning(ScheduledTaskRow.last_occurrence_seq)
                )
            session.add(row)
            if coordinate_with_task and task is not None and release_task_lease_status is not None:
                task.status = release_task_lease_status
                task.lease_owner = None
                task.lease_expires_at = None
                task.updated_at = datetime.now(UTC)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # A primary-key/sequence conflict is not necessarily an active
                # slot conflict. Preserve the database error unless an active
                # occurrence actually exists after rollback.
                if status in ACTIVE_RUN_STATUSES and await session.scalar(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES)).limit(1)):
                    raise ActiveScheduledRunConflict(task_id) from None
                raise
            await session.refresh(row)
            return self._row_to_dict(row)

    async def request_stop(self, task_run_id: str, *, task_id: str, run_id: str, user_id: str) -> bool:
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, task_run_id, with_for_update=True)
            if task is None or task.user_id != user_id or row is None or row.task_id != task_id or row.status not in {"launching", "running"} or row.run_id not in (None, run_id):
                return False
            durable = await session.get(RunRow, run_id)
            metadata = durable.metadata_json if durable is not None else {}
            if (
                durable is None
                or durable.user_id != user_id
                or durable.thread_id != row.thread_id
                or durable.status not in {"pending", "running"}
                or metadata.get("scheduled_task_id") != task_id
                or metadata.get("scheduled_task_run_id") != task_run_id
            ):
                return False
            row.stop_requested_run_id = run_id
            await session.commit()
            return True

    async def previous_occurrence(self, task_id: str, *, before_task_run_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            current = await session.get(ScheduledTaskRunRow, before_task_run_id)
            if current is None or current.task_id != task_id:
                return None
            query = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.id != before_task_run_id, ScheduledTaskRunRow.run_id.is_not(None))
            if current.occurrence_seq is not None:
                query = query.where(ScheduledTaskRunRow.occurrence_seq < current.occurrence_seq).order_by(ScheduledTaskRunRow.occurrence_seq.desc())
            else:
                sequenced = await session.scalar(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.occurrence_seq.is_not(None)).limit(1))
                if sequenced is not None:
                    return None
                query = query.where(ScheduledTaskRunRow.created_at <= current.created_at).order_by(ScheduledTaskRunRow.created_at.desc(), ScheduledTaskRunRow.scheduled_for.desc(), ScheduledTaskRunRow.id.desc())
            previous = await session.scalar(query.limit(1))
            return self._row_to_dict(previous) if previous is not None else None

    async def _finalize_recovered(self, session: AsyncSession, task: ScheduledTaskRow | None, row: ScheduledTaskRunRow, candidate: RunRow | None, *, error: str, now: datetime) -> bool:
        if candidate is not None:
            self._associate_scheduled_run(row, candidate)
        if candidate is not None and candidate.status == "success":
            status, outcome_error = "success", None
        elif candidate is not None and candidate.status in {"error", "timeout"}:
            status, outcome_error = "failed", candidate.error
        else:
            status, outcome_error = "interrupted", candidate.error if candidate is not None else None
            outcome_error = outcome_error or error
        return await finalize_occurrence(
            session,
            task,
            row,
            status=status,
            error=outcome_error,
            finished_at=now,
            run_id=candidate.run_id if candidate is not None else row.run_id,
            goal_verdict=candidate.goal_verdict if candidate is not None else None,
            observer=self._finalization_observer,
        )

    async def list_by_task(
        self,
        task_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: ScheduledTaskRunStatus | None = None,
    ) -> list[dict[str, Any]]:
        """Page of a task's occurrences, newest first.

        Each row adds ``run_number`` (see ``run_number_expression``),
        ``total_tokens`` of the launched run (None when nothing launched) and
        ``summary``: the first line of the agent's final reply. The goal
        evaluator's reason is deliberately not the summary; it stays in
        ``goal_verdict``.
        """
        number = run_number_expression(ScheduledTaskRunRow).label("run_number")
        stmt = select(ScheduledTaskRunRow, number, RunRow.total_tokens, RunRow.last_ai_message).outerjoin(RunRow, RunRow.run_id == ScheduledTaskRunRow.run_id).where(ScheduledTaskRunRow.task_id == task_id)
        if status is not None:
            stmt = stmt.where(ScheduledTaskRunRow.status == status)
        stmt = stmt.order_by(ScheduledTaskRunRow.created_at.desc(), ScheduledTaskRunRow.id.desc()).limit(limit).offset(offset)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = []
            for row, run_number, total_tokens, last_ai_message in result.all():
                data = self._row_to_dict(row)
                data["run_number"] = int(run_number) if run_number is not None else None
                data["total_tokens"] = int(total_tokens) if total_tokens is not None else None
                data["summary"] = run_summary(last_ai_message)
                rows.append(data)
            return rows

    async def run_number(self, task_run_id: str) -> int | None:
        """The automatic-run number of one occurrence (None for trials and never-launched rows)."""
        stmt = select(run_number_expression(ScheduledTaskRunRow)).where(ScheduledTaskRunRow.id == task_run_id)
        async with self._sf() as session:
            value = (await session.execute(stmt)).scalar()
        return int(value) if value is not None else None

    async def task_ids_for_thread(self, thread_id: str, *, user_id: str) -> list[str]:
        """Ids of the owner's tasks that ran an occurrence in this conversation."""
        stmt = select(ScheduledTaskRunRow.task_id).join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id).where(ScheduledTaskRunRow.thread_id == thread_id, ScheduledTaskRow.user_id == user_id).distinct()
        async with self._sf() as session:
            return sorted((await session.execute(stmt)).scalars())

    async def count_active_runs(self) -> int:
        """Count launch claims and live runs; waiting rows do not consume slots."""
        stmt = select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def list_queued_runs(self, *, limit: int, per_user_max_concurrent_runs: int = 0) -> list[dict[str, Any]]:
        """The next bounded drain batch, fair to task owners (see ``_fair_queue_statement``)."""
        stmt = self._fair_queue_statement(limit=limit, per_user_max_concurrent_runs=per_user_max_concurrent_runs)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    @staticmethod
    def _fair_queue_statement(*, limit: int, per_user_max_concurrent_runs: int = 0):
        """SELECT for the next bounded drain batch, fair to task owners.

        Only same-thread FIFO heads are eligible (an older active row on the
        same thread hides every newer one). Eligible rows are ranked within
        their owner by ``attempt_count, created_at, id`` and the batch is
        ordered by that rank first, so every owner's head comes before any
        owner's second row: one owner's backlog cannot fill the batch. With a
        per-owner cap, an owner only contributes as many rows as it has free
        slots (``cap - executing``), and owners already at the cap drop out
        before the limit is applied. With a single owner the order equals the
        plain ``attempt_count, created_at, id`` order.

        Rows whose task is gone (deleted while queued) have no owner. They are
        never launched (the drain marks them interrupted), so the cap does not
        hold them back.
        """
        candidate = aliased(ScheduledTaskRunRow)
        older = aliased(ScheduledTaskRunRow)
        older_same_thread = exists(
            select(older.id).where(
                older.thread_id == candidate.thread_id,
                older.status.in_(ACTIVE_RUN_STATUSES),
                or_(
                    older.created_at < candidate.created_at,
                    and_(
                        older.created_at == candidate.created_at,
                        older.id < candidate.id,
                    ),
                ),
            )
        )
        executing_run = aliased(ScheduledTaskRunRow)
        executing_task = aliased(ScheduledTaskRow)
        executing = (
            select(executing_task.user_id.label("owner"), func.count().label("n"))
            .select_from(executing_run)
            .join(executing_task, executing_task.id == executing_run.task_id)
            .where(executing_run.status.in_(EXECUTING_RUN_STATUSES))
            .group_by(executing_task.user_id)
            .subquery("executing")
        )
        owner_task = aliased(ScheduledTaskRow)
        eligible = (
            select(
                candidate.id.label("id"),
                candidate.attempt_count.label("attempt_count"),
                candidate.created_at.label("created_at"),
                owner_task.user_id.label("owner"),
                func.coalesce(executing.c.n, 0).label("owner_executing"),
                func.row_number()
                .over(
                    partition_by=owner_task.user_id,
                    order_by=(candidate.attempt_count.asc(), candidate.created_at.asc(), candidate.id.asc()),
                )
                .label("owner_rank"),
            )
            .select_from(candidate)
            .outerjoin(owner_task, owner_task.id == candidate.task_id)
            .outerjoin(executing, executing.c.owner == owner_task.user_id)
            .where(candidate.status == "queued", ~older_same_thread)
            .subquery("eligible")
        )
        stmt = select(ScheduledTaskRunRow).join(eligible, eligible.c.id == ScheduledTaskRunRow.id)
        if per_user_max_concurrent_runs > 0:
            stmt = stmt.where(
                or_(
                    eligible.c.owner.is_(None),
                    eligible.c.owner_rank <= per_user_max_concurrent_runs - eligible.c.owner_executing,
                )
            )
        # Prefer rows that have had fewer launch attempts within an owner. A
        # permanently busy thread therefore cannot monopolize the bounded drain
        # batch, while created_at/id preserve FIFO order among equal attempts.
        return stmt.order_by(
            eligible.c.owner_rank.asc(),
            eligible.c.attempt_count.asc(),
            eligible.c.created_at.asc(),
            eligible.c.id.asc(),
        ).limit(limit)

    async def get_active_run(self, task_id: str) -> dict[str, Any] | None:
        stmt = (
            select(ScheduledTaskRunRow)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(ScheduledTaskRunRow.created_at.asc(), ScheduledTaskRunRow.id.asc())
            .limit(1)
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return self._row_to_dict(row) if row is not None else None

    async def claim_queued_run(
        self,
        run_record_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
        global_max_concurrent_runs: int,
        per_user_max_concurrent_runs: int = 0,
    ) -> dict[str, Any] | None:
        """Atomically move one waiting row into the lease-fenced launch phase.

        Both budgets are checked under the same database-wide budget lock, so
        the per-owner cap is as atomic across workers and instances as the
        global one. A row rejected by either budget stays ``queued``.
        """
        async with self._sf() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _SCHEDULER_BUDGET_LOCK_KEY},
                )
            elif dialect == "sqlite":
                # The budget count below is only meaningful if no peer can
                # claim between it and the UPDATE. A deferred SQLite
                # transaction does not reserve the writer until that UPDATE,
                # which is too late: every claimer would read the same stale
                # count and pass. BEGIN IMMEDIATE takes the writer first, the
                # same reservation _lock_task makes for a parent row, and it
                # serializes claimers in other processes sharing the file too.
                # The claim targets one row, but the budget is global, so this
                # has to be the database-wide writer rather than a row lock.
                await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            if row is None:
                return None
            task = await self._lock_task(session, row.task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True, populate_existing=True)
            if row is None or row.status != "queued":
                return None
            if task is not None and row.trigger == "scheduled" and await end_condition_reached(session, task, now=now):
                await finalize_occurrence(session, task, row, status="skipped", error=RUN_ERROR_END_REACHED, finished_at=now, run_id=None, observer=self._finalization_observer)
                # finalize_occurrence already finished a live recurring task
                # (and emitted); this only clears the lease and covers rows
                # that could not project, without emitting twice.
                await finish_task_at_end_condition(session, task, occurrence=row, now=now, observer=self._finalization_observer)
                await session.commit()
                return None
            executing = await session.scalar(select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES)))
            if int(executing or 0) >= global_max_concurrent_runs:
                await session.rollback()
                return None
            if per_user_max_concurrent_runs > 0 and task is not None:
                owner_executing = await session.scalar(
                    select(func.count())
                    .select_from(ScheduledTaskRunRow)
                    .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                    .where(
                        ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES),
                        ScheduledTaskRow.user_id == task.user_id,
                    )
                )
                if int(owner_executing or 0) >= per_user_max_concurrent_runs:
                    await session.rollback()
                    return None
            older = aliased(ScheduledTaskRunRow)
            older_same_thread = exists(
                select(older.id).where(
                    older.thread_id == ScheduledTaskRunRow.thread_id,
                    older.status.in_(ACTIVE_RUN_STATUSES),
                    or_(
                        older.created_at < ScheduledTaskRunRow.created_at,
                        and_(
                            older.created_at == ScheduledTaskRunRow.created_at,
                            older.id < ScheduledTaskRunRow.id,
                        ),
                    ),
                )
            )
            result = await session.execute(
                update(ScheduledTaskRunRow)
                .where(
                    ScheduledTaskRunRow.id == run_record_id,
                    ScheduledTaskRunRow.status == "queued",
                    ~older_same_thread,
                )
                .values(
                    status="launching",
                    lease_owner=lease_owner,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempt_count=ScheduledTaskRunRow.attempt_count + 1,
                )
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            return self._row_to_dict(row) if row is not None else None

    async def requeue_claimed_run(
        self,
        run_record_id: str,
        *,
        lease_owner: str,
        error: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                update(ScheduledTaskRunRow)
                .where(
                    ScheduledTaskRunRow.id == run_record_id,
                    ScheduledTaskRunRow.status == "launching",
                    ScheduledTaskRunRow.lease_owner == lease_owner,
                )
                .values(
                    status="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    error=error,
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def expire_queued_runs(
        self,
        *,
        created_before: datetime,
        error: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Expire waiting rows and update each parent in one transaction.

        The queued child keeps the task unclaimable until the parent lock is
        held.  Releasing the child slot and advancing the parent in the same
        transaction prevents a peer scheduler from taking a stale due-task
        lease between those two writes.
        """
        async with self._sf() as session:
            candidate_keys = list(
                (
                    await session.execute(
                        select(
                            ScheduledTaskRunRow.id,
                            ScheduledTaskRunRow.task_id,
                        )
                        .where(
                            ScheduledTaskRunRow.status == "queued",
                            ScheduledTaskRunRow.created_at <= created_before,
                        )
                        .order_by(
                            ScheduledTaskRunRow.task_id.asc(),
                            ScheduledTaskRunRow.id.asc(),
                        )
                    )
                ).all()
            )

        expired: list[dict[str, Any]] = []
        for row_id, task_id in candidate_keys:
            async with self._sf() as session:
                task = await self._lock_task(session, task_id)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status != "queued":
                    await session.rollback()
                    continue

                row.status = "failed"
                row.error = error
                row.finished_at = now
                row.lease_owner = None
                row.lease_expires_at = None

                if task is not None and can_project(task, row):
                    if task.status == "paused":
                        # A concurrent/later pause owns the parent presentation.
                        task.lease_owner = None
                        task.lease_expires_at = None
                    else:
                        if row.trigger == "manual":
                            next_at = task.next_run_at
                            task_status = task.status or "enabled"
                        else:
                            next_at = compute_next_run_at(
                                task.schedule_type,
                                task.schedule_spec,
                                task.timezone,
                                now=now,
                            )
                            task_status = "failed" if task.schedule_type == "once" else "enabled"
                        task.status = task_status
                        task.next_run_at = next_at
                        task.last_thread_id = row.thread_id
                        task.last_error = error
                        task.lease_owner = None
                        task.lease_expires_at = None
                    task.updated_at = datetime.now(UTC)

                await session.commit()
                expired.append(self._row_to_dict(row))
        return expired

    async def fail_launching_run(
        self,
        run_record_id: str,
        *,
        task_id: str,
        lease_owner: str,
        error: str,
        now: datetime,
    ) -> bool:
        """Fail a claimed launch and update its parent without a release gap."""
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True)
            if row is None or row.task_id != task_id or row.status != "launching" or row.lease_owner != lease_owner:
                await session.rollback()
                return False

            row.status = "failed"
            row.error = error
            row.started_at = now
            row.finished_at = now
            row.lease_owner = None
            row.lease_expires_at = None

            if task is not None and can_project(task, row):
                if row.trigger == "manual":
                    task_status = task.status or "enabled"
                    next_at = task.next_run_at
                else:
                    task_status = "failed" if task.schedule_type == "once" else "enabled"
                    next_at = compute_next_run_at(
                        task.schedule_type,
                        task.schedule_spec,
                        task.timezone,
                        now=now,
                    )
                task.status = task_status
                task.next_run_at = next_at
                task.last_run_at = now
                task.last_run_id = None
                task.last_thread_id = row.thread_id
                # A failed trial on a task the host paused keeps its pause reason.
                if not (row.trigger == "manual" and task.status == "paused" and is_host_pause_marker(task.last_error)):
                    task.last_error = error
                task.lease_owner = None
                task.lease_expires_at = None
                task.updated_at = datetime.now(UTC)

            await session.commit()
            return True

    async def reconcile_launched_run(
        self,
        run_record_id: str,
        *,
        task_id: str,
        run_id: str,
        started_at: datetime,
    ) -> bool:
        """Associate a run that committed after its short claim was recovered.

        The Gateway launch path is idempotent per scheduled occurrence, so a
        peer that already reclaimed this row resolves to the same durable run.
        Parent-first locking restores the active slot before later parent
        bookkeeping can make the task due again.
        """
        async with self._sf() as session:
            await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True)
            if row is None or row.task_id != task_id:
                await session.rollback()
                return False
            if row.status in TERMINAL_RUN_STATUSES:
                if row.run_id is None:
                    # Timeout/pause can terminalize a claim that recovery
                    # briefly returned to ``queued`` while Gateway admission
                    # was still completing.  A returned durable run is the
                    # stronger fact; completion-owned terminal rows already
                    # carry this exact run_id and stay terminal below.
                    row.status = "running"
                    row.run_id = run_id
                    row.error = None
                    row.finished_at = None
                    row.started_at = row.started_at or started_at
                elif row.run_id != run_id:
                    await session.rollback()
                    return False
                elif row.started_at is None:
                    row.started_at = started_at
            else:
                row.status = "running"
                row.run_id = run_id
                row.error = None
                row.started_at = row.started_at or started_at
                row.lease_owner = None
                row.lease_expires_at = None
            await session.commit()
            return True

    async def recover_expired_launch_claims(self, *, error: str, now: datetime) -> int:
        """Recover single-instance claims that outlived their short lease."""
        stmt = (
            select(
                ScheduledTaskRunRow.id,
                ScheduledTaskRunRow.task_id,
            )
            .where(
                ScheduledTaskRunRow.status == "launching",
                or_(
                    ScheduledTaskRunRow.lease_expires_at.is_(None),
                    ScheduledTaskRunRow.lease_expires_at < now,
                ),
            )
            .order_by(
                ScheduledTaskRunRow.task_id.asc(),
                ScheduledTaskRunRow.id.asc(),
            )
        )
        async with self._sf() as session:
            row_keys = list((await session.execute(stmt)).all())
            recovered = 0
            for row_id, task_id in row_keys:
                task = await self._lock_task(session, task_id)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status != "launching":
                    continue
                candidate = await self._find_underlying_run(session, row, task)
                row.lease_owner = None
                row.lease_expires_at = None
                if candidate is None:
                    row.status = "queued"
                elif candidate.status in {"pending", "running"}:
                    self._associate_scheduled_run(row, candidate)
                    self._associate_task_with_run(task, row, candidate)
                    row.status = "running"
                    row.error = None
                else:
                    await self._finalize_recovered(session, task, row, candidate, error=error, now=now)
                recovered += 1
            await session.commit()
            return recovered

    async def update_status(
        self,
        run_record_id: str,
        *,
        status: str,
        run_id: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        protect_terminal: bool = False,
        expected_lease_owner: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            if row is None:
                return False
            # The lease-owner / terminal guards are only as fresh as the row
            # they read: on SQLite a plain SELECT sees a snapshot that a
            # concurrent requeue + re-claim can invalidate before this session
            # commits (the same staleness #5777 fixed for the parent task's
            # lease release). Take the parent's writer first — the same
            # task -> run lock order every other mutating path uses — and
            # re-read the row under it (populate_existing: the identity map
            # would otherwise serve the pre-lock row back untouched).
            await self._lock_task(session, row.task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True, populate_existing=True)
            if row is None:
                return False
            if protect_terminal and row.status in TERMINAL_RUN_STATUSES:
                # The launch-path "running" write lost the race against the
                # completion hook; keep the terminal status/error and only
                # backfill bookkeeping the completion write could not know.
                # Completion clears the short launch lease, so allow that
                # backfill after an owner mismatch only when the terminal row
                # already identifies the exact same durable run.  A stale
                # launcher for another run remains fenced.
                same_run = run_id is not None and row.run_id == run_id
                if expected_lease_owner is not None and row.lease_owner != expected_lease_owner and not same_run:
                    await session.rollback()
                    return False
                if row.run_id is None and run_id is not None:
                    row.run_id = run_id
                if row.started_at is None and started_at is not None:
                    row.started_at = started_at
                await session.commit()
                return True
            if expected_lease_owner is not None and row.lease_owner != expected_lease_owner:
                await session.rollback()
                return False
            row.status = status
            row.run_id = run_id
            row.error = error
            if status != "launching":
                row.lease_owner = None
                row.lease_expires_at = None
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()
            return True

    async def has_active_runs(self, task_id: str) -> bool:
        stmt = (
            select(ScheduledTaskRunRow.id)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return result.scalars().first() is not None

    async def mark_stale_active_runs(self, *, error: str) -> int:
        """Recover single-instance launch claims and fail orphaned live runs.

        Waiting rows are durable queue entries and survive restart. A
        ``launching`` row without a committed live run is safe to retry; a
        ``running`` row belonged to the dead in-process runtime.
        """
        stmt = (
            select(
                ScheduledTaskRunRow.id,
                ScheduledTaskRunRow.task_id,
            )
            .where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
            .order_by(
                ScheduledTaskRunRow.task_id.asc(),
                ScheduledTaskRunRow.id.asc(),
            )
        )
        now = datetime.now(UTC)
        async with self._sf() as session:
            row_keys = list((await session.execute(stmt)).all())
            recovered = 0
            for row_id, task_id in row_keys:
                task = await self._lock_task(session, task_id)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status not in EXECUTING_RUN_STATUSES:
                    continue
                row.lease_owner = None
                row.lease_expires_at = None
                candidate = await self._find_underlying_run(session, row, task)
                if row.status == "launching" and candidate is None:
                    row.status = "queued"
                else:
                    await self._finalize_recovered(session, task, row, candidate, error=error, now=now)
                recovered += 1
            await session.commit()
            return recovered

    async def reconcile_active_runs(
        self,
        *,
        error: str,
        now: datetime,
        lease_grace_seconds: int = 10,
    ) -> int:
        """Reconcile only rows whose underlying owner is no longer live.

        ``RunManager`` owns the durable run lease. A scheduled row with a live
        underlying run, or a queued row whose parent task still has a dispatch
        lease, belongs to another process and must survive this startup.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(
                    ScheduledTaskRunRow.id,
                    ScheduledTaskRunRow.task_id,
                )
                .where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
                .order_by(
                    ScheduledTaskRunRow.task_id.asc(),
                    ScheduledTaskRunRow.id.asc(),
                )
            )
            row_keys = list(result.all())
            stale = 0
            associations: list[tuple[ScheduledTaskRow | None, ScheduledTaskRunRow, RunRow]] = []
            finalizations: list[tuple[ScheduledTaskRow | None, ScheduledTaskRunRow, RunRow | None]] = []
            for row_id, task_id in row_keys:
                # Keep the same task -> scheduled-run lock order used by
                # pause/delete. Reversing these two locks lets a user action
                # and a peer reconciliation deadlock each other on Postgres.
                # Multi-instance reconciliation is Postgres-only. Keep this a
                # row lock without SQLite's writer-lock emulation because the
                # SQLite regression path performs durable-run takeover in a
                # nested short transaction below.
                task = await session.get(ScheduledTaskRow, task_id, with_for_update=True)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status not in EXECUTING_RUN_STATUSES:
                    continue
                candidate = await self._find_underlying_run(session, row, task)
                if candidate is not None:
                    self._associate_scheduled_run(row, candidate)
                    # Defer parent writes until all run takeovers have finished.
                    # Flushing a parent mutation before claim_for_takeover()
                    # would hold SQLite's writer lock across the nested short
                    # transaction used by that durable-run CAS.
                    associations.append((task, row, candidate))
                if candidate is not None and candidate.status not in {"pending", "running"}:
                    finalizations.append((task, row, candidate))
                    stale += 1
                    continue
                if candidate is not None and candidate.status in {"pending", "running"}:
                    if _lease_is_alive(candidate.lease_expires_at, now=now, grace_seconds=lease_grace_seconds):
                        # A peer can observe the committed durable run before
                        # the launcher writes its scheduled-run bookkeeping.
                        # Once reconciliation releases the short launch claim,
                        # that owner-fenced write must be allowed to fail
                        # without leaving incomplete or stale history behind.
                        row.error = None
                        if row.status == "launching":
                            row.status = "running"
                            row.lease_owner = None
                            row.lease_expires_at = None
                        continue
                    # Run takeover commits in its own short transaction. If this
                    # outer commit fails, the next poll finishes scheduled-row
                    # bookkeeping while the run remains safely terminal.
                    claimed = await self._run_repository.claim_for_takeover(
                        candidate.run_id,
                        grace_seconds=lease_grace_seconds,
                        error=error,
                        stop_reason="scheduled_task_orphan_recovered",
                    )
                    if not claimed:
                        refreshed = await self._run_repository.get(candidate.run_id, user_id=None)
                        if refreshed is not None and refreshed.get("status") in {"pending", "running"}:
                            continue
                        if refreshed is not None:
                            # Completion can beat takeover. Its committed
                            # terminal outcome/verdict is stronger than the
                            # active snapshot read above. Keep this detached:
                            # recovery must not write a stale ORM RunRow back.
                            candidate = RunRow(
                                run_id=candidate.run_id,
                                thread_id=candidate.thread_id,
                                user_id=candidate.user_id,
                                created_at=candidate.created_at,
                                status=refreshed["status"],
                                error=refreshed.get("error"),
                                goal_verdict=refreshed.get("goal_verdict"),
                            )
                if row.status == "launching" and row.run_id is None:
                    if _lease_is_alive(row.lease_expires_at, now=now, grace_seconds=0):
                        continue
                    row.status = "queued"
                    row.lease_owner = None
                    row.lease_expires_at = None
                    stale += 1
                    continue
                finalizations.append((task, row, candidate))
                stale += 1
            terminal_ids = {row.id for _, row, _ in finalizations}
            for task, row, candidate in associations:
                if row.id not in terminal_ids:
                    self._associate_task_with_run(task, row, candidate)
            for task, row, candidate in finalizations:
                await self._finalize_recovered(session, task, row, candidate, error=error, now=now)
            await session.commit()
            return stale

    @staticmethod
    async def _find_underlying_run(session: AsyncSession, row: ScheduledTaskRunRow, task: ScheduledTaskRow | None) -> RunRow | None:
        run_ids = [candidate for candidate in (row.run_id, task.last_run_id if task is not None else None) if candidate]
        for run_id in dict.fromkeys(run_ids):
            candidate = await session.get(RunRow, run_id)
            if candidate is None:
                continue
            linked_task_run_id = (candidate.metadata_json or {}).get("scheduled_task_run_id")
            # A stale parent ``last_run_id`` may point at a previous occurrence.
            # Let the current scheduled-run metadata lookup recover the live row.
            if linked_task_run_id is None or linked_task_run_id == row.id:
                return candidate

        result = await session.execute(select(RunRow).where(RunRow.metadata_json["scheduled_task_run_id"].as_string() == row.id).order_by(RunRow.created_at.desc()).limit(1))
        return result.scalars().first()

from __future__ import annotations

import hashlib
import json
import operator
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Text, and_, case, cast, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from deerflow.authz.workspace import WorkspaceContext, get_current_workspace, reset_current_workspace, set_current_workspace
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.finalization import FinalizationObserver, end_condition_reached, finalize_occurrence, finish_task_at_end_condition, is_host_pause_marker
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.projection import account_launch, can_project
from deerflow.persistence.scheduled_task_runs.scope import (
    ScheduledAdmissionReceipt,
    bound_native_run,
    captured_context,
    live_occurrence_predicate,
    live_task_predicate,
    lock_scheduled_identity,
    permits_occurrence_launch,
    resource_native_run_predicate,
    resource_occurrence_predicate,
    resource_task_predicate,
)
from deerflow.persistence.scheduled_tasks.model import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    ScheduledTaskRow,
    ScheduledTaskRunStatus,
)
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.model import WorkspaceAuditEventRow, WorkspaceMembershipRow, WorkspaceOperationOutboxRow, WorkspaceRow
from deerflow.persistence.workspaces.run_control import NativeRunStopTarget, execution_lifetime, pending_run_stop
from deerflow.persistence.workspaces.scope import resolve_resource_scope
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.scheduler.host_notes import RUN_ERROR_END_REACHED, RUN_ERROR_INTERRUPTED
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
        condition = and_(inner.task_id == outer.task_id, inner.workspace_id.is_not_distinct_from(outer.workspace_id), inner.trigger == "scheduled", inner.launch_accounted.is_(True), compare(inner.occurrence_seq, outer.occurrence_seq))
        return select(func.count()).select_from(inner).where(condition).correlate(outer).scalar_subquery()

    sequenced = and_(outer.trigger == "scheduled", outer.occurrence_seq.is_not(None))
    return case(
        (and_(sequenced, outer.launch_accounted.is_(True)), accounted(operator.le)),
        (and_(sequenced, outer.status.in_(("launching", "running"))), accounted(operator.lt) + 1),
        else_=None,
    )


def resource_run_number_expression(outer, context):
    """Public numbering counts only currently visible original occurrences.

    The background run_number_expression remains the original execution clock.
    """
    inner = aliased(ScheduledTaskRunRow)
    task = aliased(ScheduledTaskRow)

    def accounted(compare):
        return (
            select(func.count())
            .select_from(inner)
            .join(task, task.id == inner.task_id)
            .where(
                inner.task_id == outer.task_id,
                inner.trigger == "scheduled",
                inner.launch_accounted.is_(True),
                compare(inner.occurrence_seq, outer.occurrence_seq),
                resource_task_predicate(context, task),
                resource_occurrence_predicate(context, inner, task),
            )
            .correlate(outer)
            .scalar_subquery()
        )

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
        workspace_required: bool = False,
    ) -> None:
        self._sf = session_factory
        self.workspace_scope_required = workspace_required
        self._run_repository = run_repository or RunRepository(session_factory)
        self._finalization_observer: FinalizationObserver | None = None

    def set_finalization_observer(self, callback: FinalizationObserver | None) -> None:
        self._finalization_observer = callback

    @staticmethod
    def _revocation_covers(operation, context, *, member_version, policy_version):
        """Validate an existing native revoke identity, not a business grant."""
        payload = operation.payload
        if (
            type(member_version) is not int
            or type(policy_version) is not int
            or member_version <= context.membership_version
            or policy_version < context.policy_version
            or operation.kind != "workspace_revoke"
            or operation.state != "pending"
            or operation.workspace_id != context.workspace_id
            or operation.user_id != context.actor_user_id
            or type(payload) is not dict
            or type(payload.get("version")) is not int
            or payload["version"] != 1
            or type(payload.get("membership_version")) is not int
            or not context.membership_version <= payload["membership_version"] < member_version
            or type(payload.get("policy_version")) is not int
            or not context.policy_version <= payload["policy_version"] <= policy_version
            or type(payload.get("pending_domains")) is not list
            or "scheduler" not in payload["pending_domains"]
        ):
            return False
        identity = ["workspace_revoke", context.workspace_id, context.actor_user_id, payload["membership_version"], payload["policy_version"]]
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        return operation.operation_id == hashlib.sha256(encoded).hexdigest()

    async def retire_revoked_control_occurrences(self, *, now: datetime, limit: int = 64) -> frozenset[str]:
        """Retire proven closed/NoStart occurrence control, never business work.

        Workspace -> actor existence -> membership -> task -> occurrence -> Run
        -> completed lifetime -> revoke intent. No private-parent/checkpoint,
        model/result, quota/clock, finalization observer, STOP or capacity write.
        A completed native lifetime proves logical closure, not physical STOP.
        Independent pool reservations remain solely under stop_owned/report.
        Parent revoke and its scheduler domain deliberately remain pending.
        """
        if not self.workspace_scope_required or type(limit) is not int or limit <= 0:
            return frozenset()
        task_columns = tuple(
            getattr(ScheduledTaskRow, name)
            for name in (
                "id",
                "workspace_id",
                "user_id",
                "workspace_context_json",
                "status",
                "schedule_type",
                "updated_at",
                "next_run_at",
                "lease_owner",
                "lease_expires_at",
                "run_count",
                "last_run_id",
            )
        )
        occurrence_columns = tuple(
            getattr(ScheduledTaskRunRow, name)
            for name in (
                "id",
                "task_id",
                "workspace_id",
                "workspace_context_json",
                "thread_id",
                "thread_incarnation",
                "run_id",
                "trigger",
                "status",
                "launch_accounted",
                "started_at",
                "finished_at",
                "lease_owner",
                "lease_expires_at",
                "attempt_count",
                "stop_requested_run_id",
            )
        )
        run_columns = tuple(
            getattr(RunRow, name)
            for name in (
                "run_id",
                "user_id",
                "workspace_id",
                "thread_id",
                "thread_incarnation",
                "workspace_context_json",
                "owner_worker_id",
                "created_at",
                "operation_kind",
                "idempotency_key",
                "status",
                "cancel_action",
                "lease_expires_at",
            )
        ) + (
            RunRow.metadata_json["scheduled_task_id"].as_string().label("task_id"),
            RunRow.metadata_json["scheduled_task_run_id"].as_string().label("occurrence_id"),
            RunRow.metadata_json["scheduled_trigger"].as_string().label("trigger"),
        )
        operation_columns = tuple(
            getattr(WorkspaceOperationOutboxRow, name)
            for name in (
                "operation_id",
                "workspace_id",
                "user_id",
                "kind",
                "state",
                "payload",
                "lease_owner",
                "lease_token",
                "lease_expires_at",
                "attempt",
            )
        )
        no_start = and_(
            ScheduledTaskRunRow.status == "queued",
            ScheduledTaskRunRow.run_id.is_(None),
            ScheduledTaskRunRow.launch_accounted.is_(False),
            ScheduledTaskRunRow.started_at.is_(None),
            ScheduledTaskRunRow.finished_at.is_(None),
            ScheduledTaskRunRow.lease_owner.is_(None),
            ScheduledTaskRunRow.lease_expires_at.is_(None),
            ScheduledTaskRunRow.attempt_count == 0,
            ScheduledTaskRunRow.stop_requested_run_id.is_(None),
        )
        lifetime = aliased(WorkspaceOperationOutboxRow)
        closed_initial = exists(
            select(RunRow.run_id).where(
                ScheduledTaskRunRow.status == "running",
                ScheduledTaskRunRow.launch_accounted.is_(True),
                RunRow.run_id == ScheduledTaskRunRow.run_id,
                RunRow.workspace_id == ScheduledTaskRunRow.workspace_id,
                RunRow.user_id == ScheduledTaskRow.user_id,
                RunRow.thread_id == ScheduledTaskRunRow.thread_id,
                RunRow.thread_incarnation == ScheduledTaskRunRow.thread_incarnation,
                RunRow.operation_kind == "run",
                RunRow.idempotency_key == "scheduled-task:" + ScheduledTaskRunRow.id,
                RunRow.status.in_(("success", "error", "timeout", "interrupted")),
                exists(
                    select(lifetime.operation_id).where(
                        lifetime.kind == "run_execution",
                        lifetime.state == "completed",
                        lifetime.workspace_id == RunRow.workspace_id,
                        lifetime.user_id == RunRow.user_id,
                        lifetime.payload["run_id"].as_string() == RunRow.run_id,
                    )
                ),
            )
        ).correlate(ScheduledTaskRunRow, ScheduledTaskRow)
        revoke_exists = exists(
            select(WorkspaceOperationOutboxRow.operation_id).where(
                WorkspaceOperationOutboxRow.workspace_id == ScheduledTaskRow.workspace_id,
                WorkspaceOperationOutboxRow.user_id == ScheduledTaskRow.user_id,
                WorkspaceOperationOutboxRow.kind == "workspace_revoke",
                WorkspaceOperationOutboxRow.state == "pending",
            )
        ).correlate(ScheduledTaskRow)
        # Each finite page advances past malformed/unknown identities. Known
        # unsafe launching/transfer/open executions are excluded before LIMIT.
        cursor = ""
        while True:
            async with self._sf() as session:
                candidates = (
                    await session.execute(
                        select(
                            ScheduledTaskRunRow.id,
                            ScheduledTaskRunRow.task_id,
                            ScheduledTaskRow.workspace_id,
                            ScheduledTaskRow.user_id,
                        )
                        .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                        .where(
                            ScheduledTaskRunRow.id > cursor,
                            ScheduledTaskRunRow.workspace_id.is_not(None),
                            ScheduledTaskRunRow.workspace_id == ScheduledTaskRow.workspace_id,
                            revoke_exists,
                            or_(no_start, closed_initial),
                        )
                        .order_by(ScheduledTaskRunRow.id)
                        .limit(limit)
                    )
                ).all()
            if not candidates:
                break
            for locator in candidates:
                cursor = locator.id
                async with self._sf() as session:
                    if session.get_bind().dialect.name == "sqlite":
                        await session.execute(text("BEGIN IMMEDIATE"))
                    workspace = (await session.execute(select(WorkspaceRow.id, WorkspaceRow.policy_version).where(WorkspaceRow.id == locator.workspace_id).with_for_update())).first()
                    actor = await session.scalar(select(UserRow.id).where(UserRow.id == locator.user_id).with_for_update())
                    member = (
                        await session.execute(
                            select(WorkspaceMembershipRow.status, WorkspaceMembershipRow.version)
                            .where(
                                WorkspaceMembershipRow.workspace_id == locator.workspace_id,
                                WorkspaceMembershipRow.user_id == locator.user_id,
                            )
                            .with_for_update()
                        )
                    ).first()
                    if workspace is None or actor is None or member is None:
                        continue
                    task = (await session.execute(select(*task_columns, cast(ScheduledTaskRow.workspace_context_json, Text).label("snapshot_text")).where(ScheduledTaskRow.id == locator.task_id).with_for_update())).first()
                    occurrence = (await session.execute(select(*occurrence_columns, cast(ScheduledTaskRunRow.workspace_context_json, Text).label("snapshot_text")).where(ScheduledTaskRunRow.id == locator.id).with_for_update())).first()
                    try:
                        if task is None or occurrence is None:
                            continue
                        context = WorkspaceContext(**task.workspace_context_json)
                        if (
                            context.workspace_id != locator.workspace_id
                            or context.actor_user_id != locator.user_id
                            or task.workspace_id != context.workspace_id
                            or task.user_id != context.actor_user_id
                            or occurrence.workspace_id != context.workspace_id
                            or occurrence.task_id != task.id
                            or occurrence.workspace_context_json != asdict(context)
                            or (member.status == "active" and member.version == context.membership_version)
                            or member.version <= context.membership_version
                            or occurrence.trigger not in ("scheduled", "manual")
                            or task.status not in ("enabled", "running", "paused")
                            or task.schedule_type not in ("once", "cron", "interval")
                            or type(occurrence.thread_id) is not str
                            or not occurrence.thread_id
                            or type(occurrence.thread_incarnation) is not str
                            or not occurrence.thread_incarnation
                        ):
                            continue
                        if occurrence.status == "queued":
                            if not (
                                occurrence.run_id is None
                                and occurrence.launch_accounted is False
                                and occurrence.started_at is None
                                and occurrence.finished_at is None
                                and occurrence.lease_owner is None
                                and occurrence.lease_expires_at is None
                                and type(occurrence.attempt_count) is int
                                and occurrence.attempt_count == 0
                                and occurrence.stop_requested_run_id is None
                            ):
                                continue
                        elif occurrence.status == "running" and occurrence.launch_accounted is True:
                            native = (await session.execute(select(*run_columns).where(RunRow.run_id == occurrence.run_id).with_for_update())).first()
                            if native is None:
                                continue
                            target = NativeRunStopTarget.from_row(native)
                            if (
                                target.workspace_context != context
                                or target.user_id != task.user_id
                                or target.thread_id != occurrence.thread_id
                                or target.thread_incarnation != occurrence.thread_incarnation
                                or native.operation_kind != "run"
                                or native.idempotency_key != "scheduled-task:" + occurrence.id
                                or native.status not in ("success", "error", "timeout", "interrupted")
                                or native.task_id != task.id
                                or native.occurrence_id != occurrence.id
                                or native.trigger != occurrence.trigger
                            ):
                                continue
                            execution = (
                                await session.execute(
                                    select(*operation_columns)
                                    .where(
                                        WorkspaceOperationOutboxRow.operation_id == target.execution_id,
                                    )
                                    .with_for_update()
                                )
                            ).first()
                            if (
                                execution is None
                                or execution.kind != "run_execution"
                                or execution.state != "completed"
                                or execution.workspace_id != context.workspace_id
                                or execution.user_id != task.user_id
                                or type(execution.payload) is not dict
                                or type(execution.payload.get("version")) is not int
                                or execution.payload["version"] != 1
                                or execution.payload.get("binding") != target.execution_binding()
                                or execution.payload.get("owner_worker_id") != target.owner_worker_id
                            ):
                                continue
                        else:
                            continue
                        operations = (
                            await session.execute(
                                select(*operation_columns)
                                .where(
                                    WorkspaceOperationOutboxRow.workspace_id == context.workspace_id,
                                    WorkspaceOperationOutboxRow.user_id == context.actor_user_id,
                                    WorkspaceOperationOutboxRow.kind == "workspace_revoke",
                                    WorkspaceOperationOutboxRow.state == "pending",
                                )
                                .order_by(WorkspaceOperationOutboxRow.operation_id)
                                .with_for_update()
                            )
                        ).all()
                        operation = next((row for row in operations if self._revocation_covers(row, context, member_version=member.version, policy_version=workspace.policy_version)), None)
                        if operation is None:
                            continue
                    except (TypeError, ValueError):
                        continue
                    # Exact finite control snapshots, no old lease or native
                    # association can be inferred away by status alone.
                    exact_occurrence = [column.is_not_distinct_from(getattr(occurrence, column.key)) for column in occurrence_columns if column.key != "workspace_context_json"]
                    changed = await session.execute(
                        update(ScheduledTaskRunRow)
                        .where(
                            *exact_occurrence,
                            cast(ScheduledTaskRunRow.workspace_context_json, Text) == occurrence.snapshot_text,
                        )
                        .values(status="interrupted", error=RUN_ERROR_INTERRUPTED, finished_at=now)
                    )
                    if changed.rowcount != 1:
                        continue
                    exact_task = [column.is_not_distinct_from(getattr(task, column.key)) for column in task_columns if column.key != "workspace_context_json"]
                    updated = await session.execute(
                        update(ScheduledTaskRow)
                        .where(
                            *exact_task,
                            cast(ScheduledTaskRow.workspace_context_json, Text) == task.snapshot_text,
                        )
                        .values(status="cancelled" if task.schedule_type == "once" else "paused", next_run_at=None, updated_at=now)
                    )
                    if updated.rowcount != 1:
                        await session.rollback()
                        continue
                    session.add(
                        WorkspaceAuditEventRow(
                            id=str(uuid5(NAMESPACE_URL, "scheduler.revoke_settled:" + occurrence.id)),
                            workspace_id=context.workspace_id,
                            actor_user_id=None,
                            action="scheduler.revoke_settled",
                            resource_id=occurrence.id,
                            outcome="success",
                            request_id=operation.operation_id,
                        )
                    )
                    await session.commit()
        # SQL success can precede a failed host call. Re-read ALL audit pages,
        # independently of fresh candidates: first-page historical receipts
        # cannot permanently mask a later ledger wait. These are locators only.
        replay, cursor = set(), ""
        while True:
            async with self._sf() as session:
                rows = (
                    await session.execute(
                        select(
                            WorkspaceAuditEventRow.id,
                            ScheduledTaskRunRow.run_id,
                            ScheduledTaskRunRow.id.label("occurrence_id"),
                            ScheduledTaskRunRow.workspace_context_json,
                            WorkspaceMembershipRow.version.label("member_version"),
                            WorkspaceRow.policy_version.label("current_policy_version"),
                            *operation_columns,
                        )
                        .join(ScheduledTaskRunRow, ScheduledTaskRunRow.id == WorkspaceAuditEventRow.resource_id)
                        .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                        .join(RunRow, RunRow.run_id == ScheduledTaskRunRow.run_id)
                        .join(WorkspaceOperationOutboxRow, WorkspaceOperationOutboxRow.operation_id == WorkspaceAuditEventRow.request_id)
                        .join(WorkspaceMembershipRow, and_(WorkspaceMembershipRow.workspace_id == ScheduledTaskRow.workspace_id, WorkspaceMembershipRow.user_id == ScheduledTaskRow.user_id))
                        .join(WorkspaceRow, WorkspaceRow.id == ScheduledTaskRow.workspace_id)
                        .where(
                            WorkspaceAuditEventRow.id > cursor,
                            WorkspaceAuditEventRow.action == "scheduler.revoke_settled",
                            WorkspaceAuditEventRow.outcome == "success",
                            WorkspaceAuditEventRow.actor_user_id.is_(None),
                            WorkspaceAuditEventRow.workspace_id == ScheduledTaskRunRow.workspace_id,
                            ScheduledTaskRunRow.status == "interrupted",
                            ScheduledTaskRunRow.workspace_id == ScheduledTaskRow.workspace_id,
                            cast(ScheduledTaskRunRow.workspace_context_json, Text) == cast(ScheduledTaskRow.workspace_context_json, Text),
                            cast(ScheduledTaskRunRow.workspace_context_json, Text) == cast(RunRow.workspace_context_json, Text),
                            RunRow.metadata_json["scheduled_task_id"].as_string() == ScheduledTaskRow.id,
                            RunRow.metadata_json["scheduled_task_run_id"].as_string() == ScheduledTaskRunRow.id,
                            RunRow.metadata_json["scheduled_trigger"].as_string() == ScheduledTaskRunRow.trigger,
                            RunRow.workspace_id == ScheduledTaskRunRow.workspace_id,
                            RunRow.user_id == ScheduledTaskRow.user_id,
                            RunRow.thread_id == ScheduledTaskRunRow.thread_id,
                            RunRow.thread_incarnation == ScheduledTaskRunRow.thread_incarnation,
                            RunRow.operation_kind == "run",
                            RunRow.idempotency_key == "scheduled-task:" + ScheduledTaskRunRow.id,
                            WorkspaceOperationOutboxRow.kind == "workspace_revoke",
                            WorkspaceOperationOutboxRow.state == "pending",
                            WorkspaceOperationOutboxRow.workspace_id == RunRow.workspace_id,
                            WorkspaceOperationOutboxRow.user_id == RunRow.user_id,
                        )
                        .order_by(WorkspaceAuditEventRow.id)
                        .limit(limit)
                    )
                ).all()
            if not rows:
                break
            for row in rows:
                try:
                    context = WorkspaceContext(**row.workspace_context_json)
                except (TypeError, ValueError):
                    continue
                if (
                    row.member_version > context.membership_version
                    and self._revocation_covers(row, context, member_version=row.member_version, policy_version=row.current_policy_version)
                    and row.id == str(uuid5(NAMESPACE_URL, "scheduler.revoke_settled:" + row.occurrence_id))
                ):
                    replay.add(row.run_id)
            cursor = rows[-1].id
        return frozenset(replay)

    async def resolve_launch_authority(self, receipt):
        if not self.workspace_scope_required or type(receipt) is not ScheduledAdmissionReceipt:
            raise WorkspaceAccessDenied("Scoped Scheduler launch receipt is required")
        async with self._sf() as session:
            task, occurrence, context = await lock_scheduled_identity(session, self._sf, receipt.task_id, occurrence_id=receipt.occurrence_id, receipt=receipt)
            result = {"context": context, "thread_id": occurrence.thread_id, "thread_incarnation": occurrence.thread_incarnation, "user_id": task.user_id}
            await session.commit()
            return result

    async def transfer_dependency_run(self, *, task_id: str, occurrence_id: str, user_id: str, source_run_id: str, continuation_run_id: str) -> None:
        """Move an existing occurrence's run association without new admission/accounting."""
        if self.workspace_scope_required:
            if source_run_id == continuation_run_id:
                raise WorkspaceAccessDenied("Dependency transfer requires a distinct continuation")
            async with self._sf() as session:
                # Original identity comes from SQL, never the ambient UI or
                # notification payload. Preserve parents -> task -> occurrence
                # -> sorted Run rows; this changes no native Run/clock receipt.
                task, occurrence, context = await lock_scheduled_identity(session, self._sf, task_id, occurrence_id=occurrence_id)
                if task.user_id != user_id or occurrence.status != "running":
                    raise WorkspaceAccessDenied("Scheduled dependency occurrence is unavailable")
                rows = (await session.scalars(select(RunRow).where(RunRow.run_id.in_((source_run_id, continuation_run_id))).order_by(RunRow.run_id).with_for_update())).all()
                native = {row.run_id: row for row in rows}
                source, continuation = native.get(source_run_id), native.get(continuation_run_id)
                for run in (source, continuation):
                    metadata = (run.metadata_json or {}) if run is not None else {}
                    if (
                        run is None
                        or not isinstance(metadata, dict)
                        or run.operation_kind != "run"
                        or run.workspace_id != task.workspace_id
                        or run.user_id != user_id
                        or run.thread_id != occurrence.thread_id
                        or run.thread_incarnation != occurrence.thread_incarnation
                        or run.workspace_context_json != asdict(context)
                        or metadata.get("scheduled_task_id") != task_id
                        or metadata.get("scheduled_task_run_id") != occurrence_id
                        or metadata.get("scheduled_trigger") != occurrence.trigger
                    ):
                        raise WorkspaceAccessDenied("Scheduled dependency native identity differs")
                if continuation.idempotency_key != "mcp-dependencies:" + source_run_id:
                    raise WorkspaceAccessDenied("Scheduled dependency continuation key differs")
                if source.status != "success" or source.cancel_action is not None or (source.goal_verdict or {}).get("native_dependency_wait") is not True:
                    raise WorkspaceAccessDenied("Scheduled dependency source was superseded")
                if occurrence.run_id == continuation_run_id:
                    # Repeated exact association observes history only. It does
                    # not renew a lease, recreate work or grant native launch.
                    await session.commit()
                    return
                if occurrence.run_id != source_run_id or continuation.status != "pending" or continuation.cancel_action is not None:
                    raise WorkspaceAccessDenied("Scheduled dependency continuation was superseded")
                expiry = continuation.lease_expires_at
                if expiry is not None and expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if expiry is None or expiry <= datetime.now(UTC) or await session.scalar(select(pending_run_stop(run_id=continuation_run_id))):
                    raise WorkspaceAccessDenied("Scheduled dependency continuation is not live")
                await execution_lifetime(session, NativeRunStopTarget.from_row(continuation))
                # Native admission already enforces the source cleanup barrier;
                # independently require its execution lifetime to be closed.
                lifetime = await execution_lifetime(session, NativeRunStopTarget.from_row(source), open_only=False)
                if lifetime.state != "completed":
                    raise WorkspaceAccessDenied("Scheduled dependency source execution has not drained")
                occurrence.run_id = continuation_run_id
                if task.last_run_id == source_run_id:
                    task.last_run_id = continuation_run_id
                await session.commit()
                return
        if get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Legacy dependency transfer cannot inherit workspace authority")
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            occurrence = await session.get(ScheduledTaskRunRow, occurrence_id, with_for_update=True)
            source = await session.get(RunRow, source_run_id)
            continuation = await session.get(RunRow, continuation_run_id)
            if task is None or task.user_id != user_id or occurrence is None or occurrence.workspace_id is not None or occurrence.task_id != task_id or occurrence.status != "running" or source is None or continuation is None:
                raise ValueError("Scheduled dependency occurrence unavailable")
            for run in (source, continuation):
                metadata = run.metadata_json or {}
                if run.workspace_id is not None or run.user_id != user_id or run.thread_id != occurrence.thread_id or metadata.get("scheduled_task_id") != task_id or metadata.get("scheduled_task_run_id") != occurrence_id:
                    raise ValueError("Scheduled dependency occurrence identity mismatch")
            if occurrence.run_id == continuation_run_id:
                return
            if occurrence.run_id != source_run_id or source.status != "success" or source.cancel_action or (source.goal_verdict or {}).get("native_dependency_wait") is not True or continuation.status != "pending":
                raise ValueError("Scheduled dependency transfer was superseded")
            occurrence.run_id = continuation_run_id
            if task.last_run_id == source_run_id:
                task.last_run_id = continuation_run_id
            await session.commit()

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

    async def _lock_task(self, session: AsyncSession, task_id: str) -> ScheduledTaskRow | None:
        # SQLite ignores SELECT ... FOR UPDATE. Touch the parent first so its
        # single-writer lock provides the same serialization point used by
        # Postgres row locking for admission, mutation, pause, and delete.
        if self.workspace_scope_required:
            return (await lock_scheduled_identity(session, self._sf, task_id))[0]
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id, ScheduledTaskRow.workspace_id.is_(None)).values(updated_at=ScheduledTaskRow.updated_at))
        return await session.scalar(select(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id, ScheduledTaskRow.workspace_id.is_(None)).with_for_update())

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
        manual_context: WorkspaceContext | None = None,
        worker_target: NativeRunStopTarget | None = None,
        expected_token_version: int | None = None,
    ) -> dict[str, Any]:
        queue_parent = None
        original_context = None
        if self.workspace_scope_required:
            manual = trigger == "manual"
            if trigger not in {"manual", "scheduled"} or (manual and type(manual_context) is not WorkspaceContext):
                raise WorkspaceAccessDenied("Manual Scheduler admission requires current resource identity")
            if not manual and (manual_context is not None or worker_target is not None or expected_token_version is not None):
                raise WorkspaceAccessDenied("Scheduled admission cannot inherit manual authority")
            async with self._sf() as validation:
                source = (await lock_scheduled_identity(validation, self._sf, task_id, context=manual_context if manual else None))[0]
                if manual and source.workspace_context_json != asdict(manual_context):
                    raise WorkspaceAccessDenied("Original task authority expired; create/copy a new task")
                original_context = captured_context(source)
                context_mode, fixed_thread = source.context_mode, source.thread_id
                await validation.commit()
            token = set_current_workspace(original_context)
            try:
                threads = ThreadMetaRepository(self._sf, workspace_required=True)
                parent = await threads.get(thread_id, user_id=original_context.actor_user_id)
                if context_mode == "fresh_thread_per_run":
                    if parent is not None:
                        raise WorkspaceAccessDenied("Scheduler fresh execution thread already exists")
                    parent = await threads.create(thread_id, user_id=original_context.actor_user_id)
                elif thread_id != fixed_thread or parent is None:
                    raise WorkspaceAccessDenied("Scheduler reuse parent is unavailable")
                queue_parent = (thread_id, parent["incarnation"])
            finally:
                reset_current_workspace(token)
        row = ScheduledTaskRunRow(
            id=run_record_id,
            workspace_id=original_context.workspace_id if original_context else None,
            workspace_context_json=asdict(original_context) if original_context else None,
            thread_incarnation=queue_parent[1] if queue_parent else None,
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
            if not self.workspace_scope_required and await session.scalar(select(ScheduledTaskRow.workspace_id).where(ScheduledTaskRow.id == task_id)) is not None:
                raise WorkspaceAccessDenied("Legacy occurrence cannot attach to a scoped task")
            if self.workspace_scope_required:
                extra = ((worker_target.thread_id, worker_target.thread_incarnation),) if type(worker_target) is NativeRunStopTarget else ()
                task = (await lock_scheduled_identity(session, self._sf, task_id, context=manual_context if trigger == "manual" else None, execution_parent=queue_parent, extra_parents=extra))[0]
                if trigger == "manual":
                    if task.workspace_context_json != asdict(manual_context):
                        raise WorkspaceAccessDenied("Original task authority expired; create/copy a new task")
                    if not coordinate_with_task or expected_task_user_id != manual_context.actor_user_id or expected_task_status is None or expected_task_updated_at is None:
                        raise WorkspaceAccessDenied("Manual admission requires its original resource confirmation")
                    if worker_target is None:
                        if expected_token_version is not None:
                            raise WorkspaceAccessDenied("Manual worker credential requires its execution")
                    elif type(worker_target) is not NativeRunStopTarget or worker_target.workspace_context != manual_context or worker_target.user_id != task.user_id or type(expected_token_version) is not int or expected_token_version < 0:
                        raise WorkspaceAccessDenied("Manual admission execution differs")
                    if not permits_occurrence_launch(task, row):
                        raise WorkspaceAccessDenied("Manual task state is unavailable")
                    if worker_target is not None:
                        related = task.origin_thread_id == worker_target.thread_id and task.origin_thread_incarnation == worker_target.thread_incarnation
                        if not related:
                            related = bool(
                                await session.scalar(
                                    select(ScheduledTaskRunRow.id)
                                    .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                                    .where(
                                        ScheduledTaskRunRow.task_id == task.id,
                                        ScheduledTaskRunRow.thread_id == worker_target.thread_id,
                                        ScheduledTaskRunRow.thread_incarnation == worker_target.thread_incarnation,
                                        resource_occurrence_predicate(manual_context),
                                    )
                                    .limit(1)
                                )
                            )
                        if not related:
                            raise WorkspaceAccessDenied("Manual task is outside its original conversation")
                        if await session.scalar(select(UserRow.token_version).where(UserRow.id == task.user_id)) != expected_token_version:
                            raise WorkspaceAccessDenied("Scheduler original credential changed")
                        execution, _ = await self._run_repository._lock_worker_effect_after_parent(session, worker_target)
                        if execution.status != "running":
                            raise WorkspaceAccessDenied("Manual admission requires its running native execution")
            else:
                if manual_context is not None or worker_target is not None or expected_token_version is not None:
                    raise WorkspaceAccessDenied("Legacy occurrence cannot inherit manual scope")
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

    async def _lock_own_stop(self, session, occurrence_id, *, task_id, run_id, user_id, target, preparing=False):
        if type(target) is not NativeRunStopTarget or target.run_id != run_id or target.user_id != user_id:
            raise WorkspaceAccessDenied("Own-stop requires its actual native execution")
        task, occurrence, context = await lock_scheduled_identity(session, self._sf, task_id, occurrence_id=occurrence_id, context=target.workspace_context)
        if context != target.workspace_context or task.user_id != user_id or occurrence.status not in {"launching", "running"} or occurrence.run_id != run_id:
            raise WorkspaceAccessDenied("Own-stop occurrence is not this bound execution")
        if preparing:
            # Assembly happens before run_agent's pending -> running barrier.
            # Bind only immutable identity here; no control write is granted.
            native = await session.scalar(select(RunRow).where(RunRow.run_id == run_id).with_for_update())
            if native is None or NativeRunStopTarget.from_row(native) != target or native.status not in {"pending", "running"} or native.cancel_action is not None:
                raise WorkspaceAccessDenied("Own-stop assembly execution is unavailable")
            expiry = native.lease_expires_at
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry is None or expiry <= datetime.now(UTC) or await session.scalar(select(pending_run_stop(run_id=run_id))):
                raise WorkspaceAccessDenied("Own-stop assembly execution is not live")
            await execution_lifetime(session, target)
        else:
            native, _ = await self._run_repository._lock_worker_effect_after_parent(session, target)
            if native.status != "running":
                raise WorkspaceAccessDenied("Own-stop requires its running native execution")
        await bound_native_run(session, task, occurrence, run_id)
        return occurrence

    async def validate_own_stop(self, *, task_id, occurrence_id, worker_target):
        """Independent canonical SQL check, never a Session or manage grant."""
        async with self._sf() as session:
            if type(worker_target) is not NativeRunStopTarget:
                raise WorkspaceAccessDenied("Own-stop assembly requires canonical native identity")
            await self._lock_own_stop(session, occurrence_id, task_id=task_id, run_id=worker_target.run_id, user_id=worker_target.user_id, target=worker_target, preparing=True)
            await session.commit()
        return True

    async def request_stop(self, task_run_id: str, *, task_id: str, run_id: str, user_id: str, worker_target: NativeRunStopTarget | None = None) -> bool:
        if self.workspace_scope_required or get_current_workspace() is not None:
            async with self._sf() as session:
                row = await self._lock_own_stop(session, task_run_id, task_id=task_id, run_id=run_id, user_id=user_id, target=worker_target)
                if row.stop_requested_run_id not in (None, run_id):
                    return False
                row.stop_requested_run_id = run_id
                await session.commit()
                return True
        if worker_target is not None:
            raise WorkspaceAccessDenied("Legacy own-stop cannot inherit native execution")
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, task_run_id, with_for_update=True)
            if task is None or task.user_id != user_id or row is None or row.workspace_id is not None or row.task_id != task_id or row.status not in {"launching", "running"} or row.run_id not in (None, run_id):
                return False
            durable = await session.get(RunRow, run_id)
            metadata = durable.metadata_json if durable is not None else {}
            if (
                durable is None
                or durable.workspace_id is not None
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
        if self.workspace_scope_required or get_current_workspace() is not None:
            async with self._sf() as session:
                task, current, context = await lock_scheduled_identity(session, self._sf, task_id, occurrence_id=before_task_run_id)
                previous = await session.scalar(
                    select(ScheduledTaskRunRow)
                    .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                    .join(RunRow, resource_native_run_predicate())
                    .where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.occurrence_seq < current.occurrence_seq, resource_occurrence_predicate(context), ScheduledTaskRunRow.status.in_(TERMINAL_RUN_STATUSES))
                    .order_by(ScheduledTaskRunRow.occurrence_seq.desc())
                    .limit(1)
                )
                result = self._row_to_dict(previous) if previous is not None else None
                await session.commit()
                return result
        async with self._sf() as session:
            current = await session.get(ScheduledTaskRunRow, before_task_run_id)
            if current is None or current.workspace_id is not None or current.task_id != task_id:
                return None
            query = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.id != before_task_run_id, ScheduledTaskRunRow.run_id.is_not(None))
            if current.occurrence_seq is not None:
                query = query.where(ScheduledTaskRunRow.occurrence_seq < current.occurrence_seq).order_by(ScheduledTaskRunRow.occurrence_seq.desc())
            else:
                sequenced = await session.scalar(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.occurrence_seq.is_not(None)).limit(1))
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
        current = get_current_workspace()
        context = resolve_resource_scope(None, current.actor_user_id if current is not None else None, required=self.workspace_scope_required)
        if context is not None:
            number = resource_run_number_expression(ScheduledTaskRunRow, context).label("run_number")
            stmt = (
                select(ScheduledTaskRunRow, number, RunRow.total_tokens, RunRow.last_ai_message)
                .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                .outerjoin(RunRow, resource_native_run_predicate())
                .where(ScheduledTaskRunRow.task_id == task_id, resource_task_predicate(context), resource_occurrence_predicate(context))
            )
        else:
            number = run_number_expression(ScheduledTaskRunRow).label("run_number")
            stmt = (
                select(ScheduledTaskRunRow, number, RunRow.total_tokens, RunRow.last_ai_message)
                .outerjoin(RunRow, and_(RunRow.run_id == ScheduledTaskRunRow.run_id, RunRow.workspace_id.is_(None)))
                .where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRunRow.task_id == task_id)
            )
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
        """Original-authority launch provenance; public scoped history stays closed."""
        stmt = select(run_number_expression(ScheduledTaskRunRow)).where(ScheduledTaskRunRow.id == task_run_id)
        async with self._sf() as session:
            if self.workspace_scope_required:
                locator = await session.get(ScheduledTaskRunRow, task_run_id)
                if locator is None or locator.workspace_id is None:
                    return None
                await lock_scheduled_identity(session, self._sf, locator.task_id, occurrence_id=task_run_id)
            else:
                stmt = stmt.where(ScheduledTaskRunRow.workspace_id.is_(None))
            value = (await session.execute(stmt)).scalar()
            await session.commit()
        return int(value) if value is not None else None

    async def task_ids_for_thread(self, thread_id: str, *, user_id: str) -> list[str]:
        """Ids of the owner's tasks that ran an occurrence in this conversation."""
        if self.workspace_scope_required or get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Scoped Scheduler status/history requires current private-resource integration")
        stmt = (
            select(ScheduledTaskRunRow.task_id)
            .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
            .where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRow.workspace_id.is_(None), ScheduledTaskRunRow.thread_id == thread_id, ScheduledTaskRow.user_id == user_id)
            .distinct()
        )
        async with self._sf() as session:
            return sorted((await session.execute(stmt)).scalars())

    async def count_active_runs(self) -> int:
        """Count launch claims and live runs; waiting rows do not consume slots."""
        if self.workspace_scope_required or get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Scoped occurrence status requires current private-resource integration")
        stmt = select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def list_queued_runs(self, *, limit: int, per_user_max_concurrent_runs: int = 0) -> list[dict[str, Any]]:
        """Native fair queue with original-authority filtering before the limit."""
        stmt = self._fair_queue_statement(limit=limit, per_user_max_concurrent_runs=per_user_max_concurrent_runs, workspace_scoped=self.workspace_scope_required)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    @staticmethod
    def _fair_queue_statement(*, limit: int, per_user_max_concurrent_runs: int = 0, workspace_scoped=False):
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
        candidate_scope = (
            and_(candidate.workspace_id.is_not(None), candidate.workspace_id == owner_task.workspace_id, live_task_predicate(owner_task), live_occurrence_predicate(candidate, owner_task))
            if workspace_scoped
            else and_(candidate.workspace_id.is_(None), or_(owner_task.id.is_(None), owner_task.workspace_id.is_(None)))
        )
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
            .where(candidate_scope, candidate.status == "queued", ~older_same_thread)
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
        from deerflow.persistence.thread_meta.model import ThreadMetaRow

        stmt = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES))
        context = get_current_workspace()
        async with self._sf() as session:
            if self.workspace_scope_required or context is not None:
                if context is None:
                    raise WorkspaceAccessDenied("Scheduler active occurrence requires its current resource actor")
                await lock_scheduled_identity(session, self._sf, task_id, context=context)
                parent = (
                    ThreadMetaRepository._owned_scope(
                        select(ThreadMetaRow.thread_id).where(ThreadMetaRow.thread_id == ScheduledTaskRunRow.thread_id, ThreadMetaRow.incarnation == ScheduledTaskRunRow.thread_incarnation), context.actor_user_id, context
                    )
                    .correlate(ScheduledTaskRunRow)
                    .exists()
                )
                stmt = stmt.where(ScheduledTaskRunRow.workspace_id == context.workspace_id, parent)
            else:
                stmt = stmt.where(ScheduledTaskRunRow.workspace_id.is_(None))
            row = await session.scalar(stmt.limit(1))
            result = self._row_to_dict(row) if row else None
            await session.commit()
            return result

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
            if self.workspace_scope_required:
                locator = await session.get(ScheduledTaskRunRow, run_record_id)
                if locator is None or locator.workspace_id is None:
                    return None
                task, row, _ = await lock_scheduled_identity(session, self._sf, locator.task_id, occurrence_id=run_record_id, budget_key=_SCHEDULER_BUDGET_LOCK_KEY)
                if row.status != "queued" or not permits_occurrence_launch(task, row):
                    return None
                executing = await session.scalar(select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES)))
                if int(executing or 0) >= global_max_concurrent_runs:
                    return None
                if per_user_max_concurrent_runs > 0:
                    own = await session.scalar(
                        select(func.count())
                        .select_from(ScheduledTaskRunRow)
                        .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                        .where(ScheduledTaskRow.user_id == task.user_id, ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
                    )
                    if int(own or 0) >= per_user_max_concurrent_runs:
                        return None
                if await session.scalar(
                    select(ScheduledTaskRunRow.id)
                    .where(ScheduledTaskRunRow.thread_id == row.thread_id, ScheduledTaskRunRow.id != row.id, ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES), ScheduledTaskRunRow.created_at <= row.created_at)
                    .limit(1)
                ):
                    return None
                row.status, row.lease_owner, row.lease_expires_at = "launching", lease_owner, now + timedelta(seconds=lease_seconds)
                row.attempt_count += 1
                await session.commit()
                return self._row_to_dict(row)
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
            if row is None or row.workspace_id is not None:
                return None
            task = await self._lock_task(session, row.task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True, populate_existing=True)
            if row is None or row.workspace_id is not None or row.status != "queued":
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
                    ScheduledTaskRunRow.workspace_id.is_(None),
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
        if self.workspace_scope_required or get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Scoped occurrence mutation requires its native control integration")
        async with self._sf() as session:
            result = await session.execute(
                update(ScheduledTaskRunRow)
                .where(
                    ScheduledTaskRunRow.workspace_id.is_(None),
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
        if self.workspace_scope_required:
            async with self._sf() as session:
                expired = await session.scalar(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.workspace_id.is_not(None), ScheduledTaskRunRow.status == "queued", ScheduledTaskRunRow.created_at < created_before).limit(1))
                if expired is not None:
                    raise WorkspaceAccessDenied("Scoped queue timeout requires native no-start control integration")
                return []
        async with self._sf() as session:
            candidate_keys = list(
                (
                    await session.execute(
                        select(
                            ScheduledTaskRunRow.id,
                            ScheduledTaskRunRow.task_id,
                        )
                        .where(
                            ScheduledTaskRunRow.workspace_id.is_(None),
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
        if self.workspace_scope_required or get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Scoped occurrence mutation requires its native control integration")
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True)
            if row is None or row.workspace_id is not None or row.task_id != task_id or row.status != "launching" or row.lease_owner != lease_owner:
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
        if self.workspace_scope_required or get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Scoped occurrence mutation requires its native control integration")
        async with self._sf() as session:
            await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True)
            if row is None or row.workspace_id is not None or row.task_id != task_id:
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

    async def _reconcile_scoped_terminal_runs(self, *, error, now):
        """Project only exact canonical terminal Runs; unknown executions stay held.

        This never takes over a native Run, requeues an unbound launch, or
        acknowledges STOP. Revoked identities and absent/active Runs are kept
        for the native lifecycle/control path rather than guessed terminal.
        """
        async with self._sf() as locator_session:
            keys = (
                await locator_session.execute(
                    select(ScheduledTaskRunRow.id, ScheduledTaskRunRow.task_id)
                    .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                    .join(RunRow, RunRow.run_id == ScheduledTaskRunRow.run_id)
                    .where(
                        ScheduledTaskRunRow.workspace_id.is_not(None),
                        ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES),
                        ScheduledTaskRunRow.workspace_id == ScheduledTaskRow.workspace_id,
                        RunRow.workspace_id == ScheduledTaskRunRow.workspace_id,
                        RunRow.user_id == ScheduledTaskRow.user_id,
                        RunRow.thread_id == ScheduledTaskRunRow.thread_id,
                        RunRow.thread_incarnation == ScheduledTaskRunRow.thread_incarnation,
                        RunRow.status.in_(("success", "error", "timeout", "interrupted")),
                        or_(RunRow.status != "success", RunRow.cancel_action.is_not(None), RunRow.goal_verdict["native_dependency_wait"].as_boolean().is_not(True)),
                        live_task_predicate(),
                    )
                    .order_by(ScheduledTaskRunRow.task_id, ScheduledTaskRunRow.id)
                    .limit(64)
                )
            ).all()
        completed = 0
        for occurrence_id, task_id in keys:
            async with self._sf() as session:
                try:
                    task, occurrence, _ = await lock_scheduled_identity(session, self._sf, task_id, occurrence_id=occurrence_id)
                    if occurrence.status not in EXECUTING_RUN_STATUSES:
                        continue
                    native = await self._find_underlying_run(session, occurrence, task)
                    if native is None or native.status not in ("success", "error", "timeout", "interrupted"):
                        continue
                    if native.status == "success" and native.cancel_action is None and (native.goal_verdict or {}).get("native_dependency_wait") is True:
                        continue
                    completed += bool(await self._finalize_recovered(session, task, occurrence, native, error=error, now=now))
                    await session.commit()
                except WorkspaceAccessDenied:
                    await session.rollback()
        return completed

    async def recover_expired_launch_claims(self, *, error: str, now: datetime) -> int:
        """Recover single-instance claims that outlived their short lease."""
        if self.workspace_scope_required:
            return await self._reconcile_scoped_terminal_runs(error=error, now=now)
        stmt = (
            select(
                ScheduledTaskRunRow.id,
                ScheduledTaskRunRow.task_id,
            )
            .where(
                ScheduledTaskRunRow.workspace_id.is_(None),
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
                if task is not None and task.workspace_id is not None:
                    continue
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
        if self.workspace_scope_required and (status != "running" or not run_id or not expected_lease_owner):
            raise WorkspaceAccessDenied("Scoped occurrence status accepts only exact launch bookkeeping")
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
            if self.workspace_scope_required:
                task, row, _ = await lock_scheduled_identity(session, self._sf, row.task_id, occurrence_id=run_record_id)
                await bound_native_run(session, task, row, run_id)
            else:
                if row.workspace_id is not None:
                    return False
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
        if self.workspace_scope_required or get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Scoped occurrence status requires current private-resource integration")
        stmt = (
            select(ScheduledTaskRunRow.id)
            .where(
                ScheduledTaskRunRow.workspace_id.is_(None),
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
        if self.workspace_scope_required:
            return await self._reconcile_scoped_terminal_runs(error=error, now=datetime.now(UTC))
        stmt = (
            select(
                ScheduledTaskRunRow.id,
                ScheduledTaskRunRow.task_id,
            )
            .where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
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
                if task is not None and task.workspace_id is not None:
                    continue
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

    async def dependency_wait_sources(self) -> frozenset[str]:
        """Snapshot sources to examine before recovery takes writer locks."""
        if self.workspace_scope_required:
            async with self._sf() as session:
                # IDs are control locators only. Original SQL task identity,
                # private parents and exact normal Run metadata filter before
                # selection; the host independently revalidates every receipt.
                result = await session.scalars(
                    select(RunRow.run_id)
                    .select_from(ScheduledTaskRunRow)
                    .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
                    .join(RunRow, resource_native_run_predicate())
                    .where(
                        ScheduledTaskRunRow.workspace_id.is_not(None),
                        ScheduledTaskRunRow.workspace_id == ScheduledTaskRow.workspace_id,
                        ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES),
                        RunRow.metadata_json["scheduled_trigger"].as_string() == ScheduledTaskRunRow.trigger,
                        live_task_predicate(),
                        live_occurrence_predicate(ScheduledTaskRunRow, ScheduledTaskRow),
                        RunRow.status == "success",
                        RunRow.cancel_action.is_(None),
                        RunRow.goal_verdict["native_dependency_wait"].as_boolean().is_(True),
                    )
                    .order_by(RunRow.run_id)
                )
                # No bounded first page can indefinitely hide later sources
                # behind already-protected waiting occurrences.
                return frozenset(result)
        if get_current_workspace() is not None:
            raise WorkspaceAccessDenied("Legacy dependency sources cannot inherit workspace authority")
        async with self._sf() as session:
            result = await session.execute(
                select(RunRow.run_id)
                .join(ScheduledTaskRunRow, ScheduledTaskRunRow.run_id == RunRow.run_id)
                .where(
                    ScheduledTaskRunRow.workspace_id.is_(None),
                    RunRow.workspace_id.is_(None),
                    ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES),
                    RunRow.status == "success",
                    RunRow.goal_verdict["native_dependency_wait"].as_boolean().is_(True),
                )
            )
            return frozenset(result.scalars())

    async def reconcile_active_runs(
        self,
        *,
        error: str,
        now: datetime,
        lease_grace_seconds: int = 10,
        valid_dependency_wait_runs: frozenset[str] = frozenset(),
        checked_dependency_wait_runs: frozenset[str] | None = None,
    ) -> int:
        """Reconcile only rows whose underlying owner is no longer live.

        ``RunManager`` owns the durable run lease. A scheduled row with a live
        underlying run, or a queued row whose parent task still has a dispatch
        lease, belongs to another process and must survive this startup.
        """
        if self.workspace_scope_required:
            return await self._reconcile_scoped_terminal_runs(error=error, now=now)

        def protects_dependency_wait(candidate, task, row):
            if candidate is None or candidate.status != "success" or (candidate.goal_verdict or {}).get("native_dependency_wait") is not True:
                return False
            if checked_dependency_wait_runs is not None and candidate.run_id not in checked_dependency_wait_runs:
                # Completion after preflight is unchecked, not invalid.
                return True
            return (
                not candidate.cancel_action
                and candidate.run_id in valid_dependency_wait_runs
                and task is not None
                and candidate.user_id == task.user_id
                and candidate.thread_id == row.thread_id
                and (candidate.metadata_json or {}).get("scheduled_task_id") == task.id
                and (candidate.metadata_json or {}).get("scheduled_task_run_id") == row.id
            )

        async with self._sf() as session:
            result = await session.execute(
                select(
                    ScheduledTaskRunRow.id,
                    ScheduledTaskRunRow.task_id,
                )
                .where(ScheduledTaskRunRow.workspace_id.is_(None), ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
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
                if task is not None and task.workspace_id is not None:
                    continue
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
                if protects_dependency_wait(candidate, task, row):
                    # The host's durable dependency receipt owns settlement;
                    # this occurrence retains overlap/global budget protection.
                    continue
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
                                run_id=refreshed["run_id"],
                                thread_id=refreshed["thread_id"],
                                user_id=refreshed.get("user_id"),
                                created_at=candidate.created_at,
                                metadata_json=refreshed.get("metadata") or {},
                                cancel_action=refreshed.get("cancel_action"),
                                status=refreshed["status"],
                                error=refreshed.get("error"),
                                goal_verdict=refreshed.get("goal_verdict"),
                            )
                            if protects_dependency_wait(candidate, task, row):
                                continue
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
        if row.workspace_id is not None:
            if task is None or task.workspace_id != row.workspace_id or task.workspace_context_json != row.workspace_context_json or row.run_id is None:
                return None
            native = await session.get(RunRow, row.run_id)
            if (
                native is None
                or native.workspace_id != row.workspace_id
                or native.user_id != task.user_id
                or native.thread_id != row.thread_id
                or native.thread_incarnation != row.thread_incarnation
                or native.workspace_context_json != row.workspace_context_json
                or (native.metadata_json or {}).get("scheduled_task_id") != task.id
                or (native.metadata_json or {}).get("scheduled_task_run_id") != row.id
            ):
                return None
            return native
        run_ids = [candidate for candidate in (row.run_id, task.last_run_id if task is not None else None) if candidate]
        for run_id in dict.fromkeys(run_ids):
            candidate = await session.get(RunRow, run_id)
            if candidate is None or candidate.workspace_id is not None:
                continue
            linked_task_run_id = (candidate.metadata_json or {}).get("scheduled_task_run_id")
            # A stale parent ``last_run_id`` may point at a previous occurrence.
            # Let the current scheduled-run metadata lookup recover the live row.
            if linked_task_run_id is None or linked_task_run_id == row.id:
                return candidate

        result = await session.execute(select(RunRow).where(RunRow.workspace_id.is_(None), RunRow.metadata_json["scheduled_task_run_id"].as_string() == row.id).order_by(RunRow.created_at.desc()).limit(1))
        return result.scalars().first()

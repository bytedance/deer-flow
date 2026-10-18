"""Native Scheduler SQL identity and lease fences, never client authority.

The original context is read from the task. Receipts carry CAS expectations only.
Scoped lock order: workspace/actor, sorted private parents, budget (claim only),
task, occurrence, then the native Run clock/Run. No network/checkpoint IO here.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, text

from deerflow.authz.workspace import WorkspaceContext
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceRow
from deerflow.persistence.workspaces.scope import lock_resource_scope
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository


@dataclass(frozen=True, slots=True)
class ScheduledAdmissionReceipt:
    task_id: str
    occurrence_id: str
    lease_owner: str
    attempt_count: int

    def __post_init__(self):
        if any(not isinstance(value, str) or not value or value.strip() != value for value in (self.task_id, self.occurrence_id, self.lease_owner)) or type(self.attempt_count) is not int or self.attempt_count < 1:
            raise ValueError("Scheduler receipt requires exact server claim identity")


def captured_context(task):
    try:
        context = WorkspaceContext(**task.workspace_context_json)
    except (TypeError, ValueError):
        raise WorkspaceAccessDenied("Scheduler original authority is unavailable") from None
    if context.workspace_id != task.workspace_id or context.actor_user_id != task.user_id:
        raise WorkspaceAccessDenied("Scheduler original identity changed")
    return context


def live_task_predicate(row=ScheduledTaskRow):
    def parent(identity, incarnation):
        project = select(ProjectRow.id).where(ProjectRow.id == ThreadMetaRow.project_id, ProjectRow.workspace_id == row.workspace_id).correlate(ThreadMetaRow, row).exists()
        owned = (
            select(ThreadMetaRow.thread_id)
            .where(
                ThreadMetaRow.thread_id == identity,
                ThreadMetaRow.incarnation == incarnation,
                ThreadMetaRow.user_id == row.user_id,
                ThreadMetaRow.workspace_id == row.workspace_id,
                ThreadMetaRow.status != "deleting",
                or_(ThreadMetaRow.project_id.is_(None), project),
            )
            .correlate(row)
            .exists()
        )
        return or_(identity.is_(None), owned)

    return (
        WorkspaceRepository._membership_query(row.user_id)
        .where(
            WorkspaceRow.id == row.workspace_id,
            WorkspaceRow.policy_version == row.workspace_context_json["policy_version"].as_integer(),
            WorkspaceMembershipRow.version == row.workspace_context_json["membership_version"].as_integer(),
            row.workspace_context_json["workspace_id"].as_string() == row.workspace_id,
            row.workspace_context_json["actor_user_id"].as_string() == row.user_id,
            parent(row.origin_thread_id, row.origin_thread_incarnation),
            parent(row.thread_id, row.thread_incarnation),
        )
        .correlate(row)
        .exists()
    )


def live_occurrence_predicate(occurrence, task):
    """Exclude stale execution parents and snapshots before fair-queue LIMIT."""
    project = select(ProjectRow.id).where(ProjectRow.id == ThreadMetaRow.project_id, ProjectRow.workspace_id == task.workspace_id).correlate(ThreadMetaRow, task).exists()
    parent = (
        select(ThreadMetaRow.thread_id)
        .where(
            ThreadMetaRow.thread_id == occurrence.thread_id,
            ThreadMetaRow.incarnation == occurrence.thread_incarnation,
            ThreadMetaRow.user_id == task.user_id,
            ThreadMetaRow.workspace_id == occurrence.workspace_id,
            ThreadMetaRow.status != "deleting",
            or_(ThreadMetaRow.project_id.is_(None), project),
        )
        .correlate(occurrence, task)
        .exists()
    )
    return (
        parent
        & (occurrence.workspace_context_json["workspace_id"].as_string() == task.workspace_context_json["workspace_id"].as_string())
        & (occurrence.workspace_context_json["actor_user_id"].as_string() == task.workspace_context_json["actor_user_id"].as_string())
        & (occurrence.workspace_context_json["membership_version"].as_integer() == task.workspace_context_json["membership_version"].as_integer())
        & (occurrence.workspace_context_json["policy_version"].as_integer() == task.workspace_context_json["policy_version"].as_integer())
    )


async def lock_scheduled_identity(session, sf, task_id, *, occurrence_id=None, context=None, receipt=None, execution_parent=None, budget_key=None):
    # Locator reads acquire no task/occurrence locks before native parents.
    locator = await session.scalar(select(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id))
    if locator is None or locator.workspace_id is None:
        raise WorkspaceAccessDenied("Scoped Scheduler task is unavailable")
    original = captured_context(locator)
    context = original if context is None else context
    if context.workspace_id != original.workspace_id or context.actor_user_id != locator.user_id:
        raise WorkspaceAccessDenied("Scheduler resource actor differs")
    located_parents = (locator.origin_thread_id, locator.origin_thread_incarnation, locator.thread_id, locator.thread_incarnation)
    occurrence = await session.get(ScheduledTaskRunRow, occurrence_id) if occurrence_id else None
    if occurrence_id and (occurrence is None or occurrence.task_id != task_id or occurrence.workspace_id != original.workspace_id or occurrence.workspace_context_json != asdict(original)):
        raise WorkspaceAccessDenied("Scheduler occurrence original identity differs")
    parents = {}
    for thread_id, incarnation in (
        (locator.origin_thread_id, locator.origin_thread_incarnation),
        (locator.thread_id, locator.thread_incarnation),
        (occurrence.thread_id if occurrence else None, occurrence.thread_incarnation if occurrence else None),
    ):
        if thread_id is not None:
            if not incarnation or (thread_id in parents and parents[thread_id] != incarnation):
                raise WorkspaceAccessDenied("Scheduler parent identity is unavailable")
            parents[thread_id] = incarnation
    if execution_parent is not None:
        parent_id, incarnation = execution_parent
        if not incarnation or (parent_id in parents and parents[parent_id] != incarnation):
            raise WorkspaceAccessDenied("Scheduler queued parent identity differs")
        parents[parent_id] = incarnation
    await lock_resource_scope(session, context)
    for thread_id in sorted(parents):
        parent = await session.scalar(ThreadMetaRepository._owned_scope(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id), locator.user_id, context).with_for_update())
        if parent is None or parent.incarnation != parents[thread_id]:
            raise WorkspaceAccessDenied("Scheduler private parent changed")
    if budget_key is not None and session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": budget_key})
    task = await session.scalar(select(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).with_for_update().execution_options(populate_existing=True))
    if task is None or captured_context(task) != original or (task.origin_thread_id, task.origin_thread_incarnation, task.thread_id, task.thread_incarnation) != located_parents:
        raise WorkspaceAccessDenied("Scheduler task changed during admission")
    if occurrence_id:
        occurrence = await session.scalar(select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == occurrence_id).with_for_update().execution_options(populate_existing=True))
        if (
            occurrence is None
            or occurrence.task_id != task_id
            or occurrence.workspace_id != original.workspace_id
            or occurrence.workspace_context_json != asdict(original)
            or parents.get(occurrence.thread_id) != occurrence.thread_incarnation
        ):
            raise WorkspaceAccessDenied("Scheduler occurrence changed during admission")
    if receipt is not None:
        expiry = occurrence.lease_expires_at if occurrence else None
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if (
            type(receipt) is not ScheduledAdmissionReceipt
            or receipt.task_id != task_id
            or receipt.occurrence_id != occurrence_id
            or occurrence is None
            or occurrence.status != "launching"
            or occurrence.lease_owner != receipt.lease_owner
            or occurrence.attempt_count != receipt.attempt_count
            or expiry is None
            or expiry <= datetime.now(UTC)
        ):
            raise WorkspaceAccessDenied("Scheduler launch lease changed")
    return task, occurrence, original


async def bound_native_run(session, task, occurrence, run_id):
    """Validate only the Scheduler's existing native Run association."""
    native = await session.get(RunRow, run_id) if run_id else None
    if (
        occurrence is None
        or occurrence.task_id != task.id
        or occurrence.run_id != run_id
        or native is None
        or occurrence.workspace_id != task.workspace_id
        or occurrence.workspace_context_json != task.workspace_context_json
        or native.operation_kind != "run"
        or native.workspace_id != task.workspace_id
        or native.user_id != task.user_id
        or native.thread_id != occurrence.thread_id
        or native.thread_incarnation != occurrence.thread_incarnation
        or native.workspace_context_json != task.workspace_context_json
        or (native.metadata_json or {}).get("scheduled_task_id") != task.id
        or (native.metadata_json or {}).get("scheduled_task_run_id") != occurrence.id
    ):
        raise WorkspaceAccessDenied("Scheduler bookkeeping lacks its exact native Run")
    return native

"""Transactional task state. Callers verify identity and execution evidence."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.coordination.model import CoordinationInputRow, CoordinationTaskRow, TaskStatus
from deerflow.utils.time import coerce_iso

_OPEN = {TaskStatus.QUEUED, TaskStatus.RUNNING}


class TaskNotFound(LookupError):
    """The task is absent or belongs to a different owner."""


class TaskConflict(ValueError):
    """The requested update conflicts with the current task state."""


def _request_id(value: str) -> None:
    if not value.strip() or len(value) > 200:
        raise ValueError("Request ID must contain 1 to 200 characters")


def _touch(row: CoordinationTaskRow) -> None:
    row.revision += 1
    row.updated_at = datetime.now(UTC)


def _check_revision(row: CoordinationTaskRow, expected_revision: int) -> None:
    if row.revision != expected_revision:
        raise TaskConflict("Task revision changed")


def _snapshot(row: CoordinationTaskRow | CoordinationInputRow) -> dict:
    result = row.to_dict()
    result["created_at"] = coerce_iso(result["created_at"])
    if isinstance(row, CoordinationTaskRow):
        result["updated_at"] = coerce_iso(result["updated_at"])
    return result


class CoordinationTaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions.begin() as session:
            if session.get_bind().dialect.name == "sqlite":
                await session.execute(text("BEGIN IMMEDIATE"))
            yield session

    async def _lookup(self, session: AsyncSession, owner_id: str, task_id: str) -> CoordinationTaskRow:
        row = await session.scalar(select(CoordinationTaskRow).filter_by(id=task_id, owner_id=owner_id))
        if row is None:
            raise TaskNotFound(task_id)
        return row

    async def _lock_tree(self, session: AsyncSession, owner_id: str, task_id: str) -> CoordinationTaskRow:
        # All writes to an existing tree lock the root first. Fetch the target
        # after taking the lock so a concurrent cancellation cannot leave a
        # stale status in the ORM identity map.
        root_id = await session.scalar(select(CoordinationTaskRow.root_id).filter_by(id=task_id, owner_id=owner_id))
        if root_id is None:
            raise TaskNotFound(task_id)
        await session.execute(select(CoordinationTaskRow.id).filter_by(id=root_id, owner_id=owner_id).with_for_update())
        return await self._lookup(session, owner_id, task_id)

    async def get(self, owner_id: str, task_id: str) -> dict:
        async with self._sessions() as session:
            return _snapshot(await self._lookup(session, owner_id, task_id))

    async def create(
        self,
        owner_id: str,
        *,
        request_id: str,
        objective: str,
        project_id: str | None = None,
        parent_id: str | None = None,
        depends_on: Sequence[str] = (),
        run_settings: dict[str, int | bool] | None = None,
    ) -> dict:
        """Create a task once. Dependencies refer to previously created siblings."""
        _request_id(request_id)
        if not objective.strip():
            raise ValueError("Task objective is required")
        dependencies = sorted(set(depends_on))
        saved_run_settings = dict(run_settings) if run_settings else None
        async with self._write() as session:
            parent = await self._lock_tree(session, owner_id, parent_id) if parent_id is not None else None
            if parent is not None:
                if project_id is not None and project_id != parent.project_id:
                    raise TaskConflict("A child task must use its parent's project")
                project_id = parent.project_id
            create_fields = dict(objective=objective, project_id=project_id, parent_id=parent_id, depends_on=dependencies, run_settings=saved_run_settings)
            existing = await session.scalar(select(CoordinationTaskRow).filter_by(owner_id=owner_id, request_id=request_id))
            if existing is None:
                if parent is not None and parent.status not in _OPEN:
                    raise TaskConflict("Parent task is closed")
                if dependencies:
                    query = select(CoordinationTaskRow.id).filter_by(owner_id=owner_id, project_id=project_id, parent_id=parent_id)
                    found = set((await session.scalars(query.where(CoordinationTaskRow.id.in_(dependencies)))).all())
                    if found != set(dependencies):
                        raise TaskConflict("Dependencies must be existing tasks with the same owner, project and parent")
                task_id = uuid4().hex
                now = datetime.now(UTC)
                insert = postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
                await session.execute(
                    insert(CoordinationTaskRow)
                    .values(
                        **create_fields,
                        id=task_id,
                        owner_id=owner_id,
                        request_id=request_id,
                        root_id=parent.root_id if parent is not None else task_id,
                        status=TaskStatus.QUEUED,
                        revision=0,
                        execution_epoch=0,
                        latest_input_seq=0,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["owner_id", "request_id"])
                )
                existing = (await session.scalars(select(CoordinationTaskRow).filter_by(owner_id=owner_id, request_id=request_id))).one()
                if existing.id == task_id and parent is not None:
                    _touch(parent)
            if any(getattr(existing, key) != value for key, value in create_fields.items()):
                raise TaskConflict("Request ID was already used with different task data")
            return _snapshot(existing)

    @staticmethod
    async def _matching_input(session: AsyncSession, task_id: str, request_id: str, content: str) -> dict | None:
        existing = await session.scalar(select(CoordinationInputRow).filter_by(task_id=task_id, request_id=request_id))
        if existing is None:
            return None
        if existing.content != content:
            raise TaskConflict("Request ID was already used with different input")
        return _snapshot(existing)

    async def replay_input(self, owner_id: str, task_id: str, *, request_id: str, content: str) -> dict | None:
        """Return the owner's accepted receipt, including for a closed task."""
        async with self._sessions() as session:
            await self._lookup(session, owner_id, task_id)
            return await self._matching_input(session, task_id, request_id, content)

    async def append_input(self, owner_id: str, task_id: str, *, request_id: str, content: str) -> dict:
        _request_id(request_id)
        if not content.strip():
            raise ValueError("Task input is required")
        async with self._write() as session:
            task = await self._lock_tree(session, owner_id, task_id)
            if (receipt := await self._matching_input(session, task_id, request_id, content)) is not None:
                return receipt
            if task.status not in _OPEN:
                raise TaskConflict("Task is closed to new input")
            task.latest_input_seq += 1
            _touch(task)
            row = CoordinationInputRow(task_id=task_id, sequence=task.latest_input_seq, request_id=request_id, content=content, created_at=task.updated_at)
            session.add(row)
            return _snapshot(row)

    async def list_inputs(self, owner_id: str, task_id: str, *, after: int = 0, limit: int = 100) -> list[dict]:
        if after < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid input page")
        async with self._sessions() as session:
            query = (
                select(CoordinationInputRow)
                .join(CoordinationTaskRow, CoordinationTaskRow.id == CoordinationInputRow.task_id)
                .where(CoordinationTaskRow.owner_id == owner_id, CoordinationInputRow.task_id == task_id, CoordinationInputRow.sequence > after)
                .order_by(CoordinationInputRow.sequence)
                .limit(limit)
            )
            return [_snapshot(row) for row in (await session.scalars(query)).all()]

    async def start(self, owner_id: str, task_id: str, *, expected_revision: int) -> dict:
        """Claim the task for work and return the revision and input watermark."""
        async with self._write() as session:
            task = await self._lock_tree(session, owner_id, task_id)
            _check_revision(task, expected_revision)
            await self._start_locked(session, task)
            return _snapshot(task)

    async def _start_locked(self, session: AsyncSession, task: CoordinationTaskRow) -> None:
        if task.status != TaskStatus.QUEUED:
            raise TaskConflict("Only a queued task can start")
        if task.parent_id is not None:
            parent = await self._lookup(session, task.owner_id, task.parent_id)
            if parent.status != TaskStatus.RUNNING:
                raise TaskConflict("Parent task has not started")
        if task.depends_on:
            query = select(CoordinationTaskRow.id).filter_by(owner_id=task.owner_id, status=TaskStatus.SUCCEEDED)
            ready = set((await session.scalars(query.where(CoordinationTaskRow.id.in_(task.depends_on)))).all())
            if ready != set(task.depends_on):
                raise TaskConflict("Task dependencies have not succeeded")
        task.status = TaskStatus.RUNNING
        _touch(task)

    async def finish(
        self,
        owner_id: str,
        task_id: str,
        *,
        expected_revision: int,
        execution_epoch: int,
        covered_input_seq: int,
        outcome: TaskStatus,
        result_ref: str,
    ) -> dict:
        if outcome not in (TaskStatus.SUCCEEDED, TaskStatus.FAILED) or not result_ref.strip():
            raise ValueError("A success or failure outcome and a result reference are required")
        async with self._write() as session:
            task = await self._lock_tree(session, owner_id, task_id)
            if task.status != TaskStatus.RUNNING or task.execution_epoch != execution_epoch:
                raise TaskConflict("Task no longer accepts results from this execution")
            _check_revision(task, expected_revision)
            if task.latest_input_seq != covered_input_seq:
                raise TaskConflict("Result does not cover the current task inputs")
            await self._finish_locked(session, task, outcome, result_ref)
            return _snapshot(task)

    async def _finish_locked(self, session: AsyncSession, task: CoordinationTaskRow, outcome: TaskStatus, result_ref: str) -> None:
        children = (await session.scalars(select(CoordinationTaskRow.status).filter_by(parent_id=task.id, owner_id=task.owner_id))).all()
        accepted = {TaskStatus.SUCCEEDED} if outcome == TaskStatus.SUCCEEDED else {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        if any(status not in accepted for status in children):
            raise TaskConflict("Child tasks have not settled for this outcome")
        task.status = outcome
        task.result_ref = result_ref
        _touch(task)

    async def _subtree(self, session: AsyncSession, task: CoordinationTaskRow) -> list[CoordinationTaskRow]:
        rows = (await session.scalars(select(CoordinationTaskRow).filter_by(owner_id=task.owner_id, root_id=task.root_id))).all()
        children = defaultdict(list)
        for row in rows:
            children[row.parent_id].append(row)
        result = []
        pending = deque([task])
        while pending:
            row = pending.popleft()
            result.append(row)
            pending.extend(children[row.id])
        return result

    async def request_cancel(self, owner_id: str, task_id: str, *, expected_revision: int) -> dict:
        """Stop accepting work in the ownership subtree before stopping its runs."""
        async with self._write() as session:
            task = await self._lock_tree(session, owner_id, task_id)
            if task.status in (TaskStatus.CANCELLING, TaskStatus.CANCELLED):
                return _snapshot(task)
            _check_revision(task, expected_revision)
            if task.status not in _OPEN:
                raise TaskConflict("Task has already finished")
            for row in await self._subtree(session, task):
                if row.status in _OPEN:
                    row.status = TaskStatus.CANCELLING
                    row.execution_epoch += 1
                    _touch(row)
            return _snapshot(task)

    async def confirm_cancel(self, owner_id: str, task_id: str, *, execution_epoch: int) -> dict:
        """Record cancellation after the caller confirms all subtree runs stopped."""
        async with self._write() as session:
            task = await self._lock_tree(session, owner_id, task_id)
            if task.status not in (TaskStatus.CANCELLING, TaskStatus.CANCELLED) or task.execution_epoch != execution_epoch:
                raise TaskConflict("Cancellation no longer matches the task")
            rows = await self._subtree(session, task)
            await self._confirm_stopped(session, rows)
            for row in rows:
                if row.status == TaskStatus.CANCELLING:
                    row.status = TaskStatus.CANCELLED
                    _touch(row)
            return _snapshot(task)

    async def _confirm_stopped(self, session, rows):
        """Close active execution records in the same transaction as their tasks."""
        from sqlalchemy import update

        from deerflow.persistence.coordination.model import CoordinationExecutionRow

        ids = [row.id for row in rows if row.status == TaskStatus.CANCELLING]
        if ids:
            await session.execute(update(CoordinationExecutionRow).where(CoordinationExecutionRow.task_id.in_(ids), CoordinationExecutionRow.status.in_(("admitting", "running", "waiting_for_input"))).values(status="cancelled"))

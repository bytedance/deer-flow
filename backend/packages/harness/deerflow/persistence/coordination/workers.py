"""Durable admission, cancellation and result ownership for managed workers."""

from uuid import uuid4

from sqlalchemy import select

from deerflow.persistence.coordination.model import CoordinationArtifactRow as Artifact
from deerflow.persistence.coordination.model import CoordinationAssignmentRow as Assignment
from deerflow.persistence.coordination.model import CoordinationExecutionRow as Execution
from deerflow.persistence.coordination.model import CoordinationInputRow, CoordinationTaskRow, TaskStatus
from deerflow.persistence.coordination.sql import CoordinationTaskRepository, TaskConflict, TaskNotFound

THREAD_PREFIX = "coord-worker-"
RUN_KEY_PREFIX = "coord-execution:"
INPUT_SOURCES = {"input": "task_api", "chat": "worker_chat", "run-input": "run_input"}


async def bind_admitted_worker(session, thread_id, owner_id, key, run_id):
    """Called inside native SQL run admission, under the same tree lock as cancellation."""
    from deerflow.runtime.runs.manager import ConflictError

    worker = await session.scalar(select(Assignment).where(Assignment.thread_id == thread_id))
    if worker is None:
        return  # A pre-existing user-chosen thread ID may share the prefix.
    task_id = worker.task_id
    root_id = await session.scalar(select(CoordinationTaskRow.root_id).filter_by(id=task_id))
    await session.execute(select(CoordinationTaskRow.id).filter_by(id=root_id).with_for_update())
    task = await session.get(CoordinationTaskRow, task_id)
    execution = await session.get(Execution, key[len(RUN_KEY_PREFIX) :]) if key and key.startswith(RUN_KEY_PREFIX) else None
    if (
        worker.epoch != task.execution_epoch
        or task.owner_id != owner_id
        or task.status != TaskStatus.RUNNING
        or execution is None
        or execution.task_id != task_id
        or execution.epoch != task.execution_epoch
        or execution.status != "admitting"
    ):
        raise ConflictError("Managed worker admission no longer matches the task")
    execution.run_id = run_id
    execution.status = "running"


class CoordinationWorkerRepository(CoordinationTaskRepository):
    async def task_for_thread(self, thread_id):
        async with self._sessions() as session:
            return await session.scalar(select(Assignment.task_id).filter_by(thread_id=thread_id))

    @staticmethod
    def _latest(task_id):
        return select(Execution).filter_by(task_id=task_id).order_by(Execution.turn.desc()).limit(1)

    @staticmethod
    async def _artifact_refs(session, task_id, *, execution_id=None, limit=None, offset=0):
        query = (
            select(Artifact.id, Artifact.path, Artifact.sha256, Artifact.size, Execution.run_id, Execution.turn)
            .join(Execution, Execution.id == Artifact.execution_id)
            .where(Execution.task_id == task_id)
            .order_by(Execution.turn, Artifact.path, Artifact.id)
        )
        if execution_id is not None:
            query = query.where(Execution.id == execution_id)
        rows = await session.execute(query.limit(limit).offset(offset))
        return [
            {
                "id": row.id,
                "source_path": row.path,
                "sha256": row.sha256,
                "size": row.size,
                "run_id": row.run_id,
                "turn": row.turn,
                "url": f"/api/coordination/tasks/{task_id}/artifacts/{row.id}",
            }
            for row in rows
        ]

    async def view(self, owner, task_id):
        async with self._sessions() as session:
            task = await self._lookup(session, owner, task_id)
            assignment = await session.scalar(select(Assignment).filter_by(task_id=task_id).order_by(Assignment.epoch.desc()).limit(1))
            execution = await session.scalar(self._latest(task_id))
            result = None
            if execution is not None:
                result = execution.to_dict(exclude={"frozen_input", "resume_key"})
                result["artifacts"] = await self._artifact_refs(session, task_id, execution_id=execution.id)
            return {
                "task": task.to_dict(),
                "assignment": assignment.to_dict() if assignment else None,
                "execution": result,
            }

    async def admission(self, owner, task_id, execution_id):
        async with self._sessions() as session:
            task = await self._lookup(session, owner, task_id)
            execution = await session.get(Execution, execution_id)
            if execution is None or execution.task_id != task_id or execution.epoch != task.execution_epoch or task.status != TaskStatus.RUNNING:
                raise TaskConflict("Task no longer accepts this execution")
            worker = await session.get(Assignment, (task_id, execution.epoch))
            return worker.to_dict(), execution.frozen_input, task.project_id

    async def list_artifacts(self, owner, task_id, *, limit, offset):
        async with self._sessions() as session:
            await self._lookup(session, owner, task_id)
            return await self._artifact_refs(session, task_id, limit=limit, offset=offset)

    async def read_artifact(self, owner, task_id, artifact_id):
        async with self._sessions() as session:
            query = select(Artifact).join(Execution, Execution.id == Artifact.execution_id).join(CoordinationTaskRow, CoordinationTaskRow.id == Execution.task_id)
            artifact = await session.scalar(query.where(Artifact.id == artifact_id, Execution.task_id == task_id, CoordinationTaskRow.owner_id == owner))
            if artifact is None:
                raise TaskNotFound(artifact_id)
            return artifact.path, artifact.content

    async def prepare(self, owner, task_id, assistant_id=None):
        """Freeze a bounded turn before admission. Duplicate drivers get the same turn."""
        async with self._write() as session:
            task = await self._lock_tree(session, owner, task_id)
            worker = await session.get(Assignment, (task_id, task.execution_epoch))
            if worker is not None and assistant_id is not None and worker.assistant_id != assistant_id:
                raise TaskConflict("Task already has a different worker")
            if task.status == TaskStatus.QUEUED:
                await self._start_locked(session, task)
            if task.status != TaskStatus.RUNNING:
                return None
            if worker is None:
                if assistant_id is None:
                    raise TaskConflict("Task has no assigned worker")
                worker = Assignment(task_id=task_id, epoch=task.execution_epoch, assistant_id=assistant_id, thread_id=THREAD_PREFIX + uuid4().hex)
                session.add(worker)
                await session.flush()
            execution = await session.scalar(self._latest(task_id))
            if execution is None or (execution.status == "superseded" and execution.covered_seq < task.latest_input_seq):
                previous = execution.covered_seq if execution else 0
                if execution is None:
                    messages = [{"role": "user", "content": task.objective}]
                elif execution.run_id is None:
                    messages = list(execution.frozen_input.get("messages", []))
                else:
                    messages = []
                inputs = await session.scalars(select(CoordinationInputRow).filter_by(task_id=task_id).where(CoordinationInputRow.sequence > previous).order_by(CoordinationInputRow.sequence).limit(8))
                for item in inputs:
                    messages.append({"role": "user", "content": item.content})
                    previous = item.sequence
                execution = Execution(
                    id=uuid4().hex,
                    task_id=task_id,
                    turn=execution.turn + 1 if execution else 1,
                    epoch=task.execution_epoch,
                    covered_seq=previous,
                    frozen_input={"messages": messages},
                    status="admitting",
                )
                session.add(execution)
            return worker.to_dict(), execution.to_dict(), task.project_id

    async def resume(self, owner, task_id, *, key, value):
        async with self._write() as session:
            task = await self._lock_tree(session, owner, task_id)
            payload = {"command": {"resume": value}}
            execution = await session.scalar(select(Execution).filter_by(task_id=task_id, resume_key=key))
            if execution is not None:
                if execution.frozen_input != payload:
                    raise TaskConflict("Request ID was already used with a different response")
            else:
                if task.status != TaskStatus.RUNNING:
                    raise TaskConflict("Task is closed")
                previous = await session.scalar(self._latest(task_id))
                if previous is None or previous.status != "waiting_for_input":
                    raise TaskConflict("Worker has no pending interrupt")
                execution = Execution(
                    id=uuid4().hex,
                    task_id=task_id,
                    turn=previous.turn + 1,
                    epoch=task.execution_epoch,
                    covered_seq=previous.covered_seq,
                    frozen_input=payload,
                    status="admitting",
                    resume_key=key,
                )
                session.add(execution)
            worker = await session.get(Assignment, (task_id, execution.epoch))
            return worker.to_dict(), execution.to_dict(), task.project_id

    async def settle(self, owner, task_id, execution_id, run_id, status, artifacts):
        async with self._write() as session:
            task = await self._lock_tree(session, owner, task_id)
            execution = await session.get(Execution, execution_id)
            if execution is None or execution.task_id != task_id or execution.run_id != run_id or execution.status not in ("running", "admitting"):
                return
            if task.status != TaskStatus.RUNNING or task.execution_epoch != execution.epoch:
                return
            for path, digest, content in artifacts:
                session.add(Artifact(id=uuid4().hex, execution_id=execution.id, path=path, sha256=digest, size=len(content), content=content))
            if status == "waiting_for_input":
                execution.status = status
                return
            if execution.covered_seq < task.latest_input_seq:
                execution.status = "superseded"
                return
            worker = await session.get(Assignment, (task_id, task.execution_epoch))
            result_ref = f"/api/threads/{worker.thread_id}/runs/{run_id}/messages" if run_id else None
            outcome = TaskStatus.SUCCEEDED if status == "success" else TaskStatus.FAILED
            await self._finish_locked(session, task, outcome, result_ref or f"/api/coordination/tasks/{task_id}")
            execution.status = status

    @staticmethod
    def _admitted_run(task_id, sequence):
        return select(Execution.run_id).where(Execution.task_id == task_id, Execution.covered_seq >= sequence, Execution.run_id.is_not(None)).order_by(Execution.turn).limit(1)

    async def list_worker_inputs(self, owner, task_id, *, after, limit):
        async with self._sessions() as session:
            task = await self._lookup(session, owner, task_id)
            admitted = self._admitted_run(task_id, CoordinationInputRow.sequence).scalar_subquery()
            query = select(CoordinationInputRow, admitted).where(CoordinationInputRow.task_id == task_id, CoordinationInputRow.sequence > after).order_by(CoordinationInputRow.sequence).limit(limit)
            return [
                {
                    "sequence": row.sequence,
                    "content": row.content,
                    "created_at": row.created_at,
                    "source": INPUT_SOURCES.get(row.request_id.partition(":")[0], "unknown"),
                    "status": "admitted" if run_id else "pending" if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING) else "not_admitted",
                    "run_id": run_id,
                }
                for row, run_id in (await session.execute(query)).all()
            ]

    async def input_receipts(self, owner, task_id):
        async with self._sessions() as session:
            task = await self._lookup(session, owner, task_id)
            consuming = self._admitted_run(task_id, CoordinationInputRow.sequence).scalar_subquery()
            query = select(CoordinationInputRow, consuming).filter(CoordinationInputRow.task_id == task_id, CoordinationInputRow.request_id.startswith("run-input:")).order_by(CoordinationInputRow.sequence.desc()).limit(32)
            results = [(row.to_dict(), run) for row, run in (await session.execute(query)).all() if row.request_id.count(":") >= 2]
            execution = await session.scalar(self._latest(task_id))
            active = execution.run_id if task.status == TaskStatus.RUNNING and execution and execution.status == "running" else None
            return list(reversed(results)), active, task.status in (TaskStatus.CANCELLING, TaskStatus.CANCELLED)

    async def run_for_input(self, owner, task_id, sequence):
        async with self._sessions() as session:
            task = await self._lookup(session, owner, task_id)
            run_id = await session.scalar(self._admitted_run(task_id, sequence))
            if run_id is None and task.status not in (TaskStatus.RUNNING, TaskStatus.QUEUED):
                raise TaskConflict("Task stopped before this input could run")
            return run_id

    async def cancellations(self, owner, task_id):
        async with self._write() as session:
            task = await self._lock_tree(session, owner, task_id)
            ids = [row.id for row in await self._subtree(session, task) if row.status == TaskStatus.CANCELLING]
            rows = await session.execute(
                select(Assignment.thread_id, Execution.run_id)
                .join(Execution, (Assignment.task_id == Execution.task_id) & (Assignment.epoch == Execution.epoch))
                .where(Assignment.task_id.in_(ids), Execution.run_id.is_not(None), Execution.status == "running")
            )
            return list(rows)

    async def active_batches(self, owner, task_id):
        from deerflow.persistence.subagent_batches.model import SubagentBatchRow

        async with self._write() as session:
            task = await self._lock_tree(session, owner, task_id)
            ids = [row.id for row in await self._subtree(session, task) if row.status == TaskStatus.CANCELLING]
            threads = select(Assignment.thread_id).where(Assignment.task_id.in_(ids))
            query = select(SubagentBatchRow.thread_id, SubagentBatchRow.id).where(SubagentBatchRow.user_id == owner, SubagentBatchRow.thread_id.in_(threads), SubagentBatchRow.status.in_(("queued", "running", "paused")))
            return (await session.execute(query)).all()

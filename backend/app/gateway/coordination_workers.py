"""Gateway execution of durable coordination tasks using caller-bound AgentRuns."""

import asyncio
import logging
from hashlib import sha256
from uuid import uuid4

from deerflow_extension_api.agent_runs import AgentRunError
from fastapi import HTTPException

from app.gateway.deps import get_agent_runs
from deerflow.persistence.coordination.model import TaskStatus
from deerflow.persistence.coordination.sql import TaskConflict, TaskNotFound
from deerflow.persistence.coordination.workers import THREAD_PREFIX

logger = logging.getLogger(__name__)
CANCEL_RESPONSE_TIMEOUT = 5


class CoordinationWorkers:
    def __init__(self, repository):
        self.repo = repository
        self._drivers = {}
        self._wakeups = set()
        self._cancellations = {}

    async def close(self):
        jobs = [*self._drivers.values(), *self._cancellations.values()]
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    async def dispatch(self, runs, owner, task_id, assistant_id):
        turn = await self.repo.prepare(owner, task_id, assistant_id)
        if turn is not None:
            await self._admit(runs, owner, task_id, turn)
            self.watch(runs, owner, task_id)
        return await self.repo.view(owner, task_id)

    async def _admit(self, runs, owner, task_id, turn):
        worker, execution, project = turn
        thread = worker["thread_id"]
        if execution["run_id"] is None:
            try:
                await runs.create_thread(thread_id=thread, assistant_id=worker["assistant_id"], project_id=project)
                admitted = await runs.start_coordination_worker(task_id=task_id, execution_id=execution["id"])
                return admitted.run_id
            except AgentRunError as exc:
                if exc.status_code in (400, 403, 404, 422):
                    await self.repo.settle(owner, task_id, execution["id"], None, "admission_failed", [])
                raise
        return execution["run_id"]

    def watch(self, runs, owner, task_id):
        key = (owner, task_id)
        if (existing := self._drivers.get(key)) is not None and not existing.done():
            self._wakeups.add(key)
            return existing

        async def drive():
            delay = 1
            while True:
                self._wakeups.discard(key)
                try:
                    await self._drive(runs, owner, task_id)
                except AgentRunError as exc:
                    if exc.status_code < 500:
                        raise
                    await asyncio.sleep(delay)
                    delay = min(30, delay * 2)
                    continue
                if key not in self._wakeups:
                    return

        task = asyncio.create_task(drive())
        self._drivers[key] = task

        def finished(job):
            if self._drivers.get(key) is job:
                self._drivers.pop(key)
                self._wakeups.discard(key)
            if not job.cancelled() and (error := job.exception()) is not None:
                logger.warning("Coordination worker observation stopped for task %s (%s)", task_id, type(error).__name__)

        task.add_done_callback(finished)
        return task

    async def _drive(self, runs, owner, task_id):
        while (turn := await self.repo.prepare(owner, task_id)) is not None:
            worker, execution, _project = turn
            if execution["status"] == "waiting_for_input":
                return
            if execution["run_id"] is None:
                await self._admit(runs, owner, task_id, turn)
                continue
            thread = worker["thread_id"]
            try:
                run = await runs.wait_coordination_worker(thread_id=thread, run_id=execution["run_id"], timeout=60)
            except TimeoutError:
                continue
            artifacts = []
            status = run.status
            if status == "success" and not run.stop_reason:
                try:
                    artifacts = await runs.coordination_artifacts(thread_id=thread, run_id=run.run_id)
                except AgentRunError as exc:
                    if exc.status_code >= 500:
                        raise
                    status = "delivery_failed"
            elif status == "success":
                status = "stopped"
            await self.repo.settle(owner, task_id, execution["id"], run.run_id, status, artifacts)

    async def cancel(self, runs, owner, task_id, revision):
        task = await self.repo.request_cancel(owner, task_id, expected_revision=revision)
        if task["status"] == TaskStatus.CANCELLED:
            return task
        key = (owner, task_id)
        job = self._cancellations.get(key)
        if job is None or job.done():
            job = asyncio.create_task(self._finish_cancellation(runs, owner, task_id, task["execution_epoch"]))
            self._cancellations[key] = job

            def finished(completed):
                if self._cancellations.get(key) is completed:
                    self._cancellations.pop(key)
                if not completed.cancelled() and (error := completed.exception()) is not None:
                    logger.warning("Coordination cancellation stopped for task %s (%s)", task_id, type(error).__name__)

            job.add_done_callback(finished)
        # asyncio.wait leaves the tracked job running after the response deadline.
        done, _ = await asyncio.wait({job}, timeout=CANCEL_RESPONSE_TIMEOUT)
        return job.result() if done else task

    async def _finish_cancellation(self, runs, owner, task_id, epoch):
        delay = 1
        while True:
            try:
                await self._stop_subtree(runs, owner, task_id)
                return await self.repo.confirm_cancel(owner, task_id, execution_epoch=epoch)
            except AgentRunError as exc:
                if exc.status_code < 500:
                    raise
                await asyncio.sleep(delay)
                delay = min(30, delay * 2)

    async def _stop_subtree(self, runs, owner, task_id):
        active = await self.repo.cancellations(owner, task_id)
        for thread, run_id in active:
            run = await runs.get(thread_id=thread, run_id=run_id)
            if run.status in ("pending", "running"):
                try:
                    await runs.cancel(thread_id=thread, run_id=run_id)
                except AgentRunError as exc:
                    if exc.status_code != 409 or (await runs.get(thread_id=thread, run_id=run_id)).status in ("pending", "running"):
                        raise
        for thread, run_id in active:
            while True:
                try:
                    await runs.wait_coordination_worker(thread_id=thread, run_id=run_id, timeout=60)
                    break
                except TimeoutError:
                    continue
        for batch in await self.repo.active_batches(owner, task_id):
            await runs.cancel_worker_batch(thread_id=batch.thread_id, batch_id=batch.id)


def worker_context(request):
    service = getattr(request.app.state, "coordination_workers", None)
    if service is None:
        raise HTTPException(503, "Coordination workers require SQL persistence")
    runs = get_agent_runs(request)
    if runs is None:
        raise HTTPException(403, "Coordination workers require a user session")
    return service, str(request.state.user.id), runs.for_plugin("native-coordination")


def worker_error(exc):
    if isinstance(exc, TaskNotFound):
        return HTTPException(404, "Task not found")
    if isinstance(exc, AgentRunError):
        return HTTPException(exc.status_code, str(exc) if exc.status_code < 500 else "Worker host unavailable")
    return HTTPException(409, str(exc))


async def managed_task(request, thread_id):
    if not thread_id.startswith(THREAD_PREFIX):
        return None
    service = getattr(request.app.state, "coordination_workers", None)
    return await service.repo.task_for_thread(thread_id) if service is not None else None


async def direct_worker_run(request, task_id, body, key):
    from app.gateway.deps import get_run_manager

    service, owner, runs = worker_context(request)
    if getattr(request.state, "run_origin", None) or body.checkpoint or body.checkpoint_id or body.conversation_references or body.multitask_strategy != "reject":
        raise HTTPException(409, "Use a task input to continue this managed worker")
    try:
        if body.command is not None:
            if set(body.command) != {"resume"} or body.command["resume"] is None or body.input:
                raise HTTPException(422, "An explicit interrupt response is required")
            view = await service.repo.view(owner, task_id)
            current = view["execution"]
            if current and current["status"] == "running" and current["run_id"]:
                native = await runs.get(thread_id=view["assignment"]["thread_id"], run_id=current["run_id"])
                if native.status == "waiting_for_input":
                    await service.repo.settle(owner, task_id, current["id"], native.run_id, native.status, [])
            turn = await service.repo.resume(owner, task_id, key=key or uuid4().hex, value=body.command["resume"])
            run_id = await service._admit(runs, owner, task_id, turn)
            service.watch(runs, owner, task_id)
        else:
            messages = (body.input or {}).get("messages")
            if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
                raise HTTPException(422, "Managed workers accept one text message")
            message = messages[0]
            content = message.get("content")
            if isinstance(content, list) and all(isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) for part in content):
                content = "".join(part["text"] for part in content)
            if message.get("role", message.get("type")) not in ("user", "human") or not isinstance(content, str) or not 0 < len(content.strip()) <= 16384:
                raise HTTPException(422, "Managed workers accept one text message")
            identifier = key or message.get("id") or uuid4().hex
            if not isinstance(identifier, str):
                raise HTTPException(422, "Message ID must be a string")
            row = await service.repo.append_input(owner, task_id, request_id="chat:" + sha256(identifier.encode()).hexdigest(), content=content)
            driver = service.watch(runs, owner, task_id)
            # Streaming and wait endpoints must observe the Run that consumed this input.
            while not (run_id := await service.repo.run_for_input(owner, task_id, row["sequence"])):
                if driver.done():
                    driver.result()
                    raise HTTPException(409, "Input queued; the worker is waiting for an explicit interrupt response")
                await asyncio.sleep(0.25)
        record = await get_run_manager(request).get(run_id, user_id=owner)
        if record is None:
            raise HTTPException(503, "Worker run is unavailable")
        return record
    except (TaskNotFound, TaskConflict, AgentRunError) as exc:
        raise worker_error(exc) from exc

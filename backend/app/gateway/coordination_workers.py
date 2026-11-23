"""Gateway execution of durable coordination tasks using caller-bound AgentRuns."""

import asyncio
import logging
from hashlib import sha256
from time import time
from uuid import uuid4

from deerflow_extension_api.agent_runs import AgentRunError
from fastapi import HTTPException

from app.gateway.deps import get_agent_runs
from deerflow.persistence.coordination.model import TaskStatus
from deerflow.persistence.coordination.sql import TaskConflict, TaskNotFound
from deerflow.persistence.coordination.workers import THREAD_PREFIX, WORKER_CHECKPOINT_RUN, WORKER_SHUTDOWN
from deerflow.runtime.runs.manager import LEASE_ORPHAN_RECOVERY_ERROR, ORPHAN_RECOVERY_STOP_REASON, STARTUP_ORPHAN_RECOVERY_ERROR

logger = logging.getLogger(__name__)
CANCEL_RESPONSE_TIMEOUT = 5
RECOVERY_INTERVAL = 10
GRANT_LIFETIME = 24 * 60 * 60
WORKER_RUN_PERMISSIONS = frozenset({"runs:create", "runs:read", "threads:read", "threads:write"})
WORKER_CANCEL_PERMISSIONS = frozenset({"runs:read", "runs:cancel"})
WORKER_PERMISSIONS = WORKER_RUN_PERMISSIONS | WORKER_CANCEL_PERMISSIONS


class CoordinationWorkers:
    def __init__(self, repository, host, connections=None):
        self.repo = repository
        self._host = host
        self._connections = connections
        self._drivers = {}
        self._wakeups = set()
        self._cancellations = {}
        self._recovery = None

    def start_recovery(self):
        self._recovery = asyncio.create_task(self._recover())

    async def close(self):
        jobs = [*self._drivers.values(), *self._cancellations.values()]
        if self._recovery is not None:
            jobs.append(self._recovery)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    @staticmethod
    def _new_grant(authority, *, channel=None):
        if authority is None:
            raise AgentRunError(403, "A task requires restorable run authorization")
        return {
            "id": uuid4().hex,
            "authority": {**authority, "permissions": sorted(WORKER_PERMISSIONS.intersection(authority["permissions"]))},
            "channel": channel,
            "expires_at": time() + GRANT_LIFETIME,
        }

    async def dispatch(self, runs, owner, task_id, assistant_id, *, channel=None):
        grant = self._new_grant(runs.capture_authority(), channel=channel)
        turn = await self.repo.prepare(owner, task_id, assistant_id, initial_grant=grant)
        if turn is not None:
            authorized, grant_id = await self.authority(owner, task_id)
            await self._admit(authorized, owner, task_id, turn, grant_id)
            self.watch(authorized, owner, task_id, grant_id)
        return await self.view(owner, task_id)

    async def dispatch_bound_channel(self, message, *, request_id, objective, assistant_id="lead_agent"):
        """Entry point for a Gateway-side adapter after provider authentication."""
        from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
        from app.gateway.authz import resolve_route_permissions

        if self._connections is None or self._host.load_user is None or not message.connection_id or not message.owner_user_id or not message.user_id:
            raise AgentRunError(403, "A bound messaging identity is required")
        connection = await self._connections.find_connection_by_external_identity(
            provider=message.channel_name,
            external_account_id=message.user_id,
            workspace_id=message.workspace_id or None,
        )
        owner = message.owner_user_id
        if connection is None or connection["id"] != message.connection_id or connection["owner_user_id"] != owner:
            raise AgentRunError(403, "The messaging identity is no longer bound")
        user = await self._host.load_user(owner)
        if user is None or user.disabled or user.needs_setup:
            raise AgentRunError(403, "The task owner is unavailable")
        permissions = WORKER_PERMISSIONS.intersection(await resolve_route_permissions(user, is_internal=False))
        if "runs:create" not in permissions:
            raise AgentRunError(403, "Permission denied: runs:create")
        snapshot = {"token_version": user.token_version, "source": AUTH_SOURCE_SESSION, "permissions": sorted(permissions)}
        runs = await self._host.restore_delegated_authority(user_id=owner, grant=snapshot)
        request_key = sha256(f"{connection['id']}:{request_id}".encode()).hexdigest()
        task = await self.repo.create(owner, request_id=f"im:{request_key}", objective=objective)
        return await self.dispatch(runs, owner, task["id"], assistant_id, channel={"id": connection["id"], "updated_at": connection["updated_at"]})

    async def authority(self, owner, task_id, *, cancelling=False):
        grant = await self.repo.grant(owner, task_id)
        if grant is None:
            raise AgentRunError(403, "Task requires authorization")

        async def validate():
            current = await self.repo.grant(owner, task_id)
            if current is None or current["id"] != grant["id"]:
                raise AgentRunError(403, "Task authorization was revoked")

        runs = await self._host.restore_delegated_authority(
            user_id=owner,
            grant=grant["authority"],
            validator=validate,
            plugin_namespace="native-coordination",
            required_permissions=WORKER_CANCEL_PERMISSIONS if cancelling else WORKER_RUN_PERMISSIONS,
        )
        return runs, grant["id"]

    async def authorize(self, runs, owner, task_id):
        await self.repo.set_grant(owner, task_id, self._new_grant(runs.capture_authority()))
        return await self.view(owner, task_id)

    async def submit_input(self, owner, task_id, *, request_id, content):
        receipt = await self.repo.replay_input(owner, task_id, request_id=request_id, content=content)
        if receipt is not None:
            return receipt
        runs, grant_id = await self.authority(owner, task_id)
        receipt = await self.repo.append_input(owner, task_id, request_id=request_id, content=content)
        self.watch(runs, owner, task_id, grant_id)
        return receipt

    async def view(self, owner, task_id):
        view = await self.repo.view(owner, task_id)
        required = False
        status = view["task"]["status"]
        if status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCELLING):
            try:
                await self.authority(owner, task_id, cancelling=status == TaskStatus.CANCELLING)
            except AgentRunError as exc:
                if exc.status_code != 403:
                    raise
                required = True
        return {**view, "authorization_required": required}

    async def recover_once(self):
        after = ""
        while page := await self.repo.recovery_page(after):
            for task_id, owner, status, epoch in page:
                key = (owner, task_id)
                jobs = self._cancellations if status == TaskStatus.CANCELLING else self._drivers
                if (job := jobs.get(key)) is not None and not job.done():
                    continue
                try:
                    runs, grant_id = await self.authority(owner, task_id, cancelling=status == TaskStatus.CANCELLING)
                except AgentRunError as exc:
                    if exc.status_code != 403:
                        raise
                    continue
                if status == TaskStatus.CANCELLING:
                    self._cancel_job(runs, owner, task_id, epoch)
                else:
                    self.watch(runs, owner, task_id, grant_id)
            after = page[-1][0]

    async def _recover(self):
        while True:
            try:
                await self.recover_once()
            except Exception:
                logger.exception("Coordination recovery scan failed")
            await asyncio.sleep(RECOVERY_INTERVAL)

    async def _admit(self, runs, owner, task_id, turn, grant_id):
        worker, execution, project = turn
        thread = worker["thread_id"]
        if execution["run_id"] is None:
            try:
                await runs.create_thread(thread_id=thread, assistant_id=worker["assistant_id"], project_id=project)
                admitted = await runs.start_coordination_worker(task_id=task_id, execution_id=execution["id"], grant_id=grant_id)
                return admitted.run_id
            except AgentRunError as exc:
                if exc.status_code in (400, 404, 422):
                    await self.repo.settle(owner, task_id, execution["id"], None, "admission_failed", [])
                raise
        return execution["run_id"]

    def watch(self, runs, owner, task_id, grant_id):
        key = (owner, task_id)
        if (existing := self._drivers.get(key)) is not None and not existing.done():
            self._wakeups.add(key)
            return existing

        async def drive():
            delay = 1
            while True:
                self._wakeups.discard(key)
                try:
                    await self._drive(runs, owner, task_id, grant_id)
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

    async def _drive(self, runs, owner, task_id, grant_id):
        while (turn := await self.repo.prepare(owner, task_id)) is not None:
            worker, execution, _project = turn
            if execution["status"] == "waiting_for_input":
                return
            if execution["run_id"] is None:
                await self._admit(runs, owner, task_id, turn, grant_id)
                continue
            thread = worker["thread_id"]
            try:
                run = await runs.wait_coordination_worker(thread_id=thread, run_id=execution["run_id"], timeout=60)
            except TimeoutError:
                continue
            artifacts = []
            status = run.status
            if run.stop_reason == WORKER_SHUTDOWN or (run.stop_reason == ORPHAN_RECOVERY_STOP_REASON and run.error in (STARTUP_ORPHAN_RECOVERY_ERROR, LEASE_ORPHAN_RECOVERY_ERROR)):
                state = await runs.coordination_recovery_checkpoint(thread_id=thread, run_id=run.run_id)
                if state and state.get("checkpoint_id") and state.get("metadata", {}).get(WORKER_CHECKPOINT_RUN) == run.run_id and state.get("next"):
                    if any(task.get("interrupts") for task in state.get("tasks", [])):
                        status = "waiting_for_input"
                    else:
                        await self.repo.recover_checkpoint(owner, task_id, execution["id"], run.run_id, state["checkpoint_id"])
                        continue
            elif status == "success" and not run.stop_reason:
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
        job = self._cancel_job(runs, owner, task_id, task["execution_epoch"])
        # asyncio.wait leaves the tracked job running after the response deadline.
        done, _ = await asyncio.wait({job}, timeout=CANCEL_RESPONSE_TIMEOUT)
        return job.result() if done else task

    def _cancel_job(self, runs, owner, task_id, epoch):
        key = (owner, task_id)
        job = self._cancellations.get(key)
        if job is None or job.done():
            job = asyncio.create_task(self._finish_cancellation(runs, owner, task_id, epoch))
            self._cancellations[key] = job

            def finished(completed):
                if self._cancellations.get(key) is completed:
                    self._cancellations.pop(key)
                if not completed.cancelled() and (error := completed.exception()) is not None:
                    logger.warning("Coordination cancellation stopped for task %s (%s)", task_id, type(error).__name__)

            job.add_done_callback(finished)
        return job

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

    service, owner, _runs = worker_context(request)
    if getattr(request.state, "run_origin", None) or body.checkpoint or body.checkpoint_id or body.conversation_references or body.multitask_strategy != "reject":
        raise HTTPException(409, "Use a task input to continue this managed worker")
    try:
        runs, grant_id = await service.authority(owner, task_id)
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
            run_id = await service._admit(runs, owner, task_id, turn, grant_id)
            service.watch(runs, owner, task_id, grant_id)
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
            driver = service.watch(runs, owner, task_id, grant_id)
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

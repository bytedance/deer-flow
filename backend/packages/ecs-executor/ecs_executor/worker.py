"""Single-host Docker worker. No distributed worker or node-transport claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextlib import nullcontext

from sqlalchemy.exc import SQLAlchemyError

from ecs_executor.files import collect, manifest, prepare
from ecs_executor.job_store import TERMINAL


class Docker:
    async def command(self, *args, timeout=15):
        process = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        return process.returncode, stdout, stderr

    async def checked(self, *args):
        code, stdout, _ = await self.command(*args)
        if code:
            raise RuntimeError("Docker command failed; physical outcome requires reconciliation")
        return stdout

    async def inspect(self, ref):
        code, stdout, stderr = await self.command("inspect", ref)
        if code:
            if b"no such object" in stderr.lower() or b"no such container" in stderr.lower():
                return None
            raise RuntimeError("Docker inspection unavailable")
        return json.loads(stdout)[0]


class LocalWorker:
    def __init__(self, jobs, *, docker=None, node_id=None):
        self.node_id = node_id
        self.jobs = jobs
        self.store = jobs.store
        self.docker = docker or Docker()
        self._lock = asyncio.Lock()

    async def tick(self):
        async with self._lock:
            await asyncio.to_thread(self.store.expire_staged)
            # Reconcile claimed work before accepting a new queued job.
            for job in await asyncio.to_thread(self.store.list_active):
                if job.get("state") in {"starting", "running", "uncertain"}:
                    try:
                        await self.reconcile(job)
                    except (RuntimeError, TimeoutError, OSError, SQLAlchemyError):
                        # Retry inspection/STOP; never issue another start.
                        continue
            for terminal in await asyncio.to_thread(self.store.list_cleanup_pending):
                try:
                    await self.cleanup(terminal)
                except (RuntimeError, TimeoutError, OSError, SQLAlchemyError):
                    # Result and durable pending flag survive cleanup failures.
                    continue
            try:
                claimer = getattr(self.jobs, "claim_queued", self.store.claim_queued)
                job = await asyncio.to_thread(claimer)
            except (RuntimeError, SQLAlchemyError):
                return
            if job:
                await self.launch(job)

    def _ref(self, job):
        return "deerflow-exec-" + job["id"]

    def _owned(self, job, observation):
        labels = observation["Config"].get("Labels") or {}
        if labels.get("deerflow.execution.job") != job["id"] or labels.get("deerflow.execution.spec") != job["spec_digest"] or (self.node_id and labels.get("deerflow.execution.node") != self.node_id):
            raise RuntimeError("Container ownership/integrity mismatch")

    async def cleanup(self, job):
        observation = await self.docker.inspect(self._ref(job))
        if observation is not None:
            self._owned(job, observation)
            if observation["State"]["Running"] or observation["State"]["Status"] not in {"exited", "dead"}:
                raise RuntimeError("Terminal cleanup requires confirmed physical STOP")
            await self.docker.checked("rm", self._ref(job))
            if await self.docker.inspect(self._ref(job)) is not None:
                raise RuntimeError("Terminal removal not confirmed")
        # A crash after removal merely re-observes absence on the next tick.
        await asyncio.to_thread(self.store.mutate, job["id"], lambda record: record.update(cleanup_pending=False, physical_stopped=True))

    def _authority(self, job):
        if job.get("workspace_id") is None and not getattr(self.jobs, "workspace_required", False):
            return nullcontext()
        resolver = getattr(self.jobs, "execution_authority", None)
        if resolver is None:
            raise PermissionError("Worker has no scoped execution authority")
        return resolver(job)

    def _authorize(self, job):
        with self._authority(job):
            pass

    def _fenced_change(self, job, change):
        with self._authority(job):
            return self.store.mutate(job["id"], change)

    async def _request_stop(self, job):
        def request(record):
            if record["state"] not in TERMINAL:
                record.update(cancel_requested=True, error="Execution authority withdrawn; physical STOP required")

        return await asyncio.to_thread(self.store.mutate, job["id"], request)

    async def launch(self, job):
        ref, profile = self._ref(job), job["profile"]
        try:
            job = await asyncio.to_thread(self.store.get, job["id"])
            await asyncio.to_thread(self._authorize, job)
            inputs, outputs = await asyncio.to_thread(prepare, self.jobs.artifact_root, job)
            await self.docker.checked(
                "create",
                "--pull=never",
                "--name",
                ref,
                "--label",
                "deerflow.execution.job=" + job["id"],
                "--label",
                "deerflow.execution.spec=" + job["spec_digest"],
                "--label",
                "deerflow.execution.node=" + (self.node_id or "local"),
                "--restart=no",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit",
                str(profile["pids_limit"]),
                "--network",
                profile["network"],
                "--user",
                profile["user"],
                "--cpus",
                str(profile["cpu_millis"] / 1000),
                "--memory",
                str(profile["memory_mib"]) + "m",
                "--log-driver=json-file",
                "--log-opt",
                "max-size=" + str(profile["max_output_bytes"]),
                "--log-opt",
                "max-file=1",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "--ulimit",
                "fsize=" + str(profile["max_output_bytes"]),
                "--mount",
                "type=bind,src=" + str(inputs) + ",dst=/inputs,readonly",
                "--mount",
                "type=bind,src=" + str(outputs) + ",dst=/output",
                "--workdir",
                "/output",
                "--entrypoint",
                "",
                profile["image"],
                *job["spec"]["argv"],
            )

            admitted = False

            def intent(record):
                nonlocal admitted
                admitted = record["state"] == "starting" and not record.get("cancel_requested") and not record.get("start_intent")
                if admitted:
                    record.update(start_intent=True, started_at=time.time())

            fresh = await asyncio.to_thread(self._fenced_change, job, intent)
            if not admitted:
                await self.reconcile(fresh)
                return
            await asyncio.to_thread(self._authorize, fresh)
            await self.docker.checked("start", ref)
            await self.reconcile(fresh)
        except PermissionError:
            await self.reconcile(await self._request_stop(job))
        except (RuntimeError, TimeoutError, OSError, SQLAlchemyError):

            def uncertain(record):
                if record["state"] not in TERMINAL:
                    record.update(state="uncertain", error="Docker admission/start outcome uncertain; inspection required, never replayed")

            await asyncio.to_thread(self.store.mutate, job["id"], uncertain)

    async def reconcile(self, job):
        job = await asyncio.to_thread(self.store.get, job["id"])
        observation = await self.docker.inspect(self._ref(job))
        if observation is not None:
            self._owned(job, observation)
        # Removing the exact managed object fences late start commands. A
        # cancellation is terminal only after that STOP/removal is observed.
        deadline = job.get("started_at", time.time()) + job["profile"]["max_execution_seconds"]
        if not job.get("cancel_requested") and deadline > time.time():
            try:
                await asyncio.to_thread(self._authorize, job)
            except PermissionError:
                job = await self._request_stop(job)
        if job.get("cancel_requested") or deadline <= time.time():
            if observation is not None:
                await self.docker.checked("rm", "-f", self._ref(job))
                if await self.docker.inspect(self._ref(job)) is not None:
                    raise RuntimeError("Physical STOP not yet confirmed")

            def stopped(record):
                if record["state"] not in TERMINAL:
                    record.update(physical_stopped=True, state="cancelled" if record.get("cancel_requested") else "failed", error="Execution cancelled" if record.get("cancel_requested") else "Execution deadline exceeded")

            await asyncio.to_thread(self.store.mutate, job["id"], stopped)
            return
        if observation is None or observation["State"]["Status"] == "created":

            def uncertain(record):
                if record["state"] not in TERMINAL:
                    record.update(state="uncertain", error="Unresolved container start; no automatic replay")

            await asyncio.to_thread(self.store.mutate, job["id"], uncertain)
            return
        if observation["State"]["Running"]:

            def running(record):
                if record["state"] not in TERMINAL:
                    record["state"] = "running"

            await asyncio.to_thread(self.store.mutate, job["id"], running)
            return
        if observation["State"]["Status"] not in {"exited", "dead"}:
            raise RuntimeError("Container is not confirmed terminal")
        stdout = await self.docker.checked("logs", self._ref(job))
        limit = job["profile"]["max_output_bytes"]
        overflow = len(stdout) > limit
        try:
            output_files = await asyncio.to_thread(collect, self.jobs.artifact_root / job["id"] / "outputs", limit=limit - min(len(stdout), limit))
        except ValueError:
            output_files = {}
            overflow = True
        payload = json.dumps({"files": manifest(output_files), "stdout": stdout[:limit].decode("utf-8", errors="replace"), "truncated": overflow, "exit_code": observation["State"]["ExitCode"]}, ensure_ascii=True).encode()
        await asyncio.to_thread(self._authorize, job)
        artifact = await asyncio.to_thread(self._publish, job["id"], payload)
        native_uri = None
        if self.jobs.publication and not overflow:
            try:
                native_uri = await asyncio.to_thread(self.jobs.publication.publish, job, payload, output_files)
            except (ValueError, OSError):

                def unpublished(record):
                    if record["state"] not in TERMINAL:
                        record.update(state="failed", error="Private result retained; native publication denied or failed", exit_code=observation["State"]["ExitCode"], artifact=artifact, cleanup_pending=True)

                await asyncio.to_thread(self._fenced_change, job, unpublished)
                return

        def complete(record):
            if record["state"] not in TERMINAL and not record.get("cancel_requested"):
                record.update(state="completed" if observation["State"]["ExitCode"] == 0 and not overflow else "failed", exit_code=observation["State"]["ExitCode"], artifact=artifact, cleanup_pending=True)
                if native_uri:
                    record["native_artifact_uri"] = native_uri
                if overflow:
                    record["error"] = "Execution output exceeds profile limit"

        await asyncio.to_thread(self._fenced_change, job, complete)

    def _publish(self, job_id: str, payload: bytes):
        root = self.jobs.artifact_root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = root / job_id
        directory.mkdir(mode=0o700, exist_ok=True)
        temporary = directory / "result.part"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / "result.json")
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)
        return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}

    async def run(self):
        while True:
            await self.tick()
            await asyncio.sleep(0.1)

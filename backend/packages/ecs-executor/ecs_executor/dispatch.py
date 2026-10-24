"""Outbound-only worker transport. The server never connects to a worker."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
from starlette.responses import JSONResponse
from starlette.routing import Route

from ecs_executor.schema import SCHEMA_REVISION
from ecs_executor.worker import LocalWorker

PROTOCOL = "ecs-executor-1"
WORKER_VERSION = "0.1.0"


def _b_control(job):
    """Safe fixed-node control scalars; no arguments, inputs or result data."""
    fields = ("id", "kind", "node_id", "worker_owner", "generation", "state", "attempt", "start_intent", "started_at", "cancel_requested", "physical_stopped", "physical_stopped_at", "lease_until", "cleanup_pending")
    return {key: job[key] for key in fields if key in job}


def _same_assignment(left, right):
    return all(left.get(key) == right.get(key) for key in ("id", "node_id", "worker_owner", "generation"))


def _control_change(job, changes):
    if not set(changes) <= {"state", "error", "cancel_requested", "physical_stopped", "physical_stopped_at", "cleanup_pending"}:
        return False
    if "cancel_requested" in changes and changes["cancel_requested"] is not True:
        return False
    if "physical_stopped" in changes and changes["physical_stopped"] is not True:
        return False
    target = changes.get("state", job["state"])
    if job["state"] in {"completed", "failed", "cancelled"}:
        return target == job["state"] and changes.get("cleanup_pending", False) is False
    return target in {"uncertain", "failed", "cancelled"} or (target == job["state"] and changes.get("cancel_requested") is True)


def install_dispatch(app, pool, credentials, artifact_root, *, jobs=None):
    import hmac

    if set(credentials) != set(pool.nodes) or any(not v for v in credentials.values()) or len(set(credentials.values())) != len(credentials):
        raise ValueError("Every fixed node requires a separate nonempty credential")
    if jobs is not None and jobs.workspace_required and jobs.store.engine.url != pool.store.engine.url:
        raise ValueError("Scoped B and native C require the same executor ledger")
    artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = artifact_root / "pool-mount-id"
    temporary = artifact_root / ("pool-mount-" + uuid.uuid4().hex)
    temporary.write_text(uuid.uuid4().hex, encoding="ascii")
    try:
        try:
            os.link(temporary, marker)
        except FileExistsError:
            pass
    finally:
        temporary.unlink()
    mount_id = marker.read_text(encoding="ascii")

    def business(job):
        if jobs is None or not jobs.workspace_required:
            raise PermissionError("Scoped B native authority is unavailable")
        return jobs.execution_authority(job)

    def live_assignment(job):
        lease = job.get("lease_until")
        if job.get("cancel_requested") or job.get("physical_stopped") is not False or job["state"] not in {"starting", "running", "uncertain"} or type(lease) not in (int, float) or not math.isfinite(lease) or lease <= time.time():
            raise PermissionError("Scoped B assignment is not live")

    def scoped_poll(node, owner, may_claim):
        owned, claim = [], None
        for version, candidate in pool.scoped_b_candidates(node):
            if candidate["state"] == "queued":
                if not may_claim or claim is not None:
                    continue
                try:
                    with business(candidate):
                        claimed = pool.claim_scoped_b(node, owner, expected=candidate, version=version)
                    if claimed is not None:
                        # The reservation is not a continuing business grant.
                        with business(claimed):
                            fresh = pool.store.get(claimed["id"])
                            if fresh != claimed:
                                raise RuntimeError("Scoped B claim changed")
                            live_assignment(fresh)
                        claim = fresh
                except PermissionError:
                    # An allocated object remains charged if revocation races
                    # signing/payload delivery. Recovery receives only control.
                    continue
                continue
            renewed = pool.renew_scoped_b(node, owner, expected=candidate, version=version)
            if renewed is None:
                continue
            payload = {**_b_control(renewed), "control_only": True}
            if candidate.get("worker_owner") == owner:
                try:
                    with business(renewed):
                        fresh = pool.store.get(renewed["id"])
                        if fresh != renewed:
                            raise RuntimeError("Scoped B owned snapshot changed")
                        live_assignment(fresh)
                    payload = fresh
                except PermissionError:
                    pass
            owned.append(payload)
        return owned, claim

    def scoped_report(node, owner, job, args):
        if args["expected"] != _b_control(job):
            raise RuntimeError("Scoped B control snapshot changed")
        changes = args["changes"]
        if _control_change(job, changes):
            return pool.report_scoped_b(node, owner, job["id"], job["generation"], changes, job)
        # Native workspace/actor/private-parent/task locks precede the short
        # pool CAS. Neither HTTP nor Docker executes while these locks are held.
        with business(job):
            live_assignment(job)
            return pool.report_scoped_b(node, owner, job["id"], job["generation"], changes, job)

    async def dispatch(request):
        try:
            node = request.path_params["node"]
            if node not in credentials or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + credentials[node]):
                return JSONResponse({"error": "Unauthorized worker"}, status_code=403)
            args = await request.json()
            if (
                args.get("schema_revision") != SCHEMA_REVISION
                or args.get("protocol") != PROTOCOL
                or args.get("worker_version") != pool.nodes[node].worker_version
                or args.get("mount_id") != mount_id
                or not isinstance(args.get("owner"), str)
                or not args["owner"]
            ):
                raise ValueError("Worker protocol or shared mount verification failed")
            operation = request.path_params["operation"]
            if operation == "poll":
                await asyncio.to_thread(pool.store.expire_staged)
                # Required-scope deployments never launch historical unscoped
                # work. The ordinary pool's NULL-only API remains unchanged.
                required = jobs is not None and jobs.workspace_required
                owned = [] if required else await asyncio.to_thread(pool.owned, node, args["owner"], kind="B")
                claim = None if required else await asyncio.to_thread(pool.claim, node, args["owner"], kind="B")
                scoped_owned, scoped_claim = await asyncio.to_thread(scoped_poll, node, args["owner"], claim is None) if required else ([], None)
                owned.extend(scoped_owned)
                if claim is None:
                    claim = scoped_claim
                return JSONResponse({"schema_revision": SCHEMA_REVISION, "owned": owned, "claim": claim})
            job = await asyncio.to_thread(pool.store.get, args["job_id"])
            if job.get("kind", "B") != "B" or job.get("node_id") != node or job.get("worker_owner") != args["owner"] or job.get("generation") != args.get("generation"):
                raise ValueError("Worker assignment fence mismatch")
            if job.get("workspace_id") is None and jobs is not None and jobs.workspace_required:
                # Historical NULL attribution cannot become business authority
                # merely because the deployment now requires workspace scope.
                if operation == "get":
                    return JSONResponse({**_b_control(job), "control_only": True})
                if operation == "report" and args["expected"] == _b_control(job) and _control_change(job, args["changes"]):
                    updated = await asyncio.to_thread(pool.report, node, args["owner"], job["id"], job["generation"], args["changes"], job)
                    return JSONResponse({**_b_control(updated), "control_only": True})
                raise PermissionError("Unscoped B cannot acquire workspace business authority")
            if job.get("workspace_id") is not None:
                if operation == "get":
                    return JSONResponse({**_b_control(job), "control_only": True})
                if operation == "authorize":

                    def authorize():
                        with business(job):
                            live_assignment(job)
                            current = pool.store.get(job["id"])
                            if current != job:
                                raise RuntimeError("Scoped B authorization snapshot changed")

                    await asyncio.to_thread(authorize)
                    return JSONResponse(_b_control(job))
                if operation == "report":
                    updated = await asyncio.to_thread(scoped_report, node, args["owner"], job, args)
                    return JSONResponse({**_b_control(updated), "control_only": True})
                raise ValueError("Unknown scoped B operation")
            if operation == "get":
                return JSONResponse(job)
            if operation == "report":
                return JSONResponse(await asyncio.to_thread(pool.report, node, args["owner"], args["job_id"], args["generation"], args["changes"], args["expected"]))
            raise ValueError("Unknown worker operation")
        except (ValueError, PermissionError):
            return JSONResponse({"error": "Worker request denied"}, status_code=403)
        except RuntimeError:
            return JSONResponse({"error": "Worker snapshot changed"}, status_code=409)

    app.router.routes.insert(0, Route("/workers/{node}/{operation}", dispatch, methods=["POST"]))


class OutboundStore:
    """The Docker engine receives a store interface, never control DB access."""

    def __init__(self, *, url, node_id, credential, artifact_root):
        self.url, self.node_id = url.rstrip("/"), node_id
        self.owner = uuid.uuid4().hex
        self.mount_id = (Path(artifact_root) / "pool-mount-id").read_text(encoding="ascii")
        self.client = httpx.Client(headers={"Authorization": "Bearer " + credential}, timeout=30)
        self.records, self.claimed = {}, None

    def request(self, operation, **args):
        response = self.client.post(f"{self.url}/workers/{self.node_id}/{operation}", json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": self.mount_id, "owner": self.owner, **args})
        if response.status_code == 403 and operation == "authorize":
            raise PermissionError("Original scoped B execution authority withdrawn")
        if response.status_code == 409:
            raise RuntimeError("Worker snapshot changed; retry")
        if response.status_code != 200:
            raise RuntimeError("Outbound worker request denied or unavailable")
        payload = response.json()
        if operation == "poll" and payload.get("schema_revision") != SCHEMA_REVISION:
            raise RuntimeError("Executor schema capability mismatch")
        return payload

    def expire_staged(self):
        response = self.request("poll")
        previous = self.records
        self.records = {}
        for job in response["owned"]:
            self.records[job["id"]] = self._merge_control(previous.get(job["id"]), job)
        self.claimed = response["claim"]
        if self.claimed:
            self.records[self.claimed["id"]] = self.claimed

    @staticmethod
    def _merge_control(previous, response):
        if not response.get("control_only"):
            return response
        control = {key: value for key, value in response.items() if key != "control_only"}
        if previous is not None and "spec" in previous and _same_assignment(previous, response):
            return {**previous, **control}
        # A restart has no business payload to replay. The server keeps its
        # reservation; only a known exact local assignment can inspect/STOP it.
        return {**control, "control_only": True}

    @contextmanager
    def execution_authority(self, job):
        # A fresh RPC checks canonical native SQL and current pool lease. The
        # response is an observation only; no SQL lock crosses this context.
        self.request("authorize", job_id=job["id"], generation=job["generation"])
        yield

    def list_active(self):
        return [j for j in self.records.values() if "spec" in j and j["state"] not in {"completed", "failed", "cancelled"} and (not self.claimed or j["id"] != self.claimed["id"])]

    def list_cleanup_pending(self):
        return [j for j in self.records.values() if "spec" in j and j.get("cleanup_pending")]

    def claim_queued(self):
        job, self.claimed = self.claimed, None
        return job

    def get(self, job_id):
        job = self.request("get", job_id=job_id, generation=self.records[job_id]["generation"])
        job = self._merge_control(self.records[job_id], job)
        self.records[job_id] = job
        return job

    def mutate(self, job_id, change):
        for _ in range(20):
            original = self.get(job_id)
            updated = json.loads(json.dumps(original))
            change(updated)
            changes = {k: v for k, v in updated.items() if original.get(k) != v}
            try:
                job = self.request("report", job_id=job_id, generation=original["generation"], changes=changes, expected=_b_control(original) if original.get("workspace_id") is not None else original)
            except RuntimeError:
                continue
            # Keep only this exact known assignment's own freshly written
            # artifact metadata; the controller never resends hidden fields.
            job = self._merge_control(updated, job)
            self.records[job_id] = job
            return job
        raise RuntimeError("Worker report requires retry")


def main():
    """Worker config has fixed node identity/NAS roots, no job DB URL."""
    import fcntl

    from ecs_executor.publication import WorkspacePublication

    config = json.loads(Path(os.environ["ECS_WORKER_CONFIG"]).read_text(encoding="utf-8"))
    required = config.get("workspace_required", False)
    if type(required) is not bool:
        raise ValueError("Worker workspace mode must be boolean")
    server_name = config.get("native_server_name")
    if required and (not isinstance(server_name, str) or not server_name.strip() or len(server_name) > 128 or not config.get("workspace_root") or not (config.get("metadata_database_url") or config.get("metadata_database_url_env"))):
        raise ValueError("Scoped B worker requires fixed native publication configuration")
    root = Path(config["artifact_root"])
    # Fail closed if the NAS marker is missing; never mkdir a fallback mount.
    store = OutboundStore(url=config["executor_url"], node_id=config["node_id"], credential=os.environ[config["credential_env"]], artifact_root=root)
    publication = (
        WorkspacePublication(
            workspace_root=Path(config["workspace_root"]),
            metadata_database_url=os.environ[config["metadata_database_url_env"]] if "metadata_database_url_env" in config else config["metadata_database_url"],
            native_server_name=server_name if required else None,
        )
        if config.get("workspace_root")
        else None
    )
    if publication is not None:
        from ecs_executor.native_authority import NativeSubmissionAuthority

        NativeSubmissionAuthority(publication.engine).validate_mode(workspace_required=required)
    jobs = SimpleNamespace(store=store, artifact_root=root, publication=publication, workspace_required=required, execution_authority=store.execution_authority)
    with (root / ("node-" + config["node_id"] + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            asyncio.run(LocalWorker(jobs, node_id=config["node_id"]).run())
        finally:
            store.client.close()


if __name__ == "__main__":
    main()

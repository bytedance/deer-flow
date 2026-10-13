"""Outbound-only worker transport. The server never connects to a worker."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
from starlette.responses import JSONResponse
from starlette.routing import Route

from ecs_executor.schema import SCHEMA_REVISION
from ecs_executor.worker import LocalWorker

PROTOCOL = "ecs-executor-1"
WORKER_VERSION = "0.1.0"


def install_dispatch(app, pool, credentials, artifact_root):
    import hmac

    if set(credentials) != set(pool.nodes) or any(not v for v in credentials.values()) or len(set(credentials.values())) != len(credentials):
        raise ValueError("Every fixed node requires a separate nonempty credential")
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
                owned = await asyncio.to_thread(pool.owned, node, args["owner"], kind="B")
                claim = await asyncio.to_thread(pool.claim, node, args["owner"], kind="B")
                return JSONResponse({"schema_revision": SCHEMA_REVISION, "owned": owned, "claim": claim})
            job = await asyncio.to_thread(pool.store.get, args["job_id"])
            if job.get("node_id") != node or job.get("worker_owner") != args["owner"] or job.get("generation") != args.get("generation"):
                raise ValueError("Worker assignment fence mismatch")
            if operation == "get":
                return JSONResponse(job)
            if operation == "report":
                return JSONResponse(await asyncio.to_thread(pool.report, node, args["owner"], args["job_id"], args["generation"], args["changes"], args["expected"]))
            raise ValueError("Unknown worker operation")
        except ValueError:
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
        self.records = {j["id"]: j for j in response["owned"]}
        self.claimed = response["claim"]
        if self.claimed:
            self.records[self.claimed["id"]] = self.claimed

    def list_active(self):
        return [j for j in self.records.values() if j["state"] not in {"completed", "failed", "cancelled"} and (not self.claimed or j["id"] != self.claimed["id"])]

    def list_cleanup_pending(self):
        return [j for j in self.records.values() if j.get("cleanup_pending")]

    def claim_queued(self):
        job, self.claimed = self.claimed, None
        return job

    def get(self, job_id):
        job = self.request("get", job_id=job_id, generation=self.records[job_id]["generation"])
        self.records[job_id] = job
        return job

    def mutate(self, job_id, change):
        for _ in range(20):
            original = self.get(job_id)
            updated = json.loads(json.dumps(original))
            change(updated)
            changes = {k: v for k, v in updated.items() if original.get(k) != v}
            try:
                job = self.request("report", job_id=job_id, generation=original["generation"], changes=changes, expected=original)
            except RuntimeError:
                continue
            self.records[job_id] = job
            return job
        raise RuntimeError("Worker report requires retry")


def main():
    """Worker config has fixed node identity/NAS roots, no job DB URL."""
    import fcntl

    from ecs_executor.publication import WorkspacePublication

    config = json.loads(Path(os.environ["ECS_WORKER_CONFIG"]).read_text(encoding="utf-8"))
    root = Path(config["artifact_root"])
    # Fail closed if the NAS marker is missing; never mkdir a fallback mount.
    store = OutboundStore(url=config["executor_url"], node_id=config["node_id"], credential=os.environ[config["credential_env"]], artifact_root=root)
    publication = (
        WorkspacePublication(workspace_root=Path(config["workspace_root"]), metadata_database_url=os.environ[config["metadata_database_url_env"]] if "metadata_database_url_env" in config else config["metadata_database_url"])
        if config.get("workspace_root")
        else None
    )
    jobs = SimpleNamespace(store=store, artifact_root=root, publication=publication)
    with (root / ("node-" + config["node_id"] + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            asyncio.run(LocalWorker(jobs, node_id=config["node_id"]).run())
        finally:
            store.client.close()


if __name__ == "__main__":
    main()

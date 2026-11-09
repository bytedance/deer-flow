"""Task-bound declarations, immutable snapshots and version-specific handoffs."""

import asyncio
import base64
import hashlib
import json
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import PurePosixPath

from deerflow_extension_api import AgentRunError

from .shared_state import actor, fingerprint, text
from .store import TERMINAL

PUBLIC_FIELDS = ("id", "artifact_id", "version", "name", "filename", "path", "status", "sha256", "size", "source", "created_at", "error")
MAX_VERSIONS = 20
MAX_PER_JOB = 4
MAX_BYTES = 2 * 1024 * 1024
OWNER_BYTES = 64 * 1024 * 1024


def public(entry):
    return {key: entry[key] for key in PUBLIC_FIELDS}


def references(team, values):
    if not isinstance(values, list) or len(values) > MAX_PER_JOB:
        raise ValueError("Choose at most four artifact versions")
    result = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {"artifact_id", "version"} or type(value["version"]) is not int or value["version"] < 1:
            raise ValueError("Invalid artifact reference")
        ref = {"artifact_id": text(value, "artifact_id", 64), "version": value["version"]}
        lookup(team, ref)
        if ref not in result:
            result.append(ref)
    return sorted(result, key=lambda ref: (ref["artifact_id"], ref["version"]))


def lookup(team, ref):
    entry = next((entry for entry in team.get("artifacts", []) if entry["artifact_id"] == ref["artifact_id"] and entry["version"] == ref["version"]), None)
    if entry is None:
        raise ValueError("Artifact version unavailable")
    return entry


def pending(team, job):
    return any(entry["status"] == "pending" and {"artifact_id": entry["artifact_id"], "version": entry["version"]} in job.get("artifacts", []) for entry in team.get("artifacts", []))


def register(team, payload, context, executing_run_id=None, executing_job_id=None):
    required = {"team_id", "request_id", "name", "path"}
    if not required <= set(payload) or set(payload) - required - {"artifact_id"}:
        raise ValueError("Unexpected request fields")
    member_id, source = actor(team, context)
    request_id, name, path = (text(payload, key, limit) for key, limit in (("request_id", 128), ("name", 80), ("path", 500)))
    file = PurePosixPath(path)
    if not path.startswith("/mnt/user-data/outputs/") or str(file) != path or ".." in file.parts or "\\" in path or any(ord(c) < 32 for c in path) or len(file.name.encode()) > 120:
        raise ValueError("Use a regular output file path with a filename of at most 120 UTF-8 bytes")
    entries = team.setdefault("artifacts", [])
    version_id = fingerprint(team["id"], context.thread_id, request_id)
    stamp = fingerprint(name, path, payload.get("artifact_id"))
    existing = next((entry for entry in entries if entry["id"] == version_id), None)
    if existing:
        if existing["_request"] != stamp:
            raise ValueError("Request ID already used for another artifact")
        return {"artifact": public(existing)}
    job = next((job for job in team["jobs"] if job["id"] == executing_job_id and job["thread_id"] == context.thread_id), None) if executing_run_id else None
    if job is None or job["input"] is None or job["status"] in TERMINAL or job["status"] == "waiting_input" or executing_run_id != context.run_id:
        raise ValueError("Register files during an executing team task")
    source = {"thread_id": context.thread_id, "job_id": job["id"]}
    if len(entries) >= MAX_VERSIONS or sum(entry["source"]["job_id"] == job["id"] for entry in entries) >= MAX_PER_JOB:
        raise ValueError("Artifact version limit reached (20 per team, four per task)")
    artifact_id = text(payload, "artifact_id", 64) if "artifact_id" in payload else version_id
    prior = [entry for entry in entries if entry["artifact_id"] == artifact_id]
    if "artifact_id" in payload and not prior:
        raise ValueError("Artifact unavailable; omit artifact_id for a new artifact")
    entry = {
        "id": version_id,
        "artifact_id": artifact_id,
        "version": max((entry["version"] for entry in prior), default=0) + 1,
        "name": name,
        "filename": file.name,
        "path": path,
        "status": "pending",
        "sha256": None,
        "size": None,
        "source": {**source, "member_id": member_id, "run_id": executing_run_id},
        "created_at": datetime.now(UTC).isoformat(),
        "error": None,
        "_request": stamp,
    }
    entries.append(entry)
    return {"artifact": public(entry)}


# One bounded 2 MiB snapshot needs up to 43 chunks plus publication/cleanup,
# with a 30-second timeout per host command. Each file gets its own budget.
ARTIFACT_TRANSFER_SECONDS = 1500
worker_deadline: ContextVar[asyncio.Timeout | None] = ContextVar("team_worker_deadline", default=None)


async def transfer(call, **kwargs):
    deadline = worker_deadline.get()
    if deadline is None:
        return await call(**kwargs)
    loop = asyncio.get_running_loop()
    remaining = deadline.when() - loop.time()
    if remaining <= 0:
        raise TimeoutError
    deadline.reschedule(loop.time() + ARTIFACT_TRANSFER_SECONDS)
    try:
        return await call(**kwargs)
    finally:
        if not deadline.expired():
            deadline.reschedule(loop.time() + remaining)


class Artifacts:
    async def register_artifact(self, payload, context):
        team = await self.member_snapshot(payload, context)
        version_id = fingerprint(team["id"], context.thread_id, text(payload, "request_id", 128))
        existing = any(entry["id"] == version_id for entry in team.get("artifacts", []))
        run_id = getattr(context, "run_id", None)
        job = next((job for job in team["jobs"] if job["thread_id"] == context.thread_id and job["status"] not in TERMINAL), None)
        if not existing:
            if not run_id or context.agent_runs is None or job is None or job["input"] is None or job["status"] == "waiting_input":
                raise ValueError("Register files during an executing team task")
            key = job["resume"]["key"] if job.get("resume") and job["resume"].get("started", True) else job.get("execution_key") or job["id"]
            await context.agent_runs.validate_artifact_source(thread_id=context.thread_id, run_id=run_id, idempotency_key=key)
        return await self.db("change", context.principal.user_id, team["id"], lambda current: register(current, payload, context, run_id if not existing else None, job["id"] if job else None))

    async def list_artifacts(self, payload, context):
        team = await self.member_snapshot(payload, context)
        if set(payload) - {"team_id", "artifact_id", "job_id", "offset", "limit"}:
            raise ValueError("Unexpected request fields")
        offset, limit = payload.get("offset", 0), payload.get("limit", 8)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Invalid artifact page")
        filters = {key: text(payload, key, 64) for key in ("artifact_id", "job_id") if key in payload}
        entries = [public(entry) for entry in team.get("artifacts", []) if all((entry["artifact_id"] if key == "artifact_id" else entry["source"]["job_id"]) == value for key, value in filters.items())]
        result = {"team_id": team["id"], "artifacts": [], "next_offset": None}
        for entry in entries[offset : offset + limit]:
            result["artifacts"].append(entry)
            end = offset + len(result["artifacts"])
            result["next_offset"] = end if end < len(entries) else None
            if len(json.dumps(result, ensure_ascii=False).encode()) > 24000:
                result["artifacts"].pop()
                result["next_offset"] = end - 1
                break
        return result

    async def artifact_chunk(self, payload, context):
        if set(payload) - {"team_id", "artifact_id", "version", "offset"}:
            raise ValueError("Unexpected request fields")
        team_id = text(payload, "team_id", 64)
        version = payload.get("version")
        offset = payload.get("offset", 0)
        if type(version) is not int or version < 1 or type(offset) is not int or offset < 0:
            raise ValueError("Invalid artifact version or offset")
        entry, content = await self.db("artifact", context.principal.user_id, team_id, text(payload, "artifact_id", 64), version)
        if offset > len(content):
            raise ValueError("Offset exceeds artifact size")
        end = min(offset + 12288, len(content))
        result = {"artifact": public(entry), "offset": offset, "next_offset": end if end < len(content) else None, "content_base64": base64.b64encode(content[offset:end]).decode("ascii")}
        if len(json.dumps(result, ensure_ascii=False).encode()) > 24000:
            raise ValueError("Artifact response exceeds the response budget")
        return result

    async def read_artifact(self, payload, context):
        await self.member_snapshot(payload, context)
        return await self.artifact_chunk(payload, context)

    async def get_artifact(self, payload, context):
        return await self.artifact_chunk(payload, context)

    async def capture_artifacts(self, owner, team_id, job, status):
        team = await self.db("get", owner, team_id)
        for entry in team.get("artifacts", []):
            if entry["source"]["job_id"] != job["id"] or entry["status"] != "pending":
                continue
            error = "Producing task did not complete" if status != "completed" else None
            if error is None:
                try:
                    checkpoint_id = job.get("capture_checkpoint_id")
                    if not checkpoint_id:
                        raise ValueError("Producing checkpoint unavailable")
                    content = await transfer(self.handles[owner, team_id].read_artifact, thread_id=job["thread_id"], path=entry["path"], expected_checkpoint_id=checkpoint_id)
                    await self.db("capture_artifact", owner, team_id, entry["id"], content, job["run_id"])
                    continue
                except AgentRunError as exc:
                    if exc.status_code in (403, 409, 503):
                        raise
                    error = "Output file unavailable or unsafe"
                except ValueError as exc:
                    error = str(exc)

            def fail(current, entry_id=entry["id"], message=error):
                saved = next(item for item in current["artifacts"] if item["id"] == entry_id)
                if saved["status"] == "pending":
                    saved.update(status="failed", error=message)

            await self.db("change", owner, team_id, fail)

    async def prepare_artifacts(self, owner, team, job, runs):
        imports = []
        for ref in job.get("artifacts", []):
            entry, content = await self.db("artifact", owner, team["id"], ref["artifact_id"], ref["version"])
            result = await transfer(runs.import_artifact, thread_id=job["thread_id"], filename=job["id"][:12] + "-" + entry["filename"], content=content)
            if result.get("sha256") != hashlib.sha256(content).hexdigest() or result.get("size") != len(content) or not result.get("path", "").startswith("/mnt/user-data/uploads/"):
                raise ValueError("Host did not confirm the imported artifact")
            imports.append({**ref, **result, "name": entry["name"], "source": entry["source"]})
        return imports

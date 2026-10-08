"""Owner-bound ordinary MCP commands over the independent execution ledger."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ecs_executor.files import decode_inputs
from ecs_executor.job_store import TERMINAL, JobStore
from ecs_executor.scope import arguments_sha256, verify_execution_scope, verify_management_scope


class ExecutionProfile(BaseModel):
    """Operator-defined authority; request arguments cannot override it."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    image: str = Field(min_length=1, max_length=255)
    cpu_millis: int = Field(default=500, ge=100, le=64000)
    memory_mib: int = Field(default=128, ge=32, le=65536)
    network: str = "none"
    user: str = "65534:65534"
    pids_limit: int = Field(default=64, ge=1, le=1024)
    max_output_bytes: int = Field(default=1048576, ge=1024, le=16777216)
    max_execution_seconds: int = Field(default=60, ge=1, le=3600)


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.-]+$")
    profile: str = Field(min_length=1, max_length=64)
    argv: list[str] = Field(min_length=1, max_length=128)
    input_files: dict[str, str] = Field(default_factory=dict)
    input_refs: dict[str, dict[str, str]] = Field(default_factory=dict)


class ExecutionJobs:
    def __init__(
        self,
        store: JobStore,
        *,
        secret: bytes,
        audience: str,
        profiles: dict[str, ExecutionProfile],
        user_profiles: dict[str, set[str]],
        artifact_root: Path,
        staged_ttl_seconds: int = 300,
        allowed_networks: set[str] | None = None,
        workspace_root: Path | None = None,
        metadata_database_url: str | None = None,
        max_input_bytes: int = 8 * 1024 * 1024,
    ):
        if len(secret) < 32 or not audience or not 1 <= staged_ttl_seconds <= 3600:
            raise ValueError("Invalid executor configuration")
        if not 131072 <= max_input_bytes <= 64 * 1024 * 1024:
            raise ValueError("Input budget must be between 128 KiB and 64 MiB")
        self.max_input_bytes = max_input_bytes
        networks = {"none"} if allowed_networks is None else allowed_networks
        for profile in profiles.values():
            if profile.network not in networks or profile.network in {"host", "default"} or re.fullmatch(r"[a-zA-Z0-9_.-]+", profile.network) is None:
                raise ValueError("Execution network must be explicitly operator-authorized")
            if re.fullmatch(r"[1-9][0-9]*(?::[0-9]+)?", profile.user) is None:
                raise ValueError("Execution profiles require a numeric non-root user")
        if bool(workspace_root) != bool(metadata_database_url):
            raise ValueError("Native file publication requires both fixed shared workspace and metadata database")
        from ecs_executor.publication import WorkspacePublication

        self.publication = WorkspacePublication(workspace_root=workspace_root, metadata_database_url=metadata_database_url) if workspace_root else None
        self.store, self.secret, self.audience = store, secret, audience
        self.profiles, self.user_profiles = profiles, user_profiles
        self.artifact_root = Path(artifact_root)
        self.staged_ttl_seconds = staged_ttl_seconds

    def verify(self, user_id, token, operation, args):
        return verify_execution_scope(token, secret=self.secret, authenticated_user_id=user_id, arguments=args, expected_audience=self.audience, expected_operation=operation)

    def submit(self, user_id, token, args):
        claims = self.verify(user_id, token, "submit", args)
        spec = ExecutionSpec.model_validate(args)
        if spec.profile not in self.user_profiles.get(user_id, set()) or spec.profile not in self.profiles:
            raise ValueError("Execution profile is not authorized")
        if len(set(spec.input_files) | set(spec.input_refs)) > 64:
            raise ValueError("Combined input count exceeds 64 files")
        inline = decode_inputs(spec.input_files)
        if spec.input_refs and (self.publication is None or set(spec.input_refs) & set(spec.input_files)):
            raise ValueError("Native input references require shared workspace and distinct input names")
        if any(not value or "\0" in value for value in spec.argv):
            raise ValueError("Invalid execution argv")
        # A retry in the same trusted run/request namespace returns the same
        # handle. A new run gets a new handle, avoiding native remote-ID aliasing.
        identity = {key: claims[key] for key in ("user_id", "thread_id", "incarnation", "run_id")}
        namespace = arguments_sha256(identity)
        previous = self.store.find_request(namespace=namespace, request_key=spec.request_key, spec_digest=arguments_sha256(args))
        if previous:
            return {"task_id": previous["id"], "status": "running"}
        if spec.input_refs:
            snapshots = self.publication.snapshot(identity, spec.input_refs, limit=self.max_input_bytes - sum(map(len, inline.values())))
            spec.input_files.update({name: base64.b64encode(payload).decode("ascii") for name, payload in snapshots.items()})
        job = self.store.create(
            namespace=namespace,
            request_key=spec.request_key,
            spec_digest=arguments_sha256(args),
            record={**identity, "spec": spec.model_dump(), "profile": self.profiles[spec.profile].model_dump(), "staged_deadline": time.time() + self.staged_ttl_seconds, "max_input_bytes": self.max_input_bytes},
        )
        return {"task_id": job["id"], "status": "running"}

    def _authorize(self, user_id, token, operation, args):
        claims = verify_management_scope(token, secret=self.secret, authenticated_user_id=user_id, arguments=args, expected_audience=self.audience, expected_operation=operation)
        if set(args) != {"task_id"} or not isinstance(args["task_id"], str):
            raise ValueError("Invalid task arguments")
        job = self.store.get(args["task_id"])
        if job["user_id"] != claims["user_id"]:
            raise ValueError("Execution owner/scope mismatch")
        return job

    def status(self, user_id, token, args):
        job = self._authorize(user_id, token, "status", args)

        def activate(record):
            if record["state"] == "staged":
                if record["staged_deadline"] <= time.time():
                    record.update(state="failed", error="Submission staging expired")
                else:
                    record["state"] = "queued"

        return self.snapshot(self.store.mutate(job["id"], activate))

    def cancel(self, user_id, token, args):
        job = self._authorize(user_id, token, "cancel", args)

        def cancel(record):
            if record["state"] in ("staged", "queued"):
                record["state"] = "cancelled"
            elif record["state"] not in TERMINAL:
                record["cancel_requested"] = True

        job = self.store.mutate(job["id"], cancel)
        if job["state"] not in TERMINAL:
            raise RuntimeError("Physical cancellation pending; retry until worker confirms STOP")
        return self.snapshot(job)

    def snapshot(self, job):
        result = {"task_id": job["id"], "status": job["state"] if job["state"] in TERMINAL else "running"}
        if "error" in job:
            result["error"] = job["error"][:4000]
        if "artifact" in job:
            result["result_artifact"] = {"uri": job.get("native_artifact_uri", "/artifacts/" + job["id"]), "mime_type": "application/json"}
            result["result"] = {"sha256": job["artifact"]["sha256"], "bytes": job["artifact"]["bytes"], "exit_code": job["exit_code"]}
        if result["status"] == "running":
            result["poll_after_seconds"] = 0.25
        return result

    def read_artifact(self, user_id, job_id):
        job = self.store.get(job_id)
        if job["user_id"] != user_id or "artifact" not in job:
            raise ValueError("Artifact not found")
        payload = (self.artifact_root / job_id / "result.json").read_bytes()
        if len(payload) != job["artifact"]["bytes"] or hashlib.sha256(payload).hexdigest() != job["artifact"]["sha256"]:
            raise RuntimeError("Artifact integrity verification failed")
        return json.loads(payload)

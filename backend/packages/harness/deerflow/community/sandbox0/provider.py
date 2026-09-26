"""Persistent, single-Gateway Sandbox0 workspaces backed by the official SDK."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from functools import partial
from pathlib import Path

from deerflow.config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.acquire_serialization import AcquireSerializer
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox import _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider

from .sandbox import Sandbox0Sandbox


def _new_client(**kwargs):
    try:
        from sandbox0 import Client
    except ImportError as exc:
        raise ImportError("Install Sandbox0 support with pip install 'deerflow-harness[sandbox0]'") from exc
    return Client(**kwargs)


class Sandbox0Provider(SandboxProvider):
    """Keep thread identity across turns/restarts; pause commits the writable RootFS.

    The registry stores identity and lifecycle intent, never credentials or guest data. One
    Gateway owns a registry at a time; an OS lock rejects concurrent workers.
    Distributed lifecycle ownership is intentionally not inferred from local IDs.
    """

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = False
    supports_agent_skill_isolation = True

    def __init__(self):
        app = get_app_config()
        config = app.sandbox
        self._api_key = getattr(config, "api_key", None) or os.environ.get("SANDBOX0_API_KEY")
        if self._api_key and self._api_key.startswith("$"):
            self._api_key = os.environ.get(self._api_key[1:])
        if not self._api_key:
            raise ValueError("SANDBOX0_API_KEY or sandbox.api_key is required")
        self._base_url = (getattr(config, "base_url", None) or os.environ.get("SANDBOX0_BASE_URL") or "https://api.sandbox0.ai").rstrip("/")
        self._template = getattr(config, "template", None) or "default"
        self._timeout = float(getattr(config, "request_timeout", 660))
        self._lifecycle_timeout = float(getattr(config, "lifecycle_timeout", 120))
        self._command_timeout = config.bash_command_timeout
        self._ttl = int(getattr(config, "ttl", 3600))
        self._hard_ttl = int(getattr(config, "hard_ttl", 604800))
        self._replicas = config.replicas or 10
        if not all(math.isfinite(v) and v > 0 for v in (self._timeout, self._lifecycle_timeout, self._ttl, self._hard_ttl)):
            raise ValueError("Sandbox0 timeouts and TTLs must be positive")
        if self._timeout <= self._command_timeout or self._ttl <= self._command_timeout:
            raise ValueError("request_timeout and ttl must exceed bash_command_timeout")
        if self._hard_ttl <= self._ttl:
            raise ValueError("hard_ttl must exceed ttl")
        if app.skills.container_path != DEFAULT_SKILLS_CONTAINER_PATH:
            raise ValueError("Sandbox0 currently requires skills.container_path=/mnt/skills")
        if config.ownership is not None and config.ownership.type != "memory":
            raise ValueError("Sandbox0 currently supports one Gateway process per state directory")
        if config.mounts or config.thread_data_mounts:
            raise ValueError("Sandbox0 does not support host bind mounts")
        if config.network.mode != "open":
            raise ValueError("Sandbox0 network policies must be configured on the Sandbox0 template")
        self._environment = {k: os.environ.get(v[1:], "") if v.startswith("$") else v for k, v in config.environment.items()}
        _validate_extra_env(self._environment)
        namespace = hashlib.sha256(f"{self._base_url}\0{self._template}".encode()).hexdigest()[:16]
        self._state_dir = Path(getattr(config, "state_dir", None) or get_paths().base_dir / "sandbox0") / namespace
        self._lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._serializer: AcquireSerializer[str] = AcquireSerializer(thread_name_prefix="sandbox0-lifecycle")
        self._client = None
        self._registry_lock = None
        self._sandboxes: dict[str, Sandbox0Sandbox] = {}
        self._owners: dict[str, tuple[str, str]] = {}
        # Keep retry handles separate from readiness: a timed-out mutation can
        # still commit remotely after its caller stops waiting.
        self._pending_actions: dict[str, str] = {}
        self._closed = False

    def _initialize(self):
        # Lazy I/O keeps provider construction safe on the Gateway event loop.
        with self._lock:
            if self._closed:
                raise RuntimeError("Sandbox0 provider is shut down")
            if self._client is None:
                from filelock import FileLock, Timeout

                self._state_dir.mkdir(parents=True, exist_ok=True)
                registry_lock = FileLock(self._state_dir / "provider.lock", thread_local=False)
                try:
                    registry_lock.acquire(timeout=0)
                except Timeout as exc:
                    raise RuntimeError("Sandbox0 registry is already owned by another Gateway; use a single worker") from exc
                try:
                    self._client = _new_client(token=self._api_key, base_url=self._base_url, timeout=self._timeout)
                except BaseException:
                    registry_lock.release()
                    raise
                self._registry_lock = registry_lock
            return self._client

    def _binding_path(self, sandbox_id: str) -> Path:
        if len(sandbox_id) != 16 or any(c not in "0123456789abcdef" for c in sandbox_id):
            raise ValueError("invalid Sandbox0 provider ID")
        return self._state_dir / f"{sandbox_id}.json"

    def _save_binding(self, sandbox_id: str, remote_id: str, user_id: str, thread_id: str):
        self._write_binding(sandbox_id, {"version": 1, "remote_id": remote_id, "user_id": user_id, "thread_id": thread_id})

    def _read_binding(self, sandbox_id: str) -> dict:
        binding = json.loads(self._binding_path(sandbox_id).read_text(encoding="utf-8"))
        if binding.get("version") != 1 or binding.get("pending_action") not in (None, "pause", "delete"):
            raise RuntimeError("Invalid Sandbox0 registry lifecycle state")
        return binding

    def _sync_state_dir(self):
        # File fsync alone does not persist the rename/unlink across a crash.
        # Windows does not support opening a directory with os.open().
        if os.name != "nt":
            descriptor = os.open(self._state_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _write_binding(self, sandbox_id: str, binding: dict):
        path = self._binding_path(sandbox_id)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(binding, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_state_dir()
        finally:
            temporary.unlink(missing_ok=True)

    def _set_pending_action(self, sandbox_id: str, action: str | None):
        """Write intent before remote mutation; clear it only after completion."""
        if action is not None:
            with self._lock:
                self._pending_actions[sandbox_id] = action
        binding = self._read_binding(sandbox_id)
        if action is None:
            binding.pop("pending_action", None)
        else:
            binding["pending_action"] = action
        self._write_binding(sandbox_id, binding)

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        from sandbox0.apispec.models.sandbox_config import SandboxConfig

        user = user_id or get_effective_user_id()
        thread = thread_id or str(uuid.uuid4())
        sid = derive_sandbox_scope_token(user_id=user, thread_id=thread)
        with self._lifecycle:
            client = self._initialize()
            with self._lock:
                pending = self._pending_actions.get(sid)
            if pending == "delete":
                raise RuntimeError("Sandbox0 workspace deletion is pending; retry destroy()")
            if pending == "pause":
                # Finish the previous pause before resuming. Otherwise a late
                # checkpoint could stop the runtime handed to the next turn.
                self.release(sid)
            with self._lock:
                if sid in self._sandboxes:
                    return sid
                if len(self._sandboxes) >= self._replicas:
                    raise RuntimeError("Sandbox0 active sandbox capacity reached")
                # Reserve before remote I/O so parallel claims cannot bypass capacity.
                self._sandboxes[sid] = None
            try:
                path = self._binding_path(sid)
                if path.exists():
                    binding = self._read_binding(sid)
                    if (binding.get("user_id"), binding.get("thread_id")) != (user, thread):
                        raise RuntimeError("Sandbox0 registry identity mismatch")
                    remote_id = binding["remote_id"]
                    pending = binding.get("pending_action")
                    if pending is not None:
                        with self._lock:
                            self._pending_actions[sid] = pending
                        if pending == "delete":
                            raise RuntimeError("Sandbox0 workspace deletion is pending; retry destroy()")
                        self._reconcile_pause(remote_id)
                        self._set_pending_action(sid, None)
                    # Missing/expired identity must be surfaced, never silently replace
                    # a persistent workspace with a new empty sandbox.
                    state = client.sandboxes.get(remote_id)
                    if str(state.status) == "pausing":
                        client.sandboxes.wait_for_lifecycle(remote_id, lambda s: str(s.status) == "paused", timeout_sec=self._lifecycle_timeout)
                        state = client.sandboxes.get(remote_id)
                    if state.paused or str(state.status) == "paused":
                        self._await_lifecycle(remote_id, "resume", lambda s: str(s.status) == "running" and not s.paused and s.runtime_generation > state.runtime_generation)
                    elif str(state.status) != "running":
                        raise RuntimeError(f"Sandbox0 workspace is not ready: {state.status}")
                    remote = client.sandbox(remote_id)
                    client.sandboxes.refresh(remote_id)
                else:
                    remote = client.sandboxes.claim(self._template, config=SandboxConfig(ttl=self._ttl, hard_ttl=self._hard_ttl, auto_resume=False))
                    try:
                        self._save_binding(sid, remote.id, user, thread)
                    except BaseException:
                        # A failed directory sync may leave the new binding
                        # visible. Fence cleanup before deleting that identity.
                        if path.exists():
                            self._set_pending_action(sid, "delete")
                        self._delete_remote(remote.id)
                        raise
                sandbox = Sandbox0Sandbox(sid, remote, command_timeout=self._command_timeout, environment=self._environment, refresh=partial(client.sandboxes.refresh, remote.id), refresh_interval=min(60, self._ttl / 3))
                self._bootstrap(sandbox)
                self._sync_skills(sandbox, user, thread)
                self._sync_inputs(sandbox, user, thread)
                with self._lock:
                    self._sandboxes[sid] = sandbox
                    self._owners[sid] = (user, thread)
                    self._pending_actions.pop(sid, None)
                return sid
            except BaseException:
                with self._lock:
                    self._sandboxes.pop(sid, None)
                # A committed binding remains recoverable after bootstrap/transport
                # failure. The server soft TTL bounds orphaned running compute.
                raise

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return await self._serializer.run_on_executor(partial(self.acquire, thread_id, user_id=user_id))

    def _bootstrap(self, sandbox: Sandbox0Sandbox):
        sandbox._checked(
            "command -v python3 && command -v bash && command -v find && command -v grep && command -v base64 && test -x /usr/bin/stat && test -x /usr/bin/realpath && mkdir -p /mnt/user-data/{workspace,uploads,outputs} /mnt/acp-workspace",
            timeout=30,
        )

    def _sync_skills(self, sandbox: Sandbox0Sandbox, user_id: str, thread_id: str):
        from deerflow.skills.projection import ensure_skill_projections, get_thread_skill_projection_paths
        from deerflow.skills.storage import get_or_new_user_skill_storage

        from .transfer import upload_skills

        storage = get_or_new_user_skill_storage(user_id, app_config=get_app_config())
        if get_paths().thread_skills_view_dir(thread_id, user_id=user_id).exists():
            projection = get_thread_skill_projection_paths(storage, thread_id)
        else:
            projection = ensure_skill_projections(storage)
        upload_skills(sandbox, projection)

    def _sync_inputs(self, sandbox: Sandbox0Sandbox, user_id: str, thread_id: str):
        from .transfer import upload_inputs

        paths = get_paths()
        upload_inputs(sandbox, paths.sandbox_uploads_dir(thread_id, user_id=user_id), "/mnt/user-data/uploads")
        upload_inputs(sandbox, paths.acp_workspace_dir(thread_id, user_id=user_id), "/mnt/acp-workspace")

    def sync_agent_skills(self, sandbox_id: str, *, thread_id: str, user_id: str, projection):
        from .transfer import upload_skills

        with self._lifecycle:
            with self._lock:
                sandbox = self.get(sandbox_id)
                owner = self._owners.get(sandbox_id)
            if sandbox is None or owner != (user_id, thread_id):
                raise RuntimeError("Sandbox0 skill synchronization requires the exact active owner")
            upload_skills(sandbox, projection)

    def get(self, sandbox_id: str) -> Sandbox0Sandbox | None:
        with self._lock:
            if self._closed or sandbox_id in self._pending_actions:
                return None
            return self._sandboxes.get(sandbox_id)

    def _sync_artifacts(self, sandbox: Sandbox0Sandbox, user_id: str, thread_id: str):
        from .transfer import download_artifacts

        download_artifacts(sandbox, get_paths().sandbox_user_data_dir(thread_id, user_id=user_id))

    def release(self, sandbox_id: str) -> None:
        with self._lifecycle:
            with self._lock:
                sandbox = self._sandboxes.get(sandbox_id)
                owner = self._owners.get(sandbox_id)
                pending = self._pending_actions.get(sandbox_id)
                if pending == "delete":
                    raise RuntimeError("Sandbox0 workspace deletion is pending; retry destroy()")
                if sandbox is not None:
                    self._pending_actions[sandbox_id] = "pause"
            if sandbox is None:
                return
            sync_error = None
            if pending != "pause":
                try:
                    self._sync_artifacts(sandbox, *owner)
                except Exception as exc:
                    sync_error = exc

            # The durable marker also fences a replacement Gateway if the
            # process exits before the remote mutation has completed.
            self._set_pending_action(sandbox_id, "pause")
            if pending == "pause":
                self._reconcile_pause(sandbox.remote_id)
            else:
                self._await_lifecycle(sandbox.remote_id, "pause", lambda s: str(s.status) == "paused" and s.paused)
            self._set_pending_action(sandbox_id, None)
            with self._lock:
                self._sandboxes.pop(sandbox_id, None)
                self._owners.pop(sandbox_id, None)
                self._pending_actions.pop(sandbox_id, None)
            if sync_error is not None:
                raise sync_error

    def _reconcile_pause(self, remote_id: str):
        """Finish an uncertain pause, even if the remote still reports running."""

        def paused(state):
            return str(state.status) == "paused" and state.paused

        state = self._client.sandboxes.get(remote_id)
        if paused(state):
            return
        if str(state.status) == "pausing":
            self._client.sandboxes.wait_for_lifecycle(remote_id, paused, timeout_sec=self._lifecycle_timeout)
        elif str(state.status) == "running":
            self._await_lifecycle(remote_id, "pause", paused)
        else:
            raise RuntimeError(f"Sandbox0 pending pause cannot be reconciled: {state.status}")

    def _await_lifecycle(self, remote_id, action, predicate):
        # SDK 0.10.2 parses synchronous responses only. Newer Nomad services
        # accept lifecycle mutations with 202; acceptance is not completion.
        try:
            return getattr(self._client.sandboxes, f"{action}_and_wait")(remote_id, timeout_sec=self._lifecycle_timeout)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 202:
                raise
        return self._client.sandboxes.wait_for_lifecycle(remote_id, predicate, timeout_sec=self._lifecycle_timeout)

    def _delete_remote(self, remote_id):
        try:
            self._client.sandboxes.delete(remote_id)
            return
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return
            if getattr(exc, "status_code", None) != 202:
                raise
        deadline = time.monotonic() + self._lifecycle_timeout
        while True:
            try:
                self._client.sandboxes.get(remote_id)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 404:
                    return
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Sandbox0 deletion has not completed; binding retained for retry")
            time.sleep(min(0.5, remaining))

    def destroy(self, sandbox_id: str) -> None:
        """Explicitly delete this provider's workspace and its saved binding."""
        with self._lifecycle:
            self._initialize()
            path = self._binding_path(sandbox_id)
            if path.exists():
                remote_id = self._read_binding(sandbox_id)["remote_id"]
                self._set_pending_action(sandbox_id, "delete")
                self._delete_remote(remote_id)
                path.unlink()
            self._sync_state_dir()
            with self._lock:
                self._sandboxes.pop(sandbox_id, None)
                self._owners.pop(sandbox_id, None)
                self._pending_actions.pop(sandbox_id, None)

    def reset(self):
        self.shutdown()

    def shutdown(self):
        with self._lifecycle:
            self._shutdown_locked()

    def _shutdown_locked(self):
        """Checkpoint active workspaces; retain bindings for the next Gateway."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            ids = list(self._sandboxes)
        try:
            errors = []
            for sid in ids:
                try:
                    self.release(sid)
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise ExceptionGroup("Sandbox0 shutdown could not checkpoint every workspace", errors)
        finally:
            self._serializer.close()
            if self._client is not None:
                self._client.close()
            if self._registry_lock is not None:
                self._registry_lock.release()

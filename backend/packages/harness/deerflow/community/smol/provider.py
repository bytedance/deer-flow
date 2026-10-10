"""Smol Machines provider: one VM per DeerFlow user/thread scope."""

from __future__ import annotations

import atexit
import logging
import threading
import time
import uuid
from functools import partial
from typing import Any

from deerflow.config import get_app_config
from deerflow.sandbox.acquire_serialization import AcquireSerializer
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider

from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .sandbox import SmolSandbox

logger = logging.getLogger(__name__)


def _import_smol():
    try:
        from smol import ConnectOptions, Machine, MachineConfig, ResourceSpec
    except ImportError as exc:
        raise ImportError("SmolSandboxProvider requires 'smolmachines'. Install it with pip install 'deerflow-harness[smol]'.") from exc
    return ConnectOptions, Machine, MachineConfig, ResourceSpec


class SmolSandboxProvider(WarmPoolLifecycleMixin[SmolSandbox], SandboxProvider):
    """Reclaim warm VMs only for the user/thread that created them."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    _idle_checker_thread_name = "smol-idle-reaper"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, SmolSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[SmolSandbox, float]] = {}
        self._acquire_serializer: AcquireSerializer[str] = AcquireSerializer(thread_name_prefix="smol-acquire-wait")
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._shutdown_called = False
        cfg = get_app_config().sandbox
        target = getattr(cfg, "target", None) or "local"
        if target not in ("local", "cloud"):
            raise ValueError("sandbox.target must be 'local' or 'cloud'")
        # DeerFlow's dynamic network approval requires the AIO proxy. Do not
        # silently accept an allowlist that this provider cannot enforce.
        if cfg.network.mode != "open":
            raise ValueError("SmolSandboxProvider currently supports sandbox.network.mode: open only")
        _validate_extra_env(cfg.environment)
        ttl_seconds = getattr(cfg, "ttl_seconds", None)
        if ttl_seconds is not None and (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0):
            raise ValueError("sandbox.ttl_seconds must be a positive integer")
        self._config: dict[str, Any] = {
            "target": target,
            "api_key": getattr(cfg, "api_key", None),
            "image": cfg.image or "python:3.12-slim",
            "cpus": getattr(cfg, "cpus", None),
            "memory_mb": getattr(cfg, "memory_mb", None),
            "replicas": cfg.replicas if cfg.replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": cfg.idle_timeout if cfg.idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
            "environment": cfg.environment,
            "ttl_seconds": ttl_seconds if ttl_seconds is not None else 24 * 60 * 60,
            "bash_command_timeout": cfg.bash_command_timeout,
        }
        atexit.register(self.shutdown)
        self._start_idle_checker()

    @staticmethod
    def _sandbox_id(thread_id: str, user_id: str) -> str:
        return derive_sandbox_scope_token(user_id=user_id, thread_id=thread_id)

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return user_id or "", thread_id

    def _active_count_locked(self) -> int:
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: SmolSandbox, *, reason: str) -> None:
        try:
            entry.close()
        except Exception:
            logger.exception("Could not delete Smol sandbox %s after %s", sandbox_id, reason)

    def _create_sandbox(self, sandbox_id: str) -> SmolSandbox:
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)
        ConnectOptions, Machine, MachineConfig, ResourceSpec = _import_smol()
        config = self._config
        conn = ConnectOptions(target=config["target"], api_key=config["api_key"])
        name = f"deer-flow-smol-{sandbox_id}-{uuid.uuid4().hex[:8]}"
        resources = ResourceSpec(cpus=config["cpus"], memory_mb=config["memory_mb"], network=True)
        machine = Machine.create(
            MachineConfig(
                name=name,
                image=config["image"],
                command=["sleep", "infinity"],
                resources=resources,
                persistent=True,
                ttl_seconds=config["ttl_seconds"] if config["target"] == "cloud" else None,
                # No published app ports: wait for guest execution, not HTTP.
                wait_for_ports=False,
            ),
            conn,
        )
        try:
            result = machine.exec(["mkdir", "-p", "/mnt/user-data/workspace", "/mnt/user-data/uploads", "/mnt/user-data/outputs"])
            if result.exit_code != 0:
                raise OSError(f"Smol sandbox bootstrap failed: {result.stderr}")
        except BaseException:
            machine.delete()
            raise
        return SmolSandbox(sandbox_id, machine, default_env=config["environment"], default_timeout=config["bash_command_timeout"], target=config["target"])

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        if thread_id is None:
            sandbox_id = uuid.uuid4().hex[:16]
            sandbox = self._create_sandbox(sandbox_id)
            with self._lock:
                self._sandboxes[sandbox_id] = sandbox
            return sandbox_id
        key = self._thread_key(thread_id, user_id)
        sandbox_id = self._sandbox_id(thread_id, key[0])
        with self._acquire_serializer.hold(sandbox_id):
            with self._lock:
                existing = self._thread_sandboxes.get(key)
                if existing in self._sandboxes:
                    return existing
            reclaimed = self._reclaim(sandbox_id)
            if reclaimed is None:
                reclaimed = self._create_sandbox(sandbox_id)
                with self._lock:
                    self._sandboxes[sandbox_id] = reclaimed
            with self._lock:
                self._thread_sandboxes[key] = sandbox_id
            return sandbox_id

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return await self._acquire_serializer.run_on_executor(partial(self.acquire, thread_id, user_id=user_id))

    def _reclaim(self, sandbox_id: str) -> SmolSandbox | None:
        with self._lock:
            entry = self._warm_pool.pop(sandbox_id, None)
        if entry is None:
            return None
        sandbox, _ = entry
        try:
            result = sandbox._exec(["sh", "-c", "true"], timeout=10)
            if result.exit_code != 0:
                raise OSError("warm sandbox health check failed")
        except Exception:
            logger.exception("Warm Smol sandbox %s is not healthy", sandbox_id)
            self._destroy_warm_entry(sandbox_id, sandbox, reason="health_check_failed")
            return None
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
        return sandbox

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str) -> Sandbox | None:
        with self._lock:
            if self._thread_sandboxes.get(self._thread_key(thread_id, user_id)) != sandbox_id:
                return None
            return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            if sandbox is None:
                return
            if not self._shutdown_called:
                self._warm_pool[sandbox_id] = (sandbox, time.time())
                return
        sandbox.close()

    def reset(self) -> None:
        with self._lock:
            now = time.time()
            for sandbox_id, sandbox in self._sandboxes.items():
                self._warm_pool.setdefault(sandbox_id, (sandbox, now))
            self._sandboxes.clear()
            self._thread_sandboxes.clear()
        self._acquire_serializer.close()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
        self._stop_idle_checker()
        with self._lock:
            sandboxes = list(self._sandboxes.values()) + [sandbox for sandbox, _ in self._warm_pool.values()]
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._thread_sandboxes.clear()
        self._acquire_serializer.close()
        for sandbox in sandboxes:
            try:
                sandbox.close()
            except Exception:
                logger.exception("Could not delete Smol sandbox %s during shutdown", sandbox.id)

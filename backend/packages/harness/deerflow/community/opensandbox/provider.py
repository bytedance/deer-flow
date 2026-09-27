"""OpenSandbox-backed community ``SandboxProvider`` for DeerFlow."""

from __future__ import annotations

import atexit
import ipaddress
import logging
import os
import threading
import time
import uuid
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from deerflow.config import get_app_config
from deerflow.sandbox.acquire_serialization import AcquireSerializer
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider

from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .sandbox import OpenSandboxSandbox, format_execution

if TYPE_CHECKING:
    from opensandbox.config.connection_sync import ConnectionConfigSync
    from opensandbox.models.execd import RunCommandOpts
    from opensandbox.sync import SandboxSync

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.11"
DEFAULT_READY_TIMEOUT = 30.0
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_SANDBOX_TIMEOUT = 4 * 60 * 60
DEFAULT_COMMAND_TIMEOUT = 10 * 60
_BOOTSTRAP_TIMEOUT = 30.0
_BOOTSTRAP_COMMAND = "mkdir -p /mnt/user-data/workspace /mnt/user-data/uploads /mnt/user-data/outputs"


def _uses_insecure_remote_http(domain: Any, protocol: str) -> bool:
    if not domain:
        return False
    value = str(domain)
    try:
        parsed = urlsplit(value if "://" in value else f"{protocol}://{value}")
    except ValueError:
        return False
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        return False
    if parsed.hostname.lower() == "localhost":
        return False
    try:
        return not ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return True


def _import_sdk() -> tuple[type[SandboxSync], type[ConnectionConfigSync], type[RunCommandOpts]]:
    """Import the optional OpenSandbox sync SDK only when this provider is used."""
    try:
        from opensandbox.config.connection_sync import ConnectionConfigSync
        from opensandbox.models.execd import RunCommandOpts
        from opensandbox.sync import SandboxSync
    except ImportError as exc:  # pragma: no cover - depends on optional install state
        raise ImportError("OpenSandboxProvider requires the optional 'opensandbox' dependency. Install it with: pip install 'deerflow-harness[opensandbox]' or pip install 'opensandbox>=0.1.15,<0.2.0'.") from exc
    return SandboxSync, ConnectionConfigSync, RunCommandOpts


class OpenSandboxProvider(WarmPoolLifecycleMixin[OpenSandboxSandbox], SandboxProvider):
    """Create one OpenSandbox environment per effective user/thread scope."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    _idle_checker_thread_name = "opensandbox-idle-reaper"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, OpenSandboxSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[OpenSandboxSandbox, float]] = {}
        self._acquire_serializer: AcquireSerializer[str] = AcquireSerializer(thread_name_prefix="opensandbox-acquire-wait")
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._shutdown_called = False
        self._sdk: tuple[type[SandboxSync], type[ConnectionConfigSync], type[RunCommandOpts]] | None = None
        self._config = self._load_config()
        atexit.register(self.shutdown)
        self._start_idle_checker()

    @staticmethod
    def _positive_float(name: str, value: Any, default: float) -> float:
        resolved = float(default if value is None else value)
        if resolved <= 0:
            raise ValueError(f"sandbox.{name} must be positive")
        return resolved

    def _load_config(self) -> dict[str, Any]:
        sandbox_config = get_app_config().sandbox

        def option(name: str, default: Any = None) -> Any:
            return getattr(sandbox_config, name, default)

        api_key = option("api_key")
        domain = option("domain")
        protocol = option("protocol") or "http"
        effective_domain = domain or os.environ.get("OPEN_SANDBOX_DOMAIN")
        if not (api_key or os.environ.get("OPEN_SANDBOX_API_KEY")) and not effective_domain:
            logger.warning("OpenSandboxProvider: no api_key or domain configured (set sandbox.api_key/sandbox.domain in config.yaml or OPEN_SANDBOX_API_KEY/OPEN_SANDBOX_DOMAIN). The SDK will default to unauthenticated localhost:8080.")
        if _uses_insecure_remote_http(effective_domain, protocol):
            logger.warning("OpenSandboxProvider: remote OpenSandbox domain uses HTTP; use HTTPS to protect credentials and sandbox traffic.")
        environment = dict(option("environment") or {})
        _validate_extra_env(environment)
        replicas = option("replicas")
        idle_timeout = option("idle_timeout")
        raw_sandbox_timeout = option("sandbox_timeout")
        sandbox_timeout = float(DEFAULT_SANDBOX_TIMEOUT if raw_sandbox_timeout is None else raw_sandbox_timeout)
        if sandbox_timeout < 0:
            raise ValueError("sandbox.sandbox_timeout must be non-negative")
        return {
            "api_key": api_key,
            "domain": domain,
            "protocol": protocol,
            "request_timeout": self._positive_float("request_timeout", option("request_timeout"), DEFAULT_REQUEST_TIMEOUT),
            "use_server_proxy": bool(option("use_server_proxy", False)),
            "image": option("image") or DEFAULT_IMAGE,
            "ready_timeout": self._positive_float("ready_timeout", option("ready_timeout"), DEFAULT_READY_TIMEOUT),
            "sandbox_timeout": None if sandbox_timeout == 0 else sandbox_timeout,
            "command_timeout": self._positive_float("bash_command_timeout", option("bash_command_timeout"), DEFAULT_COMMAND_TIMEOUT),
            "environment": self._resolve_env_vars(environment),
            "replicas": replicas if replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": idle_timeout if idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                resolved[key] = os.environ.get(value[1:], "")
            else:
                resolved[key] = "" if value is None else str(value)
        return resolved

    def _get_sdk(self) -> tuple[type[SandboxSync], type[ConnectionConfigSync], type[RunCommandOpts]]:
        with self._lock:
            sdk = self._sdk
        if sdk is not None:
            return sdk
        imported = _import_sdk()
        with self._lock:
            if self._sdk is None:
                self._sdk = imported
                return imported
            return self._sdk

    def _new_connection_config(self, connection_config_cls: type[ConnectionConfigSync]) -> ConnectionConfigSync:
        # SandboxSync.create() derives an SDK-owned transport on a config copy,
        # and destroy() closes that transport. A fresh base config per remote
        # ensures no live sandbox can inherit another sandbox's transport.
        return connection_config_cls(
            api_key=self._config["api_key"],
            domain=self._config["domain"],
            protocol=self._config["protocol"],
            request_timeout=timedelta(seconds=self._config["request_timeout"]),
            use_server_proxy=self._config["use_server_proxy"],
        )

    @staticmethod
    def _sandbox_id(thread_id: str, user_id: str) -> str:
        return derive_sandbox_scope_token(user_id=user_id, thread_id=thread_id)

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    def _start_idle_checker(self) -> None:
        if self._config["idle_timeout"] <= 0:
            return
        super()._start_idle_checker()

    def _active_count_locked(self) -> int:
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: OpenSandboxSandbox, *, reason: str) -> None:
        self._destroy_quietly(entry, context=f"warm pool, reason={reason}")

    @staticmethod
    def _destroy_quietly(sandbox: OpenSandboxSandbox, *, context: str) -> None:
        try:
            sandbox.destroy()
        except Exception as exc:
            logger.warning("Error destroying OpenSandbox %s (%s): %s", sandbox.id, context, exc)

    def _invalidate_sandbox(self, sandbox_id: str, reason: str) -> None:
        with self._lock:
            active = self._sandboxes.pop(sandbox_id, None)
            warm_entry = self._warm_pool.pop(sandbox_id, None)
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
        sandbox = active or (warm_entry[0] if warm_entry is not None else None)
        if sandbox is None:
            return
        logger.warning("Invalidating OpenSandbox %s after terminal failure: %s", sandbox_id, reason)
        self._destroy_quietly(sandbox, context="terminal failure")

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        with self._lock:
            if self._shutdown_called:
                raise RuntimeError("OpenSandboxProvider has been shut down")
        if thread_id is None:
            sandbox_id = str(uuid.uuid4())[:8]
            sandbox = self._create_sandbox(sandbox_id, thread_id=None, user_id=user_id)
            with self._lock:
                if self._shutdown_called:
                    destroy_after_unlock = True
                else:
                    self._sandboxes[sandbox_id] = sandbox
                    destroy_after_unlock = False
            if destroy_after_unlock:
                self._destroy_quietly(sandbox, context="created during shutdown")
                raise RuntimeError("OpenSandboxProvider shut down during acquire")
            return sandbox_id

        key = self._thread_key(thread_id, user_id)
        sandbox_id = self._sandbox_id(thread_id, user_id or "")
        with self._acquire_serializer.hold(sandbox_id):
            return self._acquire_scope_locked(key, sandbox_id, thread_id=thread_id, user_id=user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire without blocking the event loop.

        The entire synchronous acquire (serializer wait + body) runs on the
        serializer's dedicated executor — never the default executor. A
        cancelled awaiter abandons the worker thread, which runs to
        completion and releases the hold itself, so a retry serializes
        behind it instead of overlapping the abandoned body.
        """
        acquire = partial(self.acquire, thread_id, user_id=user_id)
        return await self._acquire_serializer.run_on_executor(acquire)

    def _acquire_scope_locked(self, key: tuple[str, str], sandbox_id: str, *, thread_id: str, user_id: str | None) -> str:
        with self._lock:
            existing = self._thread_sandboxes.get(key)
            active = self._sandboxes.get(existing) if existing is not None else None
        if existing is not None and active is not None:
            try:
                active.renew()
                return existing
            except Exception:
                # A terminal renewal failure invokes _invalidate_sandbox,
                # which removes and closes this exact client. Rebuild in the
                # same acquire; transient errors leave the registry intact
                # and must remain visible to the caller.
                with self._lock:
                    invalidated = self._sandboxes.get(existing) is not active and existing not in self._warm_pool
                    shutting_down = self._shutdown_called
                if not invalidated or not active.is_closed or shutting_down:
                    raise
                logger.info("Rebuilding terminal OpenSandbox %s during acquire", existing)
        reclaimed = self._reclaim_warm_pool(sandbox_id)
        if reclaimed is not None:
            with self._lock:
                if self._shutdown_called:
                    raise RuntimeError("OpenSandboxProvider shut down during acquire")
                if reclaimed in self._sandboxes:
                    self._thread_sandboxes[key] = reclaimed
                    return reclaimed
        sandbox = self._create_sandbox(sandbox_id, thread_id=thread_id, user_id=user_id)
        with self._lock:
            if self._shutdown_called:
                destroy_after_unlock = True
            else:
                self._sandboxes[sandbox_id] = sandbox
                self._thread_sandboxes[key] = sandbox_id
                destroy_after_unlock = False
        if destroy_after_unlock:
            self._destroy_quietly(sandbox, context="created during shutdown")
            raise RuntimeError("OpenSandboxProvider shut down during acquire")
        return sandbox_id

    def _create_sandbox(self, sandbox_id: str, *, thread_id: str | None, user_id: str | None) -> OpenSandboxSandbox:
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        sandbox_cls, connection_config_cls, run_command_opts_cls = self._get_sdk()
        connection_config = self._new_connection_config(connection_config_cls)
        metadata = {"deer_flow_provider": "opensandbox"}
        if thread_id is not None:
            metadata["deer_flow_thread"] = thread_id
        if user_id is not None:
            metadata["deer_flow_user"] = user_id
        remote = sandbox_cls.create(
            self._config["image"],
            timeout=None if self._config["sandbox_timeout"] is None else timedelta(seconds=self._config["sandbox_timeout"]),
            ready_timeout=timedelta(seconds=self._config["ready_timeout"]),
            env=self._config["environment"] or None,
            metadata=metadata,
            connection_config=connection_config,
        )
        try:
            bootstrap = remote.commands.run(
                _BOOTSTRAP_COMMAND,
                opts=run_command_opts_cls(
                    timeout=timedelta(seconds=_BOOTSTRAP_TIMEOUT),
                    envs=self._config["environment"] or None,
                ),
            )
            exit_code = getattr(bootstrap, "exit_code", None)
            if exit_code != 0:
                detail = format_execution(bootstrap).strip() or ("no exit code" if exit_code is None else f"exit code {exit_code}")
                raise RuntimeError(f"OpenSandbox bootstrap failed: {detail}")
        except Exception:
            try:
                remote.destroy()
            except Exception:
                logger.warning("Failed to destroy OpenSandbox %s after bootstrap failure", remote.id, exc_info=True)
            raise

        return OpenSandboxSandbox(
            sandbox_id,
            remote,
            run_command_opts_cls=run_command_opts_cls,
            default_env=self._config["environment"],
            sandbox_timeout=None if self._config["sandbox_timeout"] is None else timedelta(seconds=self._config["sandbox_timeout"]),
            default_command_timeout=self._config["command_timeout"],
            on_terminal_failure=self._invalidate_sandbox,
        )

    def _reclaim_warm_pool(self, sandbox_id: str) -> str | None:
        with self._lock:
            warm_entry = self._warm_pool.get(sandbox_id)
        if warm_entry is None:
            return None
        sandbox = warm_entry[0]
        if not sandbox.ping():
            with self._lock:
                removed = self._warm_pool.pop(sandbox_id, None)
            if removed is not None:
                self._destroy_warm_entry(sandbox_id, removed[0], reason="health_check_failed")
            return None
        with self._lock:
            removed = self._warm_pool.pop(sandbox_id, None)
            if removed is None:
                return None
            self._sandboxes[sandbox_id] = removed[0]
        logger.info("Reclaimed warm OpenSandbox %s (remote=%s)", sandbox_id, sandbox.remote_id)
        return sandbox_id

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            if sandbox is None:
                return
            if self._shutdown_called:
                destroy_after_unlock = True
            else:
                self._warm_pool[sandbox_id] = (sandbox, time.time())
                destroy_after_unlock = False
        if destroy_after_unlock:
            self._destroy_quietly(sandbox, context="released during shutdown")

    def reset(self) -> None:
        """Park active clients so the detached provider still owns their cleanup."""
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
            sandboxes = list(self._sandboxes.values()) + [entry for entry, _ in self._warm_pool.values()]
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._thread_sandboxes.clear()
            self._acquire_serializer.close()
        for sandbox in sandboxes:
            self._destroy_quietly(sandbox, context="shutdown")


__all__ = ["OpenSandboxProvider"]

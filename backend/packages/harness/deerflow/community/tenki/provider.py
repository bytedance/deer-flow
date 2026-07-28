"""``TenkiSandboxProvider`` — DeerFlow :class:`SandboxProvider` backed by Tenki.

Integrates `Tenki <https://tenki.cloud>`_ cloud sandboxes as a DeerFlow sandbox
backend. Each sandbox is an isolated cloud microVM created from a stock base
image; the provider creates one per ``(user, thread)`` and reuses it within the
process, parking released sandboxes in a warm pool (shared
:class:`WarmPoolLifecycleMixin` machinery) for fast reclaim.

Config is read off :class:`SandboxConfig` (``extra="allow"``), so Tenki keys may
appear under ``sandbox:`` in ``config.yaml`` even though they are not declared on
the model — see this package's ``__init__`` docstring for the full set.

The Tenki SDK is imported lazily (``_import_client``) so the harness — and every
other provider — installs without ``tenki-sandbox``; the dependency is only
needed once this provider is selected.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import shlex
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from deerflow.config import get_app_config
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider

from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .sandbox import DEFAULT_TENKI_HOME_DIR, TenkiSandbox

if TYPE_CHECKING:
    from tenki_sandbox import Client

logger = logging.getLogger(__name__)

_SANDBOX_NAME_PREFIX = "deer-flow-tenki-"
# Tenki terminates a sandbox at its max lifetime (~30 min by default), which
# would silently drop a long-running thread's state mid-conversation. DeerFlow
# owns the lifecycle here — the warm pool's idle_timeout reaps unused sandboxes
# — so ask for a lifetime that comfortably outlives a research run. Override
# with sandbox.max_duration (seconds); 0 falls back to the Tenki account default.
DEFAULT_MAX_DURATION = 4 * 60 * 60
# Bootstrap is best-effort and holds the per-scope acquire lock, so bound its
# exec: a hang here (e.g. a stuck sudo) would otherwise stall acquire for that
# scope indefinitely and queue later acquires behind it. A timeout drops it to
# the existing warning path instead.
_BOOTSTRAP_TIMEOUT = 30.0


def _bootstrap_script(home_dir: str) -> str:
    """Materialise DeerFlow's virtual path layout inside the sandbox.

    Tenki sandboxes run as the unprivileged ``tenki`` user with ``/mnt``
    root-owned, so ``mkdir -p /mnt/user-data/...`` fails with Permission denied.
    Mirroring ``community/e2b_sandbox``, we create the real backing directories
    under the writable HOME and best-effort ``sudo``-symlink ``/mnt/user-data``
    to it so commands using the documented ``/mnt/...`` paths still work. If
    sudo is unavailable the symlink step is skipped; the file APIs keep working
    via :meth:`TenkiSandbox._resolve_path`'s home remap.

    ``sudo -n`` (non-interactive) is deliberate: if the tenki user's sudoers
    entry needs a password, a bare ``sudo`` on a tty-allocating exec would block
    on the password prompt and — with this call's exec timeout — stall the whole
    acquire. ``-n`` fails fast instead, and the existing ``|| true`` swallows it.
    """
    home = shlex.quote(home_dir)
    return (
        f"mkdir -p {home}/workspace {home}/uploads {home}/outputs; "
        f"if command -v sudo >/dev/null 2>&1; then "
        f"  if [ ! -e /mnt/user-data ] || [ -L /mnt/user-data ]; then "
        f"    sudo -n ln -sfn {home} /mnt/user-data 2>/dev/null || true; "
        f"  fi; "
        f"fi; "
        f"echo BOOTSTRAP_OK"
    )


def _import_client() -> type[Client]:
    """Import Tenki's ``Client`` lazily.

    Kept out of module import so the harness (and every other provider) installs
    without Tenki; the dependency is only needed once this provider is selected.
    """
    try:
        from tenki_sandbox import Client
    except ImportError as e:  # pragma: no cover - depends on the optional dependency
        raise ImportError("TenkiSandboxProvider requires the optional 'tenki-sandbox' dependency. Install it with: pip install 'deerflow-harness[tenki]' or pip install tenki-sandbox.") from e
    return Client


class TenkiSandboxProvider(WarmPoolLifecycleMixin[TenkiSandbox], SandboxProvider):
    """Run each DeerFlow sandbox as a Tenki cloud microVM."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    _idle_checker_thread_name = "tenki-idle-reaper"

    @staticmethod
    def _sandbox_id(thread_id: str, user_id: str) -> str:
        """Deterministic sandbox ID from user/thread scope.

        Includes user_id so a sandbox created for one user's bucket cannot be
        reclaimed by another user's thread with the same thread_id. The warm
        pool is keyed by this id alone (``_reclaim_warm_pool`` looks it up
        directly, with no full-seed fallback), so on a hosted multi-tenant
        gateway a hash collision would let one user reclaim another's parked
        sandbox. 64 bits, like community/e2b_sandbox, keeps that negligible.
        """
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:16]

    # ── Provider lifecycle ───────────────────────────────────────────────

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, TenkiSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[TenkiSandbox, float]] = {}
        self._acquire_locks: dict[str, threading.Lock] = {}
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._shutdown_called = False
        self._client: Client | None = None
        self._config = self._load_config()
        atexit.register(self.shutdown)
        self._start_idle_checker()

    def _load_config(self) -> dict[str, Any]:
        sandbox_config = get_app_config().sandbox

        def _opt(name: str, default: Any = None) -> Any:
            return getattr(sandbox_config, name, default)

        api_key = _opt("api_key")
        replicas = _opt("replicas")
        idle_timeout = _opt("idle_timeout")
        max_duration = _opt("max_duration")
        environment = dict(_opt("environment") or {})
        # Fail fast on a misconfigured key (e.g. "bad-key"): the per-call env goes
        # through the same POSIX-name check in execute_command, but this static
        # config env is merged into every command and would otherwise only surface
        # as a confusing SDK error at create/exec time.
        _validate_extra_env(environment)
        return {
            "max_duration": float(max_duration if max_duration is not None else DEFAULT_MAX_DURATION),
            # Off by default (the SDK default). Warm-pool sandboxes stay running
            # between turns, so host pinning only matters to deployments that
            # also pause/resume; expose it rather than decide for them.
            "sticky": bool(_opt("sticky", False)),
            "api_key": api_key,  # None → SDK falls back to TENKI_API_KEY / TENKI_AUTH_TOKEN
            "base_url": _opt("base_url"),
            "image": _opt("image"),  # None → Tenki account default base image
            "home_dir": _opt("home_dir") or DEFAULT_TENKI_HOME_DIR,
            "project_id": _opt("project_id"),
            "workspace_id": _opt("workspace_id"),
            "cpu_cores": _opt("cpu_cores"),
            "memory_mb": _opt("memory_mb"),
            "environment": environment,
            "replicas": replicas if replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": idle_timeout if idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
        }

    def _get_client(self) -> Client:
        with self._lock:
            if self._client is not None:
                return self._client
        client_cls = _import_client()
        client = client_cls(auth_token=self._config["api_key"], base_url=self._config["base_url"])
        with self._lock:
            if self._client is None:
                self._client = client
            return self._client

    def _resolve_scope(self) -> tuple[str | None, str | None]:
        """Return (project_id, workspace_id), auto-selecting when unambiguous.

        Tenki's ``create`` needs a project scope. When the caller didn't set one
        in config, pick it if the account has exactly one workspace and project;
        otherwise raise with the choices so the operator can set ``project_id``.
        """
        project_id = self._config["project_id"]
        workspace_id = self._config["workspace_id"]
        if project_id is not None:
            return project_id, workspace_id

        identity = self._get_client().who_am_i()
        workspaces = list(identity.workspaces or [])
        if workspace_id is not None:
            workspaces = [w for w in workspaces if w.id == workspace_id]
        workspace = self._require_single(workspaces, "workspace", "workspace_id")
        project = self._require_single(list(workspace.projects or []), "project", "project_id")
        return project.id, workspace.id

    @staticmethod
    def _require_single(items: list[Any], kind: str, param: str) -> Any:
        if len(items) != 1:
            raise ValueError(f"Could not auto-select a Tenki {kind}; set sandbox.{param} in config.yaml. Found: {[(getattr(i, 'id', None), getattr(i, 'name', None)) for i in items]}")
        return items[0]

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    @classmethod
    def _sandbox_name(cls, sandbox_id: str) -> str:
        return f"{_SANDBOX_NAME_PREFIX}{sandbox_id}"

    def _lock_for_sandbox(self, sandbox_id: str) -> threading.Lock:
        with self._lock:
            lock = self._acquire_locks.get(sandbox_id)
            if lock is None:
                lock = threading.Lock()
                self._acquire_locks[sandbox_id] = lock
            return lock

    def _start_idle_checker(self) -> None:
        """Start idle cleanup when enabled; idle_timeout=0 keeps it disabled."""
        if self._config["idle_timeout"] <= 0:
            return
        super()._start_idle_checker()

    def _active_count_locked(self) -> int:
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: TenkiSandbox, *, reason: str) -> None:
        self._close_quietly(entry, context=f"warm pool, reason={reason}")

    def _invalidate_sandbox(self, sandbox_id: str, reason: str) -> None:
        """Destroy and deregister a sandbox after a terminal command-path failure."""
        to_close: TenkiSandbox | None = None
        with self._lock:
            active = self._sandboxes.pop(sandbox_id, None)
            warm_entry = self._warm_pool.pop(sandbox_id, None)
            for key in [k for k, sid in self._thread_sandboxes.items() if sid == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            to_close = active or (warm_entry[0] if warm_entry is not None else None)

        if to_close is None:
            logger.warning("Tenki sandbox %s failed terminally but was not tracked: %s", sandbox_id, reason)
            return
        logger.warning("Invalidating Tenki sandbox %s after terminal failure: %s", sandbox_id, reason)
        self._close_quietly(to_close, context="terminal failure")

    # ── Acquire / release ────────────────────────────────────────────────

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        if thread_id is None:
            sandbox_id = str(uuid.uuid4())[:8]
            sandbox = self._create_sandbox(sandbox_id)
            with self._lock:
                self._sandboxes[sandbox.id] = sandbox
            return sandbox.id

        key = self._thread_key(thread_id, user_id)
        sandbox_id = self._sandbox_id(thread_id, user_id or "")
        acquire_lock = self._lock_for_sandbox(sandbox_id)
        with acquire_lock:
            with self._lock:
                existing = self._thread_sandboxes.get(key)
                if existing is not None and existing in self._sandboxes:
                    return existing

            reclaimed = self._reclaim_warm_pool(sandbox_id)
            if reclaimed is not None:
                with self._lock:
                    self._thread_sandboxes[key] = reclaimed
                return reclaimed

            sandbox = self._create_sandbox(sandbox_id)
            with self._lock:
                self._sandboxes[sandbox.id] = sandbox
                self._thread_sandboxes[key] = sandbox.id
            return sandbox.id

    def _create_sandbox(self, sandbox_id: str) -> TenkiSandbox:
        # Enforce replica soft cap: evict the oldest warm sandbox if active + warm
        # are at capacity.
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        client = self._get_client()
        project_id, workspace_id = self._resolve_scope()
        create_kwargs: dict[str, Any] = {
            "name": self._sandbox_name(sandbox_id),
            "project_id": project_id,
            "workspace_id": workspace_id,
            "sticky": self._config["sticky"],
            # Wait for readiness ourselves (below) instead of inside create():
            # create(wait=True) raises with the session handle still local to the
            # SDK, so a readiness failure would leak a running, billed microVM
            # that this provider never sees and can never terminate.
            "wait": False,
        }
        if self._config["max_duration"] > 0:
            create_kwargs["max_duration"] = self._config["max_duration"]
        for key in ("image", "cpu_cores", "memory_mb"):
            if self._config[key] is not None:
                create_kwargs[key] = self._config[key]
        if self._config["environment"]:
            create_kwargs["env"] = self._config["environment"]

        remote = client.create(**create_kwargs)
        try:
            remote.wait_ready()
        except Exception:
            self._terminate_orphan(sandbox_id, remote)
            raise

        # Materialise DeerFlow's virtual path layout under the writable HOME.
        # Best-effort: on failure the file APIs still work via the home remap.
        try:
            result = remote.exec("sh", "-lc", _bootstrap_script(self._config["home_dir"]), timeout=_BOOTSTRAP_TIMEOUT)
            if result.exit_code not in (0, None) or "BOOTSTRAP_OK" not in (result.stdout_text or ""):
                logger.warning(
                    "Tenki bootstrap for %s exited code=%s stderr=%s",
                    sandbox_id,
                    result.exit_code,
                    (result.stderr_text or "").strip(),
                )
        except Exception as e:
            logger.warning("Tenki bootstrap for %s raised: %s", sandbox_id, e)
        logger.info("Created Tenki sandbox %s (name=%s)", sandbox_id, self._sandbox_name(sandbox_id))
        return TenkiSandbox(
            sandbox_id,
            remote,
            default_env=self._config["environment"],
            home_dir=self._config["home_dir"],
            on_terminal_failure=self._invalidate_sandbox,
        )

    @staticmethod
    def _terminate_orphan(sandbox_id: str, remote: Any) -> None:
        """Terminate a microVM that was created but never handed to the adapter."""
        try:
            remote.close()
            logger.warning("Terminated Tenki sandbox %s after it failed to become ready", sandbox_id)
        except Exception as e:
            logger.error("Leaked Tenki sandbox %s (id=%s): could not terminate after readiness failure: %s", sandbox_id, getattr(remote, "id", "?"), e)

    @staticmethod
    def _close_quietly(sandbox: TenkiSandbox, *, context: str) -> None:
        """Close a sandbox where the caller has no way to act on a failure."""
        try:
            sandbox.close()
        except Exception as e:
            logger.warning("Error closing Tenki sandbox %s (%s): %s", sandbox.id, context, e)

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        """Release a sandbox into the warm pool — the microVM stays running.

        The sandbox moves from ``_sandboxes`` to ``_warm_pool`` and its
        ``_thread_sandboxes`` entries are cleared. It is NOT terminated unless
        shutdown has already begun.
        """
        close_sandbox: TenkiSandbox | None = None
        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            for key in [k for k, sid in self._thread_sandboxes.items() if sid == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            if sandbox is None:
                return
            if self._shutdown_called:
                close_sandbox = sandbox
            else:
                self._warm_pool[sandbox_id] = (sandbox, time.time())

        if close_sandbox is not None:
            self._close_quietly(close_sandbox, context="released during shutdown")
            logger.info("Closed released Tenki sandbox %s because shutdown is in progress", sandbox_id)
        else:
            logger.info("Released Tenki sandbox %s to warm pool (microVM still running)", sandbox_id)

    def _reclaim_warm_pool(self, sandbox_id: str) -> str | None:
        """Reclaim a warm-pool sandbox by id after a liveness health check.

        Returns sandbox_id on success, None if not present or the health check
        fails (the dead entry is destroyed).
        """
        with self._lock:
            if sandbox_id not in self._warm_pool:
                return None
            sandbox, _ = self._warm_pool[sandbox_id]

        try:
            result = sandbox.execute_command("echo ok", timeout=10)
            healthy = "ok" in result
        except Exception as e:
            logger.warning("Tenki warm-pool sandbox %s health check error: %s", sandbox_id, e)
            healthy = False

        if not healthy:
            with self._lock:
                warm_entry = self._warm_pool.pop(sandbox_id, None)
            if warm_entry is not None:
                self._destroy_warm_entry(sandbox_id, warm_entry[0], reason="health_check_failed")
            return None

        with self._lock:
            warm_entry = self._warm_pool.pop(sandbox_id, None)
            if warm_entry is None:
                return None  # Raced with another thread
            self._sandboxes[sandbox_id] = warm_entry[0]

        logger.info("Reclaimed warm-pool Tenki sandbox %s", sandbox_id)
        return sandbox_id

    def reset(self) -> None:
        """Park tracked sandboxes into this instance's warm pool for later cleanup.

        ``reset_sandbox_provider()`` drops the singleton and calls this so config
        changes take effect on the next construction. Teardown belongs to
        ``shutdown()``; reset leaves running microVMs alive but visible to this
        instance's idle reaper and atexit shutdown instead of orphaning them.
        """
        with self._lock:
            now = time.time()
            for sandbox_id, sandbox in self._sandboxes.items():
                self._warm_pool.setdefault(sandbox_id, (sandbox, now))
            self._sandboxes.clear()
            self._thread_sandboxes.clear()
            self._acquire_locks.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True

        self._stop_idle_checker()

        with self._lock:
            active = list(self._sandboxes.values())
            warm = [sandbox for sandbox, _ in self._warm_pool.values()]
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._thread_sandboxes.clear()
            self._acquire_locks.clear()

        for sandbox in active + warm:
            self._close_quietly(sandbox, context="shutdown")

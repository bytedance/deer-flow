"""AIO Sandbox Provider — orchestrates sandbox lifecycle with pluggable backends.

This provider composes:
- SandboxBackend: how sandboxes are provisioned (local container vs remote/K8s)

The provider itself handles:
- In-process caching for fast repeated access
- Idle timeout management
- Graceful shutdown with signal handling
- Mount computation (thread-specific, skills)
"""

import asyncio
import atexit
import hashlib
import logging
import os
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from deerflow.community.warm_pool_lifecycle import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_REPLICAS,
    WarmPoolLifecycleMixin,
)
from deerflow.community.warm_pool_lifecycle import (
    IDLE_CHECK_INTERVAL as _SHARED_IDLE_CHECK_INTERVAL,
)
from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths, join_host_path
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.skills.storage import user_should_see_legacy_skills

from .aio_sandbox import AioSandbox
from .backend import SandboxBackend, wait_for_sandbox_ready, wait_for_sandbox_ready_async
from .local_backend import LocalContainerBackend
from .remote_backend import RemoteSandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_PORT = 8080
DEFAULT_CONTAINER_PREFIX = "deer-flow-sandbox"
IDLE_CHECK_INTERVAL = _SHARED_IDLE_CHECK_INTERVAL
THREAD_LOCK_EXECUTOR_WORKERS = min(32, (os.cpu_count() or 1) + 4)
_THREAD_LOCK_EXECUTOR = ThreadPoolExecutor(max_workers=THREAD_LOCK_EXECUTOR_WORKERS, thread_name_prefix="sandbox-lock-wait")
atexit.register(_THREAD_LOCK_EXECUTOR.shutdown, wait=False, cancel_futures=True)


def _lock_file_exclusive(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return

    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return

    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _open_lock_file(lock_path):
    return open(lock_path, "a", encoding="utf-8")


async def _acquire_thread_lock_async(lock: threading.Lock) -> None:
    """Acquire a threading.Lock without polling or using the default executor."""
    loop = asyncio.get_running_loop()
    acquire_future = loop.run_in_executor(_THREAD_LOCK_EXECUTOR, lock.acquire, True)

    try:
        acquired = await asyncio.shield(acquire_future)
    except asyncio.CancelledError:
        acquire_future.add_done_callback(lambda task: _release_cancelled_lock_acquire(lock, task))
        raise

    if not acquired:
        raise RuntimeError("Failed to acquire sandbox thread lock")


def _release_cancelled_lock_acquire(lock: threading.Lock, task: asyncio.Future[bool]) -> None:
    """Release a lock acquired after its awaiting coroutine was cancelled."""
    if task.cancelled():
        return

    try:
        acquired = task.result()
    except Exception as e:
        logger.warning(f"Cancelled sandbox lock acquisition finished with error: {e}")
        return

    if acquired:
        lock.release()


class AioSandboxProvider(WarmPoolLifecycleMixin[SandboxInfo], SandboxProvider):
    """Sandbox provider that manages containers running the AIO sandbox.

    Architecture:
        This provider composes a SandboxBackend (how to provision), enabling:
        - Local Docker/Apple Container mode (auto-start containers)
        - Remote/K8s mode (connect to pre-existing sandbox URL)

    Configuration options in config.yaml under sandbox:
        use: deerflow.community.aio_sandbox:AioSandboxProvider
        image: <container image>
        port: 8080                      # Base port for local containers
        container_prefix: deer-flow-sandbox
        idle_timeout: 600               # Idle timeout in seconds (0 to disable)
        replicas: 3                     # Max concurrent sandbox containers (LRU eviction when exceeded)
        mounts:                         # Volume mounts for local containers
          - host_path: /path/on/host
            container_path: /path/in/container
            read_only: false
        environment:                    # Environment variables for containers
          NODE_ENV: production
          API_KEY: $MY_API_KEY
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sandboxes: dict[str, AioSandbox] = {}  # sandbox_id -> AioSandbox instance
        self._sandbox_infos: dict[str, SandboxInfo] = {}  # sandbox_id -> SandboxInfo (for destroy)
        self._thread_sandboxes: dict[tuple[str, str], str] = {}  # (user_id, thread_id) -> sandbox_id
        self._thread_locks: dict[tuple[str, str], threading.Lock] = {}  # (user_id, thread_id) -> in-process lock
        self._last_activity: dict[str, float] = {}  # sandbox_id -> last activity timestamp
        # Warm pool: released sandboxes whose containers are still running.
        # Maps sandbox_id -> (SandboxInfo, release_timestamp).
        # Containers here can be reclaimed quickly (no cold-start) or destroyed
        # when replicas capacity is exhausted.
        self._warm_pool: dict[str, tuple[SandboxInfo, float]] = {}
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None

        self._config = self._load_config()
        self._backend: SandboxBackend = self._create_backend()

        # Register shutdown handler
        atexit.register(self.shutdown)
        self._register_signal_handlers()

        # Reconcile orphaned containers from previous process lifecycles
        self._reconcile_orphans()

        # Start idle checker if enabled
        if self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT) > 0:
            self._start_idle_checker()

    @property
    def uses_thread_data_mounts(self) -> bool:
        """Whether thread workspace/uploads/outputs are visible via mounts.

        Local container backends bind-mount the thread data directories, so files
        written by the gateway are already visible when the sandbox starts.
        Remote backends may require explicit file sync.
        """
        return isinstance(self._backend, LocalContainerBackend)

    # ── Factory methods ──────────────────────────────────────────────────

    def _create_backend(self) -> SandboxBackend:
        """Create the appropriate backend based on configuration.

        Selection logic (checked in order):
        1. ``provisioner_url`` set → RemoteSandboxBackend (provisioner mode)
              Provisioner dynamically creates Pods + Services in k3s.
        2. Default → LocalContainerBackend (local mode)
              Local provider manages container lifecycle directly (start/stop).
        """
        provisioner_url = self._config.get("provisioner_url")
        if provisioner_url:
            logger.info(f"Using remote sandbox backend with provisioner at {provisioner_url}")
            api_key = self._config.get("provisioner_api_key", "")
            return RemoteSandboxBackend(provisioner_url=provisioner_url, api_key=api_key)

        logger.info("Using local container sandbox backend")
        return LocalContainerBackend(
            image=self._config["image"],
            base_port=self._config["port"],
            container_prefix=self._config["container_prefix"],
            config_mounts=self._config["mounts"],
            environment=self._config["environment"],
        )

    # ── Configuration ────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        """Load sandbox configuration from app config."""
        config = get_app_config()
        sandbox_config = config.sandbox

        idle_timeout = getattr(sandbox_config, "idle_timeout", None)
        replicas = getattr(sandbox_config, "replicas", None)

        return {
            "image": sandbox_config.image or DEFAULT_IMAGE,
            "port": sandbox_config.port or DEFAULT_PORT,
            "container_prefix": sandbox_config.container_prefix or DEFAULT_CONTAINER_PREFIX,
            "idle_timeout": idle_timeout if idle_timeout is not None else DEFAULT_IDLE_TIMEOUT,
            "replicas": replicas if replicas is not None else DEFAULT_REPLICAS,
            "mounts": sandbox_config.mounts or [],
            "environment": self._resolve_env_vars(sandbox_config.environment or {}),
            # provisioner URL for dynamic pod management (e.g. http://provisioner:8002)
            "provisioner_url": getattr(sandbox_config, "provisioner_url", None) or "",
            "provisioner_api_key": getattr(sandbox_config, "provisioner_api_key", None) or "",
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        """Resolve environment variable references (values starting with $)."""
        resolved = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                env_name = value[1:]
                resolved[key] = os.environ.get(env_name, "")
            else:
                resolved[key] = str(value)
        return resolved

    # ── Startup reconciliation ────────────────────────────────────────────

    def _reconcile_orphans(self) -> None:
        """Reconcile orphaned containers left by previous process lifecycles.

        On startup, enumerate all running containers matching our prefix
        and adopt them all into the warm pool.  The idle checker will reclaim
        containers that nobody re-acquires within ``idle_timeout``.

        All containers are adopted unconditionally because we cannot
        distinguish "orphaned" from "actively used by another process"
        based on age alone — ``idle_timeout`` represents inactivity, not
        uptime.  Adopting into the warm pool and letting the idle checker
        decide avoids destroying containers that a concurrent process may
        still be using.

        This closes the fundamental gap where in-memory state loss (process
        restart, crash, SIGKILL) leaves Docker containers running forever.
        """
        try:
            running = self._backend.list_running()
        except Exception as e:
            logger.warning(f"Failed to enumerate running containers during startup reconciliation: {e}")
            return

        if not running:
            return

        current_time = time.time()
        adopted = 0

        for info in running:
            age = current_time - info.created_at if info.created_at > 0 else float("inf")
            # Single lock acquisition per container: atomic check-and-insert.
            # Avoids a TOCTOU window between the "already tracked?" check and
            # the warm-pool insert.
            with self._lock:
                if info.sandbox_id in self._sandboxes or info.sandbox_id in self._warm_pool:
                    continue
                self._warm_pool[info.sandbox_id] = (info, current_time)
            adopted += 1
            logger.info(f"Adopted container {info.sandbox_id} into warm pool (age: {age:.0f}s)")

        logger.info(f"Startup reconciliation complete: {adopted} adopted into warm pool, {len(running)} total found")

    # ── Deterministic ID ─────────────────────────────────────────────────

    @staticmethod
    def _effective_acquire_user_id(user_id: str | None) -> str:
        return user_id or get_effective_user_id()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        return (user_id, thread_id)

    @staticmethod
    def _deterministic_sandbox_id(thread_id: str, user_id: str) -> str:
        """Generate a deterministic sandbox ID from user/thread scope.

        Includes user_id so a previously-created default-bucket sandbox cannot be
        reused for an auth/channel run that should mount a user-scoped bucket.
        """
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:8]

    # ── Mount helpers ────────────────────────────────────────────────────

    def _get_extra_mounts(self, thread_id: str | None, *, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """Collect all extra mounts for a sandbox (thread-specific + skills)."""
        mounts: list[tuple[str, str, bool]] = []

        if thread_id:
            mounts.extend(self._get_thread_mounts(thread_id, user_id=user_id))
            logger.info(f"Adding thread mounts for thread {thread_id}: {mounts}")

        skills_mounts = self._get_skills_mounts(user_id=user_id)
        if skills_mounts:
            mounts.extend(skills_mounts)
            logger.info(f"Adding skills mounts: {skills_mounts}")

        return mounts

    @staticmethod
    def _get_thread_mounts(thread_id: str, *, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """Get volume mounts for a thread's data directories.

        Creates directories if they don't exist (lazy initialization).
        Mount sources use host_base_dir so that when running inside Docker with a
        mounted Docker socket (DooD), the host Docker daemon can resolve the paths.
        """
        paths = get_paths()
        effective_user_id = AioSandboxProvider._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)

        return [
            (paths.host_sandbox_work_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (paths.host_sandbox_uploads_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (paths.host_sandbox_outputs_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
            # ACP workspace: read-only inside the sandbox (lead agent reads results;
            # the ACP subprocess writes from the host side, not from within the container).
            (paths.host_acp_workspace_dir(thread_id, user_id=effective_user_id), "/mnt/acp-workspace", True),
        ]

    @staticmethod
    def _get_skills_mounts(*, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """Get skills directory mount configurations for three-way skills layout.

        Mirrors ``LocalSandboxProvider._build_thread_path_mappings`` for AIO
        sandboxes: public, per-user custom, and legacy (pre-migration
        global-custom) skills are mounted to separate container subdirectories so
        that ``Skill.get_container_path()`` category-aware paths resolve
        correctly inside the sandbox.

        Mount sources use ``DEER_FLOW_HOST_SKILLS_PATH`` and
        ``DEER_FLOW_HOST_BASE_DIR`` when running inside Docker (DooD) so the
        host Docker daemon can resolve the paths.
        """
        mounts: list[tuple[str, str, bool]] = []
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # When running inside Docker with DooD, use host-side skills path.
            host_skills_root = os.environ.get("DEER_FLOW_HOST_SKILLS_PATH") or str(skills_path)

            # 1. Public skills: global, read-only — static, shared by all threads
            public_skills_path = skills_path / "public"
            if public_skills_path.exists():
                mounts.append(
                    (
                        join_host_path(host_skills_root, "public"),
                        f"{container_path}/public",
                        True,
                    )
                )

            # 2. Per-user custom skills: read-only, per-thread/per-user
            effective_user_id = AioSandboxProvider._effective_acquire_user_id(user_id)
            paths = get_paths()
            user_custom_path = paths.user_custom_skills_dir(effective_user_id)
            user_custom_path.mkdir(parents=True, exist_ok=True)

            host_user_custom = join_host_path(
                str(paths.host_base_dir),
                "users",
                effective_user_id,
                "skills",
                "custom",
            )
            mounts.append(
                (
                    host_user_custom,
                    f"{container_path}/custom",
                    True,
                )
            )

            # 3. Legacy (pre-migration global-custom) skills: only mount for
            #    users who have no per-user custom skills yet, mirroring
            #    ``UserScopedSkillStorage._iter_skill_files`` visibility rule.
            legacy_skills_path = skills_path / "custom"
            if user_should_see_legacy_skills(effective_user_id, host_path=str(skills_path)) and legacy_skills_path.exists():
                mounts.append(
                    (
                        join_host_path(host_skills_root, "custom"),
                        f"{container_path}/legacy",
                        True,
                    )
                )
        except Exception as e:
            logger.warning("Could not setup skills mounts: %s", e)

        return mounts

    # ── Idle timeout management ──────────────────────────────────────────

    def _cleanup_idle_resources(self, idle_timeout: float) -> None:
        """Clean AIO resources idle longer than ``idle_timeout`` seconds."""
        self._cleanup_idle_sandboxes(idle_timeout)

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        current_time = time.time()
        active_to_destroy = []

        with self._lock:
            # Active sandboxes: tracked via _last_activity
            for sandbox_id, last_activity in self._last_activity.items():
                idle_duration = current_time - last_activity
                if idle_duration > idle_timeout:
                    active_to_destroy.append(sandbox_id)
                    logger.info(f"Sandbox {sandbox_id} idle for {idle_duration:.1f}s, marking for destroy")

        # Destroy active sandboxes (re-verify still idle before acting)
        for sandbox_id in active_to_destroy:
            try:
                # Re-verify the sandbox is still idle under the lock before destroying.
                # Between the snapshot above and here, the sandbox may have been
                # re-acquired (last_activity updated) or already released/destroyed.
                with self._lock:
                    last_activity = self._last_activity.get(sandbox_id)
                    if last_activity is None:
                        # Already released or destroyed by another path — skip.
                        logger.info(f"Sandbox {sandbox_id} already gone before idle destroy, skipping")
                        continue
                    if (time.time() - last_activity) < idle_timeout:
                        # Re-acquired (activity updated) since the snapshot — skip.
                        logger.info(f"Sandbox {sandbox_id} was re-acquired before idle destroy, skipping")
                        continue
                logger.info(f"Destroying idle sandbox {sandbox_id}")
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy idle sandbox {sandbox_id}: {e}")

        self._reap_expired_warm(idle_timeout)

    # ── Signal handling ──────────────────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown.

        Handles SIGTERM, SIGINT, and SIGHUP (terminal close) to ensure
        sandbox containers are cleaned up even when the user closes the terminal.
        """
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._original_sighup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None

        def signal_handler(signum, frame):
            self.shutdown()
            if signum == signal.SIGTERM:
                original = self._original_sigterm
            elif hasattr(signal, "SIGHUP") and signum == signal.SIGHUP:
                original = self._original_sighup
            else:
                original = self._original_sigint
            if callable(original):
                original(signum, frame)
            elif original == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, signal_handler)
        except ValueError:
            logger.debug("Could not register signal handlers (not main thread)")

    # ── Thread locking (in-process) ──────────────────────────────────────

    def _get_thread_lock(self, thread_id: str, user_id: str) -> threading.Lock:
        """Get or create an in-process lock for a specific user/thread scope."""
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            if key not in self._thread_locks:
                self._thread_locks[key] = threading.Lock()
            return self._thread_locks[key]

    def _sandbox_id_for_thread(self, thread_id: str | None, user_id: str | None) -> str:
        """Return deterministic IDs for thread sandboxes and random IDs otherwise."""
        return self._deterministic_sandbox_id(thread_id, self._effective_acquire_user_id(user_id)) if thread_id else str(uuid.uuid4())[:8]

    def _reuse_in_process_sandbox(self, thread_id: str | None, *, user_id: str | None = None, post_lock: bool = False) -> str | None:
        """Reuse an active in-process sandbox for a thread if one is still tracked."""
        if thread_id is None:
            return None

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)
        with self._lock:
            if key not in self._thread_sandboxes:
                return None

            existing_id = self._thread_sandboxes[key]
            if existing_id in self._sandboxes:
                info = self._sandbox_infos.get(existing_id)
            else:
                del self._thread_sandboxes[key]
                return None

        alive = self._check_tracked_sandbox_alive(existing_id, info) if info is not None else True
        if alive is False:
            self._drop_unhealthy_sandbox(
                existing_id,
                "in-process cache failed health check",
                expected_info=info,
            )
            return None

        with self._lock:
            if self._thread_sandboxes.get(key) != existing_id:
                return None
            if existing_id not in self._sandboxes:
                self._thread_sandboxes.pop(key, None)
                return None

            suffix = " (post-lock check)" if post_lock else ""
            logger.info(f"Reusing in-process sandbox {existing_id} for user/thread {effective_user_id}/{thread_id}{suffix}")
            self._last_activity[existing_id] = time.time()
            return existing_id

    def _reclaim_warm_pool_sandbox(
        self,
        thread_id: str | None,
        sandbox_id: str,
        *,
        user_id: str | None = None,
        post_lock: bool = False,
    ) -> str | None:
        """Promote a warm-pool sandbox back to active tracking if available."""
        if thread_id is None:
            return None

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)
        with self._lock:
            if sandbox_id not in self._warm_pool:
                return None

            info, _ = self._warm_pool[sandbox_id]

        alive = self._check_tracked_sandbox_alive(sandbox_id, info)
        if alive is False:
            self._drop_unhealthy_sandbox(
                sandbox_id,
                "warm-pool cache failed health check",
                expected_info=info,
            )
            return None

        with self._lock:
            warm_item = self._warm_pool.pop(sandbox_id, None)
            if warm_item is None:
                return None
            info, _ = warm_item
            sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            self._thread_sandboxes[key] = sandbox_id

        suffix = " (post-lock check)" if post_lock else f" at {info.sandbox_url}"
        logger.info(f"Reclaimed warm-pool sandbox {sandbox_id} for user/thread {effective_user_id}/{thread_id}{suffix}")
        return sandbox_id

    def _recheck_cached_sandbox(self, thread_id: str, sandbox_id: str, *, user_id: str) -> str | None:
        """Re-check in-memory caches after acquiring the cross-process file lock."""
        return self._reuse_in_process_sandbox(thread_id, user_id=user_id, post_lock=True) or self._reclaim_warm_pool_sandbox(
            thread_id,
            sandbox_id,
            user_id=user_id,
            post_lock=True,
        )

    def _register_discovered_sandbox(self, thread_id: str, info: SandboxInfo, *, user_id: str) -> str:
        """Track a sandbox discovered through the backend."""
        sandbox = AioSandbox(id=info.sandbox_id, base_url=info.sandbox_url)
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            self._sandboxes[info.sandbox_id] = sandbox
            self._sandbox_infos[info.sandbox_id] = info
            self._last_activity[info.sandbox_id] = time.time()
            self._thread_sandboxes[key] = info.sandbox_id

        logger.info(f"Discovered existing sandbox {info.sandbox_id} for user/thread {user_id}/{thread_id} at {info.sandbox_url}")
        return info.sandbox_id

    def _register_created_sandbox(self, thread_id: str | None, sandbox_id: str, info: SandboxInfo, *, user_id: str | None = None) -> str:
        """Track a newly-created sandbox in the active maps."""
        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[self._thread_key(thread_id, self._effective_acquire_user_id(user_id))] = sandbox_id

        logger.info(f"Created sandbox {sandbox_id} for thread {thread_id} at {info.sandbox_url}")
        return sandbox_id

    def _check_tracked_sandbox_alive(self, sandbox_id: str, info: SandboxInfo) -> bool | None:
        """Return whether a tracked sandbox appears alive, or None if unknown."""
        try:
            return self._backend.is_alive(info)
        except Exception as e:
            logger.warning(f"Failed to check sandbox {sandbox_id} health: {e}")
            return None

    def _remove_tracked_sandbox(
        self,
        sandbox_id: str,
        *,
        expected_info: SandboxInfo | None = None,
    ) -> tuple[Sandbox | None, SandboxInfo | None, bool]:
        """Remove a sandbox from in-process tracking maps.

        When expected_info is provided, removal only happens if the currently
        tracked active or warm-pool entry is the exact info object that was
        checked. This prevents a stale health-check result from deleting a
        freshly recreated sandbox with the same deterministic id.
        """
        thread_keys_to_remove: list[tuple[str, str]] = []

        with self._lock:
            active_info = self._sandbox_infos.get(sandbox_id)
            warm_item = self._warm_pool.get(sandbox_id)
            warm_info = warm_item[0] if warm_item is not None else None
            if expected_info is not None and active_info is not expected_info and warm_info is not expected_info:
                return None, None, False

            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_keys_to_remove = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in thread_keys_to_remove:
                del self._thread_sandboxes[key]
            self._last_activity.pop(sandbox_id, None)
            if info is None and sandbox_id in self._warm_pool:
                info, _ = self._warm_pool.pop(sandbox_id)
            else:
                self._warm_pool.pop(sandbox_id, None)

        return sandbox, info, True

    def _drop_unhealthy_sandbox(self, sandbox_id: str, reason: str, *, expected_info: SandboxInfo | None = None) -> None:
        """Remove and destroy a sandbox after a definitive failed health check."""
        sandbox, info, removed = self._remove_tracked_sandbox(sandbox_id, expected_info=expected_info)
        if not removed:
            logger.info(f"Skipped dropping sandbox {sandbox_id}: tracked info changed after health check")
            return

        if sandbox is not None:
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing unhealthy sandbox {sandbox_id}: {e}")

        if info is not None:
            try:
                self._backend.destroy(info)
            except Exception as e:
                logger.warning(f"Error destroying unhealthy sandbox {sandbox_id}: {e}")

        logger.warning(f"Dropped unhealthy sandbox {sandbox_id}: {reason}")

    def _active_count_locked(self) -> int:
        """Return active AIO sandbox count while ``_lock`` is held."""
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: SandboxInfo, *, reason: str) -> None:
        """Destroy a warm-pool sandbox using AIO-specific backend logging."""
        try:
            self._backend.destroy(entry)
        except Exception as e:
            if reason == "idle_timeout":
                logger.error(f"Failed to destroy idle warm-pool sandbox {sandbox_id}: {e}")
            elif reason == "replica_enforcement":
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id}: {e}")
            else:
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id} for {reason}: {e}")
            return

        if reason == "idle_timeout":
            logger.info(f"Destroyed idle warm-pool sandbox {sandbox_id}")
        elif reason == "replica_enforcement":
            logger.info(f"Destroyed warm-pool sandbox {sandbox_id}")
        else:
            logger.info(f"Destroyed warm-pool sandbox {sandbox_id} for {reason}")

    # ── Core: acquire / get / release / shutdown ─────────────────────────

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a sandbox environment and return its ID.

        For the same thread_id, this method will return the same sandbox_id
        across multiple turns, multiple processes, and (with shared storage)
        multiple pods.

        Thread-safe with both in-process and cross-process locking.

        Args:
            thread_id: Optional thread ID for thread-specific configurations.

        Returns:
            The ID of the acquired sandbox environment.
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id, effective_user_id)
            with thread_lock:
                return self._acquire_internal(thread_id, user_id=effective_user_id)
        else:
            return self._acquire_internal(thread_id, user_id=effective_user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a sandbox environment without blocking the event loop.

        Mirrors ``acquire()`` while keeping blocking backend operations off the
        event loop and using async-native readiness polling for newly created
        sandboxes.
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id, effective_user_id)
            await _acquire_thread_lock_async(thread_lock)
            try:
                return await self._acquire_internal_async(thread_id, user_id=effective_user_id)
            finally:
                thread_lock.release()

        return await self._acquire_internal_async(thread_id, user_id=effective_user_id)

    def _acquire_internal(self, thread_id: str | None, *, user_id: str) -> str:
        """Internal sandbox acquisition with two-layer consistency.

        Layer 1: In-process cache (fastest, covers same-process repeated access)
        Layer 2: Backend discovery (covers containers started by other processes;
                 sandbox_id is deterministic from thread_id so no shared state file
                 is needed — any process can derive the same container name)
        """
        cached_id = self._reuse_in_process_sandbox(thread_id, user_id=user_id)
        if cached_id is not None:
            return cached_id

        # Deterministic ID for thread-specific, random for anonymous
        sandbox_id = self._sandbox_id_for_thread(thread_id, user_id)

        # ── Layer 1.5: Warm pool (container still running, no cold-start) ──
        reclaimed_id = self._reclaim_warm_pool_sandbox(thread_id, sandbox_id, user_id=user_id)
        if reclaimed_id is not None:
            return reclaimed_id

        # ── Layer 2: Backend discovery + create (protected by cross-process lock) ──
        # Use a file lock so that two processes racing to create the same sandbox
        # for the same thread_id serialize here: the second process will discover
        # the container started by the first instead of hitting a name-conflict.
        if thread_id:
            return self._discover_or_create_with_lock(thread_id, sandbox_id, user_id=user_id)

        return self._create_sandbox(thread_id, sandbox_id, user_id=user_id)

    async def _acquire_internal_async(self, thread_id: str | None, *, user_id: str) -> str:
        """Async counterpart to ``_acquire_internal``."""
        cached_id = await asyncio.to_thread(self._reuse_in_process_sandbox, thread_id, user_id=user_id)
        if cached_id is not None:
            return cached_id

        # Deterministic ID for thread-specific, random for anonymous
        sandbox_id = self._sandbox_id_for_thread(thread_id, user_id)

        # ── Layer 1.5: Warm pool (container still running, no cold-start) ──
        reclaimed_id = await asyncio.to_thread(self._reclaim_warm_pool_sandbox, thread_id, sandbox_id, user_id=user_id)
        if reclaimed_id is not None:
            return reclaimed_id

        # ── Layer 2: Backend discovery + create (protected by cross-process lock) ──
        if thread_id:
            return await self._discover_or_create_with_lock_async(thread_id, sandbox_id, user_id=user_id)

        return await self._create_sandbox_async(thread_id, sandbox_id, user_id=user_id)

    def _discover_or_create_with_lock(self, thread_id: str, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Discover an existing sandbox or create a new one under a cross-process file lock.

        The file lock serializes concurrent sandbox creation for the same thread_id
        across multiple processes, preventing container-name conflicts.
        """
        paths = get_paths()
        effective_user_id = self._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
        lock_path = paths.thread_dir(thread_id, user_id=effective_user_id) / f"{sandbox_id}.lock"

        with open(lock_path, "a", encoding="utf-8") as lock_file:
            locked = False
            try:
                _lock_file_exclusive(lock_file)
                locked = True
                # Re-check in-process caches under the file lock in case another
                # thread in this process won the race while we were waiting.
                cached_id = self._recheck_cached_sandbox(thread_id, sandbox_id, user_id=effective_user_id)
                if cached_id is not None:
                    return cached_id

                # Backend discovery: another process may have created the container.
                discovered = self._backend.discover(sandbox_id)
                if discovered is not None:
                    return self._register_discovered_sandbox(thread_id, discovered, user_id=effective_user_id)

                return self._create_sandbox(thread_id, sandbox_id, user_id=effective_user_id)
            finally:
                if locked:
                    _unlock_file(lock_file)

    async def _discover_or_create_with_lock_async(self, thread_id: str, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Async counterpart to ``_discover_or_create_with_lock``."""
        paths = get_paths()
        effective_user_id = self._effective_acquire_user_id(user_id)
        await asyncio.to_thread(paths.ensure_thread_dirs, thread_id, user_id=effective_user_id)
        lock_path = paths.thread_dir(thread_id, user_id=effective_user_id) / f"{sandbox_id}.lock"

        lock_file = await asyncio.to_thread(_open_lock_file, lock_path)
        locked = False
        try:
            await asyncio.to_thread(_lock_file_exclusive, lock_file)
            locked = True
            # Re-check in-process caches under the file lock in case another
            # thread in this process won the race while we were waiting.
            cached_id = await asyncio.to_thread(self._recheck_cached_sandbox, thread_id, sandbox_id, user_id=effective_user_id)
            if cached_id is not None:
                return cached_id

            # Backend discovery is sync because local discovery may inspect
            # Docker and perform a health check; keep it off the event loop.
            discovered = await asyncio.to_thread(self._backend.discover, sandbox_id)
            if discovered is not None:
                return self._register_discovered_sandbox(thread_id, discovered, user_id=effective_user_id)

            return await self._create_sandbox_async(thread_id, sandbox_id, user_id=effective_user_id)
        finally:
            if locked:
                await asyncio.to_thread(_unlock_file, lock_file)
            await asyncio.to_thread(lock_file.close)

    def _create_sandbox(self, thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Create a new sandbox via the backend.

        Args:
            thread_id: Optional thread ID.
            sandbox_id: The sandbox ID to use.

        Returns:
            The sandbox_id.

        Raises:
            RuntimeError: If sandbox creation or readiness check fails.
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        extra_mounts = self._get_extra_mounts(thread_id, user_id=effective_user_id)

        # Enforce replicas: only warm-pool containers count toward eviction budget.
        # Active sandboxes are in use by live threads and must not be forcibly stopped.
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        info = self._backend.create(thread_id, sandbox_id, extra_mounts=extra_mounts or None, user_id=effective_user_id)

        # Wait for sandbox to be ready
        if not wait_for_sandbox_ready(info.sandbox_url, timeout=60):
            self._backend.destroy(info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        return self._register_created_sandbox(thread_id, sandbox_id, info, user_id=effective_user_id)

    async def _create_sandbox_async(self, thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Async counterpart to ``_create_sandbox``."""
        effective_user_id = self._effective_acquire_user_id(user_id)
        extra_mounts = await asyncio.to_thread(self._get_extra_mounts, thread_id, user_id=effective_user_id)

        # Enforce replicas: only warm-pool containers count toward eviction budget.
        # Active sandboxes are in use by live threads and must not be forcibly stopped.
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = await asyncio.to_thread(self._evict_oldest_warm)
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        info = await asyncio.to_thread(self._backend.create, thread_id, sandbox_id, extra_mounts=extra_mounts or None, user_id=effective_user_id)

        # Wait for sandbox to be ready without blocking the event loop.
        if not await wait_for_sandbox_ready_async(info.sandbox_url, timeout=60):
            await asyncio.to_thread(self._backend.destroy, info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        return self._register_created_sandbox(thread_id, sandbox_id, info, user_id=effective_user_id)

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox by ID. Updates last activity timestamp.

        Args:
            sandbox_id: The ID of the sandbox.

        Returns:
            The sandbox instance if found, None otherwise.
        """
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
            return sandbox

    def release(self, sandbox_id: str) -> None:
        """Release a sandbox from active use into the warm pool.

        The container is kept running so it can be reclaimed quickly by the same
        thread on its next turn without a cold-start.  The container will only be
        stopped when the replicas limit forces eviction or during shutdown.

        The host-side HTTP client owned by the cached ``AioSandbox`` instance is
        closed before the instance is dropped (#2872). The warm-pool entry only
        stores ``SandboxInfo``, so a fresh ``AioSandbox`` (and a fresh client)
        is constructed if the container is later reclaimed.

        Args:
            sandbox_id: The ID of the sandbox to release.
        """
        info = None
        sandbox = None
        thread_keys_to_remove: list[tuple[str, str]] = []

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_keys_to_remove = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in thread_keys_to_remove:
                del self._thread_sandboxes[key]
            self._last_activity.pop(sandbox_id, None)
            # Park in warm pool — container keeps running
            if info and sandbox_id not in self._warm_pool:
                self._warm_pool[sandbox_id] = (info, time.time())

        if sandbox is not None:
            # Defense-in-depth: close() already swallows its own errors; this
            # guard only protects against a future close() that misbehaves, so
            # host-side client cleanup can never block parking in the warm pool.
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during release: {e}")

        logger.info(f"Released sandbox {sandbox_id} to warm pool (container still running)")

    def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox: stop the container and free all resources.

        Unlike release(), this actually stops the container.  Use this for
        explicit cleanup, capacity-driven eviction, or shutdown.

        The host-side HTTP client owned by the cached ``AioSandbox`` instance is
        closed alongside backend/container destruction so no client/socket
        resources leak (#2872).

        Args:
            sandbox_id: The ID of the sandbox to destroy.
        """
        sandbox, info, _ = self._remove_tracked_sandbox(sandbox_id)

        if sandbox is not None:
            # Defense-in-depth: close() already swallows its own errors; this
            # guard only protects against a future close() that misbehaves, so
            # host-side client cleanup can never block container destruction.
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during destroy: {e}")

        if info:
            self._backend.destroy(info)
            logger.info(f"Destroyed sandbox {sandbox_id}")

    def shutdown(self) -> None:
        """Shutdown all sandboxes. Thread-safe and idempotent."""
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())
            warm_items = list(self._warm_pool.items())
            self._warm_pool.clear()

        self._stop_idle_checker()

        logger.info(f"Shutting down {len(sandbox_ids)} active + {len(warm_items)} warm-pool sandbox(es)")

        for sandbox_id in sandbox_ids:
            try:
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy sandbox {sandbox_id} during shutdown: {e}")

        for sandbox_id, (info, _) in warm_items:
            try:
                self._backend.destroy(info)
                logger.info(f"Destroyed warm-pool sandbox {sandbox_id} during shutdown")
            except Exception as e:
                logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id} during shutdown: {e}")

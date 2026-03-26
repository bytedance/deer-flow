"""AIO Sandbox Provider — orchestrates sandbox lifecycle with pluggable backends.

This provider composes:
- SandboxBackend: how sandboxes are provisioned (local container vs remote/K8s)

The provider itself handles:
- In-process caching for fast repeated access
- Idle timeout management
- Graceful shutdown with signal handling
- Mount computation (thread-specific, skills)
"""

import atexit
import fcntl
import hashlib
import logging
import os
import signal
import threading
import time
import uuid

from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, Paths, get_paths
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from .aio_sandbox import AioSandbox
from .backend import SandboxBackend, wait_for_sandbox_ready
from .local_backend import LocalContainerBackend
from .remote_backend import RemoteSandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_PORT = 8080
DEFAULT_CONTAINER_PREFIX = "deer-flow-sandbox"
DEFAULT_IDLE_TIMEOUT = 600  # 10 minutes in seconds
DEFAULT_REPLICAS = 3  # Maximum concurrent sandbox containers
IDLE_CHECK_INTERVAL = 60  # Check every 60 seconds


class AioSandboxProvider(SandboxProvider):
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
        self._thread_sandboxes: dict[str, str] = {}  # thread_id -> sandbox_id
        self._thread_locks: dict[str, threading.Lock] = {}  # thread_id -> in-process lock
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

        # Start idle checker if enabled
        if self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT) > 0:
            self._start_idle_checker()

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
            return RemoteSandboxBackend(provisioner_url=provisioner_url)

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

    # ── Deterministic ID ─────────────────────────────────────────────────

    @staticmethod
    def _deterministic_sandbox_id(thread_id: str) -> str:
        """Generate a deterministic sandbox ID from a thread ID.

        Ensures all processes derive the same sandbox_id for a given thread,
        enabling cross-process sandbox discovery without shared memory.
        """
        return hashlib.sha256(thread_id.encode()).hexdigest()[:8]

    # ── Mount helpers ────────────────────────────────────────────────────

    def _get_extra_mounts(self, thread_id: str | None) -> list[tuple[str, str, bool]]:
        """Collect all extra mounts for a sandbox (thread-specific + skills)."""
        mounts: list[tuple[str, str, bool]] = []

        if thread_id:
            mounts.extend(self._get_thread_mounts(thread_id))
            logger.info(f"Adding thread mounts for thread {thread_id}: {mounts}")

        skills_mount = self._get_skills_mount()
        if skills_mount:
            mounts.append(skills_mount)
            logger.info(f"Adding skills mount: {skills_mount}")

        return mounts

    @staticmethod
    def _get_thread_mounts(thread_id: str) -> list[tuple[str, str, bool]]:
        """Get volume mounts for a thread's data directories.

        Creates directories if they don't exist (lazy initialization).
        Mount sources use host_base_dir so that when running inside Docker with a
        mounted Docker socket (DooD), the host Docker daemon can resolve the paths.
        """
        paths = get_paths()
        paths.ensure_thread_dirs(thread_id)

        # host_paths resolves to the host-side base dir when DEER_FLOW_HOST_BASE_DIR
        # is set, otherwise falls back to the container's own base dir (native mode).
        host_paths = Paths(base_dir=paths.host_base_dir)

        return [
            (str(host_paths.sandbox_work_dir(thread_id)), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (str(host_paths.sandbox_uploads_dir(thread_id)), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (str(host_paths.sandbox_outputs_dir(thread_id)), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
            # ACP workspace: read-only inside the sandbox (lead agent reads results;
            # the ACP subprocess writes from the host side, not from within the container).
            (str(host_paths.acp_workspace_dir(thread_id)), "/mnt/acp-workspace", True),
        ]

    @staticmethod
    def _get_skills_mount() -> tuple[str, str, bool] | None:
        """Get the skills directory mount configuration.

        Mount source uses DEER_FLOW_HOST_SKILLS_PATH when running inside Docker (DooD)
        so the host Docker daemon can resolve the path.
        """
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            if skills_path.exists():
                # When running inside Docker with DooD, use host-side skills path.
                host_skills = os.environ.get("DEER_FLOW_HOST_SKILLS_PATH") or str(skills_path)
                return (host_skills, container_path, True)  # Read-only for security
        except Exception as e:
            logger.warning(f"Could not setup skills mount: {e}")
        return None

    # ── Idle timeout management ──────────────────────────────────────────

    def _start_idle_checker(self) -> None:
        """Start the background thread that checks for idle sandboxes."""
        self._idle_checker_thread = threading.Thread(
            target=self._idle_checker_loop,
            name="sandbox-idle-checker",
            daemon=True,
        )
        self._idle_checker_thread.start()
        logger.info(f"Started idle checker thread (timeout: {self._config.get('idle_timeout', DEFAULT_IDLE_TIMEOUT)}s)")

    def _idle_checker_loop(self) -> None:
        idle_timeout = self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT)
        while not self._idle_checker_stop.wait(timeout=IDLE_CHECK_INTERVAL):
            try:
                self._cleanup_idle_sandboxes(idle_timeout)
            except Exception as e:
                logger.error(f"Error in idle checker loop: {e}")

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        current_time = time.time()
        active_to_destroy = []
        warm_to_destroy: list[tuple[str, SandboxInfo]] = []

        with self._lock:
            # Active sandboxes: tracked via _last_activity
            for sandbox_id, last_activity in self._last_activity.items():
                idle_duration = current_time - last_activity
                if idle_duration > idle_timeout:
                    active_to_destroy.append(sandbox_id)
                    logger.info(f"Sandbox {sandbox_id} idle for {idle_duration:.1f}s, marking for destroy")

            # Warm pool: tracked via release_timestamp stored in _warm_pool
            for sandbox_id, (info, release_ts) in list(self._warm_pool.items()):
                warm_duration = current_time - release_ts
                if warm_duration > idle_timeout:
                    warm_to_destroy.append((sandbox_id, info))
                    del self._warm_pool[sandbox_id]
                    logger.info(f"Warm-pool sandbox {sandbox_id} idle for {warm_duration:.1f}s, marking for destroy")

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

        # Destroy warm-pool sandboxes (already removed from _warm_pool under lock above)
        for sandbox_id, info in warm_to_destroy:
            try:
                self._backend.destroy(info)
                logger.info(f"Destroyed idle warm-pool sandbox {sandbox_id}")
            except Exception as e:
                logger.error(f"Failed to destroy idle warm-pool sandbox {sandbox_id}: {e}")

    # ── Signal handling ──────────────────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)

        def signal_handler(signum, frame):
            self.shutdown()
            original = self._original_sigterm if signum == signal.SIGTERM else self._original_sigint
            if callable(original):
                original(signum, frame)
            elif original == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
        except ValueError:
            logger.debug("Could not register signal handlers (not main thread)")

    # ── Thread locking (in-process) ──────────────────────────────────────

    def _get_thread_lock(self, thread_id: str) -> threading.Lock:
        """Get or create an in-process lock for a specific thread_id."""
        with self._lock:
            if thread_id not in self._thread_locks:
                self._thread_locks[thread_id] = threading.Lock()
            return self._thread_locks[thread_id]

    # ── Core: acquire / get / release / shutdown ─────────────────────────

    def acquire(self, thread_id: str | None = None) -> str:
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
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id)
            with thread_lock:
                return self._acquire_internal(thread_id)
        else:
            return self._acquire_internal(thread_id)

    def _acquire_internal(self, thread_id: str | None) -> str:
        """Internal sandbox acquisition with two-layer consistency.

        Layer 1: In-process cache (fastest, covers same-process repeated access)
        Layer 2: Backend discovery (covers containers started by other processes;
                 sandbox_id is deterministic from thread_id so no shared state file
                 is needed — any process can derive the same container name)
        """
        # ── Layer 1: In-process cache (fast path) ──
        if thread_id:
            with self._lock:
                if thread_id in self._thread_sandboxes:
                    existing_id = self._thread_sandboxes[thread_id]
                    if existing_id in self._sandboxes:
                        logger.info(f"Reusing in-process sandbox {existing_id} for thread {thread_id}")
                        self._last_activity[existing_id] = time.time()
                        return existing_id
                    else:
                        del self._thread_sandboxes[thread_id]

        # Deterministic ID for thread-specific, random for anonymous
        sandbox_id = self._deterministic_sandbox_id(thread_id) if thread_id else str(uuid.uuid4())[:8]

        # ── Layer 1.5: Warm pool (container still running, no cold-start) ──
        if thread_id:
            with self._lock:
                if sandbox_id in self._warm_pool:
                    info, _ = self._warm_pool.pop(sandbox_id)
                    sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
                    self._sandboxes[sandbox_id] = sandbox
                    self._sandbox_infos[sandbox_id] = info
                    self._last_activity[sandbox_id] = time.time()
                    self._thread_sandboxes[thread_id] = sandbox_id
                    logger.info(f"Reclaimed warm-pool sandbox {sandbox_id} for thread {thread_id} at {info.sandbox_url}")
                    return sandbox_id

        # ── Layer 2: Backend discovery + create (protected by cross-process lock) ──
        # Use a file lock so that two processes racing to create the same sandbox
        # for the same thread_id serialize here: the second process will discover
        # the container started by the first instead of hitting a name-conflict.
        if thread_id:
            return self._discover_or_create_with_lock(thread_id, sandbox_id)

        return self._create_sandbox(thread_id, sandbox_id)

    def _discover_or_create_with_lock(self, thread_id: str, sandbox_id: str) -> str:
        """Discover an existing sandbox or create a new one under a cross-process file lock.

        The file lock serializes concurrent sandbox creation for the same thread_id
        across multiple processes, preventing container-name conflicts.
        """
        paths = get_paths()
        paths.ensure_thread_dirs(thread_id)
        lock_path = paths.thread_dir(thread_id) / f"{sandbox_id}.lock"

        with open(lock_path, "a", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                # Re-check in-process caches under the file lock in case another
                # thread in this process won the race while we were waiting.
                with self._lock:
                    if thread_id in self._thread_sandboxes:
                        existing_id = self._thread_sandboxes[thread_id]
                        if existing_id in self._sandboxes:
                            logger.info(f"Reusing in-process sandbox {existing_id} for thread {thread_id} (post-lock check)")
                            self._last_activity[existing_id] = time.time()
                            return existing_id
                    if sandbox_id in self._warm_pool:
                        info, _ = self._warm_pool.pop(sandbox_id)
                        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
                        self._sandboxes[sandbox_id] = sandbox
                        self._sandbox_infos[sandbox_id] = info
                        self._last_activity[sandbox_id] = time.time()
                        self._thread_sandboxes[thread_id] = sandbox_id
                        logger.info(f"Reclaimed warm-pool sandbox {sandbox_id} for thread {thread_id} (post-lock check)")
                        return sandbox_id

                # Backend discovery: another process may have created the container.
                discovered = self._backend.discover(sandbox_id)
                if discovered is not None:
                    sandbox = AioSandbox(id=discovered.sandbox_id, base_url=discovered.sandbox_url)
                    with self._lock:
                        self._sandboxes[discovered.sandbox_id] = sandbox
                        self._sandbox_infos[discovered.sandbox_id] = discovered
                        self._last_activity[discovered.sandbox_id] = time.time()
                        self._thread_sandboxes[thread_id] = discovered.sandbox_id
                    logger.info(f"Discovered existing sandbox {discovered.sandbox_id} for thread {thread_id} at {discovered.sandbox_url}")
                    return discovered.sandbox_id

                return self._create_sandbox(thread_id, sandbox_id)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _evict_oldest_warm(self) -> str | None:
        """Destroy the oldest container in the warm pool to free capacity.

        Returns:
            The evicted sandbox_id, or None if warm pool is empty.
        """
        with self._lock:
            if not self._warm_pool:
                return None
            oldest_id = min(self._warm_pool, key=lambda sid: self._warm_pool[sid][1])
            info, _ = self._warm_pool.pop(oldest_id)

        try:
            self._backend.destroy(info)
            logger.info(f"Destroyed warm-pool sandbox {oldest_id}")
        except Exception as e:
            logger.error(f"Failed to destroy warm-pool sandbox {oldest_id}: {e}")
            return None
        return oldest_id

    def _create_sandbox(self, thread_id: str | None, sandbox_id: str) -> str:
        """Create a new sandbox via the backend.

        Args:
            thread_id: Optional thread ID.
            sandbox_id: The sandbox ID to use.

        Returns:
            The sandbox_id.

        Raises:
            RuntimeError: If sandbox creation or readiness check fails.
        """
        extra_mounts = self._get_extra_mounts(thread_id)

        # Enforce replicas: only warm-pool containers count toward eviction budget.
        # Active sandboxes are in use by live threads and must not be forcibly stopped.
        replicas = self._config.get("replicas", DEFAULT_REPLICAS)
        with self._lock:
            total = len(self._sandboxes) + len(self._warm_pool)
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            if evicted:
                logger.info(f"Evicted warm-pool sandbox {evicted} to stay within replicas={replicas}")
            else:
                # All slots are occupied by active sandboxes — proceed anyway and log.
                # The replicas limit is a soft cap; we never forcibly stop a container
                # that is actively serving a thread.
                logger.warning(f"All {replicas} replica slots are in active use; creating sandbox {sandbox_id} beyond the soft limit")

        info = self._backend.create(thread_id, sandbox_id, extra_mounts=extra_mounts or None)

        # Wait for sandbox to be ready
        if not wait_for_sandbox_ready(info.sandbox_url, timeout=60):
            self._backend.destroy(info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[thread_id] = sandbox_id

        logger.info(f"Created sandbox {sandbox_id} for thread {thread_id} at {info.sandbox_url}")
        return sandbox_id

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

        Args:
            sandbox_id: The ID of the sandbox to release.
        """
        info = None
        thread_ids_to_remove: list[str] = []

        with self._lock:
            self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_ids_to_remove = [tid for tid, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for tid in thread_ids_to_remove:
                del self._thread_sandboxes[tid]
            self._last_activity.pop(sandbox_id, None)
            # Park in warm pool — container keeps running
            if info and sandbox_id not in self._warm_pool:
                self._warm_pool[sandbox_id] = (info, time.time())

        logger.info(f"Released sandbox {sandbox_id} to warm pool (container still running)")

    def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox: stop the container and free all resources.

        Unlike release(), this actually stops the container.  Use this for
        explicit cleanup, capacity-driven eviction, or shutdown.

        Args:
            sandbox_id: The ID of the sandbox to destroy.
        """
        info = None
        thread_ids_to_remove: list[str] = []

        with self._lock:
            self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_ids_to_remove = [tid for tid, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for tid in thread_ids_to_remove:
                del self._thread_sandboxes[tid]
            self._last_activity.pop(sandbox_id, None)
            # Also pull from warm pool if it was parked there
            if info is None and sandbox_id in self._warm_pool:
                info, _ = self._warm_pool.pop(sandbox_id)
            else:
                self._warm_pool.pop(sandbox_id, None)

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

        # Stop idle checker
        self._idle_checker_stop.set()
        if self._idle_checker_thread is not None and self._idle_checker_thread.is_alive():
            self._idle_checker_thread.join(timeout=5)
            logger.info("Stopped idle checker thread")

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

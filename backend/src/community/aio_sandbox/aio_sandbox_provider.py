"""AIO Sandbox Provider — orchestrates sandbox lifecycle with pluggable backends.

This provider composes two abstractions:
- SandboxBackend: how sandboxes are provisioned (local container vs remote/K8s)
- SandboxStateStore: how thread→sandbox mappings are persisted (file vs Redis)

The provider itself handles:
- In-process caching for fast repeated access
- Thread-safe locking (in-process + cross-process via state store)
- Idle timeout management
- Graceful shutdown with signal handling
- Mount computation (thread-specific, skills)
"""

import atexit
import hashlib
import logging
import os
import signal
import threading
import time
import uuid
from pathlib import Path

from src.config import get_app_config
from src.sandbox.consts import THREAD_DATA_BASE_DIR, VIRTUAL_PATH_PREFIX
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import SandboxProvider

from .aio_sandbox import AioSandbox
from .backend import SandboxBackend, wait_for_sandbox_ready
from .file_state_store import FileSandboxStateStore
from .local_backend import LocalContainerBackend
from .remote_backend import RemoteSandboxBackend
from .sandbox_info import SandboxInfo
from .state_store import SandboxStateStore

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_PORT = 8080
DEFAULT_CONTAINER_PREFIX = "deer-flow-sandbox"
DEFAULT_IDLE_TIMEOUT = 600  # 10 minutes in seconds
IDLE_CHECK_INTERVAL = 60  # Check every 60 seconds


class AioSandboxProvider(SandboxProvider):
    """Sandbox provider that manages containers running the AIO sandbox.

    Architecture:
        This provider composes a SandboxBackend (how to provision) and a
        SandboxStateStore (how to persist state), enabling:
        - Local Docker/Apple Container mode (auto-start containers)
        - Remote/K8s mode (connect to pre-existing sandbox URL)
        - Cross-process consistency via file-based or Redis state stores

    Configuration options in config.yaml under sandbox:
        use: src.community.aio_sandbox:AioSandboxProvider
        image: <container image>
        port: 8080                      # Base port for local containers
        base_url: http://...            # If set, uses remote backend (K8s/external)
        auto_start: true                # Whether to auto-start local containers
        container_prefix: deer-flow-sandbox
        idle_timeout: 600               # Idle timeout in seconds (0 to disable)
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
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None

        self._config = self._load_config()
        self._backend: SandboxBackend = self._create_backend()
        self._state_store: SandboxStateStore = self._create_state_store()

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
        2. ``auto_start``    → LocalContainerBackend (Docker / Apple Container)
        """
        provisioner_url = self._config.get("provisioner_url")
        if provisioner_url:
            logger.info(f"Using remote sandbox backend with provisioner at {provisioner_url}")
            return RemoteSandboxBackend(provisioner_url=provisioner_url)

        if not self._config.get("auto_start", True):
            raise RuntimeError("auto_start is disabled and no base_url is configured")

        logger.info("Using local container sandbox backend")
        return LocalContainerBackend(
            image=self._config["image"],
            base_port=self._config["port"],
            container_prefix=self._config["container_prefix"],
            config_mounts=self._config["mounts"],
            environment=self._config["environment"],
        )

    def _create_state_store(self) -> SandboxStateStore:
        """Create the state store for cross-process sandbox mapping persistence.

        Currently uses file-based store. For distributed multi-host deployments,
        a Redis-based store can be plugged in here.
        """
        # TODO: Support RedisSandboxStateStore for distributed deployments.
        #   Configuration would be:
        #     sandbox:
        #       state_store: redis
        #       redis_url: redis://localhost:6379/0
        #   This would enable cross-host sandbox discovery (e.g., multiple K8s pods
        #   without shared PVC, or multi-node Docker Swarm).
        return FileSandboxStateStore(base_dir=os.getcwd())

    # ── Configuration ────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        """Load sandbox configuration from app config."""
        config = get_app_config()
        sandbox_config = config.sandbox

        return {
            "image": sandbox_config.image or DEFAULT_IMAGE,
            "port": sandbox_config.port or DEFAULT_PORT,
            "base_url": sandbox_config.base_url,
            "auto_start": sandbox_config.auto_start if sandbox_config.auto_start is not None else True,
            "container_prefix": sandbox_config.container_prefix or DEFAULT_CONTAINER_PREFIX,
            "idle_timeout": getattr(sandbox_config, "idle_timeout", None) or DEFAULT_IDLE_TIMEOUT,
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
        """
        base_dir = os.getcwd()
        thread_dir = Path(base_dir) / THREAD_DATA_BASE_DIR / thread_id / "user-data"

        mounts = [
            (str(thread_dir / "workspace"), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (str(thread_dir / "uploads"), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (str(thread_dir / "outputs"), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
        ]

        for host_path, _, _ in mounts:
            os.makedirs(host_path, exist_ok=True)

        return mounts

    @staticmethod
    def _get_skills_mount() -> tuple[str, str, bool] | None:
        """Get the skills directory mount configuration."""
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            if skills_path.exists():
                return (str(skills_path), container_path, True)  # Read-only for security
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
        sandboxes_to_release = []

        with self._lock:
            for sandbox_id, last_activity in self._last_activity.items():
                idle_duration = current_time - last_activity
                if idle_duration > idle_timeout:
                    sandboxes_to_release.append(sandbox_id)
                    logger.info(f"Sandbox {sandbox_id} idle for {idle_duration:.1f}s, marking for release")

        for sandbox_id in sandboxes_to_release:
            try:
                logger.info(f"Releasing idle sandbox {sandbox_id}")
                self.release(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to release idle sandbox {sandbox_id}: {e}")

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
        """Internal sandbox acquisition with three-layer consistency.

        Layer 1: In-process cache (fastest, covers same-process repeated access)
        Layer 2: Cross-process state store + file lock (covers multi-process)
        Layer 3: Backend discovery (covers containers started by other processes)
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

        # ── Layer 2 & 3: Cross-process recovery + creation ──
        if thread_id:
            with self._state_store.lock(thread_id):
                # Try to recover from persisted state or discover existing container
                recovered_id = self._try_recover(thread_id)
                if recovered_id is not None:
                    return recovered_id
                # Nothing to recover — create new sandbox (still under cross-process lock)
                return self._create_sandbox(thread_id, sandbox_id)
        else:
            return self._create_sandbox(thread_id, sandbox_id)

    def _try_recover(self, thread_id: str) -> str | None:
        """Try to recover a sandbox from persisted state or backend discovery.

        Called under cross-process lock for the given thread_id.

        Args:
            thread_id: The thread ID.

        Returns:
            The sandbox_id if recovery succeeded, None otherwise.
        """
        info = self._state_store.load(thread_id)
        if info is None:
            return None

        # Re-discover: verifies sandbox is alive and gets current connection info
        # (handles cases like port changes after container restart)
        discovered = self._backend.discover(info.sandbox_id)
        if discovered is None:
            logger.info(f"Persisted sandbox {info.sandbox_id} for thread {thread_id} could not be recovered")
            self._state_store.remove(thread_id)
            return None

        # Adopt into this process's memory
        sandbox = AioSandbox(id=discovered.sandbox_id, base_url=discovered.sandbox_url)
        with self._lock:
            self._sandboxes[discovered.sandbox_id] = sandbox
            self._sandbox_infos[discovered.sandbox_id] = discovered
            self._last_activity[discovered.sandbox_id] = time.time()
            self._thread_sandboxes[thread_id] = discovered.sandbox_id

        # Update state if connection info changed
        if discovered.sandbox_url != info.sandbox_url:
            self._state_store.save(thread_id, discovered)

        logger.info(f"Recovered sandbox {discovered.sandbox_id} for thread {thread_id} at {discovered.sandbox_url}")
        return discovered.sandbox_id

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

        # Persist for cross-process discovery
        if thread_id:
            self._state_store.save(thread_id, info)

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
        """Release a sandbox: clean up in-memory state, persisted state, and backend resources.

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

        # Clean up persisted state (outside lock, involves file I/O)
        for tid in thread_ids_to_remove:
            self._state_store.remove(tid)

        # Destroy backend resources (stop container, release port, etc.)
        if info:
            self._backend.destroy(info)
            logger.info(f"Released sandbox {sandbox_id}")

    def shutdown(self) -> None:
        """Shutdown all sandboxes. Thread-safe and idempotent."""
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())

        # Stop idle checker
        self._idle_checker_stop.set()
        if self._idle_checker_thread is not None and self._idle_checker_thread.is_alive():
            self._idle_checker_thread.join(timeout=5)
            logger.info("Stopped idle checker thread")

        logger.info(f"Shutting down {len(sandbox_ids)} sandbox(es)")

        for sandbox_id in sandbox_ids:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to release sandbox {sandbox_id} during shutdown: {e}")

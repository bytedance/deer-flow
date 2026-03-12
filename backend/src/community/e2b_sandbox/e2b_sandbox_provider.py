"""E2B Sandbox Provider — manages E2B cloud sandbox lifecycle.

E2B provides secure, isolated cloud sandboxes. Each thread gets its own
sandbox instance with a full Linux environment.

Supports two lifecycle modes (configured via sandbox.mode in config.yaml):
  - "session" (default): Sandbox persists for the thread's lifetime (idle_timeout=300s).
  - "task": Short-lived sandboxes with a grace period (idle_timeout=60s).
    Outputs are synced to persistent storage (R2/local) after each agent turn,
    so files survive sandbox teardown. Can cut cloud costs by 3-4x.

Configuration in config.yaml:
    sandbox:
      use: src.community.e2b_sandbox:E2bSandboxProvider
      # Optional: Lifecycle mode (default: session)
      # mode: task
      # Optional: E2B template ID (default: base)
      # template: my-custom-template
      # Optional: Sandbox timeout in seconds (default depends on mode)
      # idle_timeout: 300
      # Optional: Environment variables to inject into the sandbox
      # environment:
      #   NODE_ENV: production
      #   API_KEY: $MY_API_KEY

Requires E2B_API_KEY in .env file.
"""

import atexit
import logging
import os
import threading
import time

from src.config import get_app_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import SandboxProvider

from .e2b_sandbox import E2bSandbox

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TIMEOUT = 300  # 5 minutes
DEFAULT_TASK_TIMEOUT = 60  # 60 second grace period
IDLE_CHECK_INTERVAL = 60  # Check every 60 seconds


class E2bSandboxProvider(SandboxProvider):
    """Sandbox provider that manages E2B cloud sandboxes.

    Each thread gets a dedicated E2B sandbox. Sandboxes are cached in-process
    and reused across multiple turns within the same thread.

    Supports two modes:
    - Session mode (default): Sandbox persists for the thread, idle timeout 5 min.
    - Task mode: Short-lived sandboxes with 60s grace period. Outputs are synced
      to persistent storage after each turn so they survive sandbox teardown.
      Re-acquisition is automatic — if sandbox was killed, a new one is created
      and files are synced from storage.

    Idle sandboxes are automatically killed after the configured timeout.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sandboxes: dict[str, E2bSandbox] = {}  # sandbox_id -> E2bSandbox
        self._thread_sandboxes: dict[str, str] = {}  # thread_id -> sandbox_id
        self._last_activity: dict[str, float] = {}  # sandbox_id -> timestamp
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None

        self._config = self._load_config()

        # Register shutdown handler
        atexit.register(self.shutdown)

        # Start idle checker
        idle_timeout = self._config.get("timeout", DEFAULT_SESSION_TIMEOUT)
        if idle_timeout > 0:
            self._start_idle_checker()

    def _load_config(self) -> dict:
        """Load E2B-specific configuration from app config."""
        config = get_app_config()
        sandbox_config = config.sandbox

        env_vars = self._resolve_env_vars(sandbox_config.environment or {})

        mode = getattr(sandbox_config, "mode", "session")
        default_timeout = DEFAULT_TASK_TIMEOUT if mode == "task" else DEFAULT_SESSION_TIMEOUT

        return {
            "template": getattr(sandbox_config, "template", None),
            "timeout": sandbox_config.idle_timeout or default_timeout,
            "environment": env_vars,
            "mode": mode,
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

    def _start_idle_checker(self) -> None:
        """Start background thread that kills idle sandboxes."""
        self._idle_checker_thread = threading.Thread(
            target=self._idle_checker_loop,
            name="e2b-idle-checker",
            daemon=True,
        )
        self._idle_checker_thread.start()

    def _idle_checker_loop(self) -> None:
        timeout = self._config.get("timeout", DEFAULT_SESSION_TIMEOUT)
        while not self._idle_checker_stop.wait(timeout=IDLE_CHECK_INTERVAL):
            try:
                self._cleanup_idle_sandboxes(timeout)
            except Exception as e:
                logger.error(f"Error in E2B idle checker: {e}")

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        current_time = time.time()
        to_release = []

        with self._lock:
            for sandbox_id, last_activity in self._last_activity.items():
                if current_time - last_activity > idle_timeout:
                    to_release.append(sandbox_id)
                    logger.info(f"E2B sandbox {sandbox_id} idle, marking for release")

        for sandbox_id in to_release:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to release idle E2B sandbox {sandbox_id}: {e}")

    def _sync_skills_to_sandbox(self, sandbox: E2bSandbox) -> None:
        """Sync skills directory to E2B sandbox (runs in background thread)."""
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path
            if skills_path.exists():
                sandbox.client.commands.run(cmd=f"sudo mkdir -p {container_path} && sudo chown -R user:user {container_path}", timeout=10)
                self._sync_local_dir_to_sandbox(sandbox, skills_path, container_path)
                logger.info(f"Skills synced to E2B sandbox {sandbox.id}")
        except Exception as e:
            logger.warning(f"Could not sync skills to E2B sandbox: {e}")

    def _sync_storage_to_sandbox(self, thread_id: str, sandbox: E2bSandbox, category: str, sandbox_dir: str) -> None:
        """Sync files from persistent storage (R2/local) into the E2B sandbox."""
        try:
            from src.storage import get_storage

            storage = get_storage()
            prefix = f"threads/{thread_id}/{category}/"
            file_infos = storage.list_files(prefix)

            for info in file_infos:
                try:
                    data = storage.read(info.path)
                    sandbox_path = f"{sandbox_dir}/{info.filename}"
                    sandbox.client.files.write(path=sandbox_path, data=data)
                    logger.debug(f"Synced {info.filename} from storage to E2B sandbox")
                except Exception as e:
                    logger.warning(f"Failed to sync {info.filename} to E2B sandbox: {e}")
        except Exception as e:
            logger.warning(f"Failed to sync {category} from storage to E2B sandbox: {e}")

    def _sync_local_dir_to_sandbox(self, sandbox: E2bSandbox, host_dir, sandbox_dir: str) -> None:
        """Sync files from a local host directory into the E2B sandbox."""
        from pathlib import Path

        host_path = Path(host_dir)
        if not host_path.exists():
            return

        for file_path in host_path.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(host_path)
                sandbox_path = f"{sandbox_dir}/{relative}"
                try:
                    content = file_path.read_bytes()
                    sandbox.client.files.write(path=sandbox_path, data=content)
                except Exception as e:
                    logger.warning(f"Failed to sync {file_path} to E2B sandbox: {e}")

    def acquire(self, thread_id: str | None = None) -> str:
        """Acquire an E2B sandbox and return its ID.

        For the same thread_id, returns the same sandbox if still alive.
        """
        from e2b import Sandbox as E2bClient

        # Check for existing sandbox
        if thread_id:
            with self._lock:
                if thread_id in self._thread_sandboxes:
                    existing_id = self._thread_sandboxes[thread_id]
                    if existing_id in self._sandboxes:
                        sandbox = self._sandboxes[existing_id]
                        try:
                            if sandbox.client.is_running():
                                logger.info(f"Reusing E2B sandbox {existing_id} for thread {thread_id}")
                                self._last_activity[existing_id] = time.time()
                                return existing_id
                        except Exception:
                            pass
                        # Sandbox is dead, clean up
                        del self._sandboxes[existing_id]
                    del self._thread_sandboxes[thread_id]

        # Create new sandbox
        create_kwargs = {}
        template = self._config.get("template")
        if template:
            create_kwargs["template"] = template
        timeout = self._config.get("timeout", DEFAULT_SESSION_TIMEOUT)
        if timeout:
            create_kwargs["timeout"] = timeout
        env_vars = self._config.get("environment", {})
        if env_vars:
            create_kwargs["envs"] = env_vars

        logger.info(f"Creating new E2B sandbox for thread {thread_id}")
        client = E2bClient.create(**create_kwargs)
        sandbox_id = client.sandbox_id

        sandbox = E2bSandbox(id=sandbox_id, client=client)

        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[thread_id] = sandbox_id

        has_template = bool(self._config.get("template"))

        if not has_template:
            # No custom template — create dirs manually (template has them pre-baked)
            dirs = [
                f"{VIRTUAL_PATH_PREFIX}/workspace",
                f"{VIRTUAL_PATH_PREFIX}/uploads",
                f"{VIRTUAL_PATH_PREFIX}/outputs",
            ]
            dir_list = " ".join(dirs)
            try:
                client.commands.run(cmd=f"sudo mkdir -p {dir_list} && sudo chown -R user:user {VIRTUAL_PATH_PREFIX}", timeout=10)
            except Exception as e:
                logger.error(f"Failed to create dirs in E2B sandbox {sandbox_id}: {e}")

        # Sync storage files synchronously — agent needs files before it runs
        if thread_id:
            self._sync_storage_to_sandbox(thread_id, sandbox, "uploads", f"{VIRTUAL_PATH_PREFIX}/uploads")
            self._sync_storage_to_sandbox(thread_id, sandbox, "workspace", f"{VIRTUAL_PATH_PREFIX}/workspace")

        # Skills sync in background — template has them pre-baked, this is only
        # for non-template sandboxes and is not needed before agent starts
        if not has_template:
            bg = threading.Thread(
                target=self._sync_skills_to_sandbox,
                args=(sandbox,),
                name=f"e2b-sync-skills-{sandbox_id}",
                daemon=True,
            )
            bg.start()

        logger.info(f"Created E2B sandbox {sandbox_id} for thread {thread_id}")
        return sandbox_id

    def get_existing(self, thread_id: str) -> str | None:
        """Get the sandbox ID for a thread if one already exists."""
        with self._lock:
            sandbox_id = self._thread_sandboxes.get(thread_id)
            if sandbox_id and sandbox_id in self._sandboxes:
                self._last_activity[sandbox_id] = time.time()
                return sandbox_id
        return None

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox by ID."""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
            return sandbox

    def release(self, sandbox_id: str) -> None:
        """Release (kill) an E2B sandbox."""
        sandbox = None
        thread_ids_to_remove: list[str] = []

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            thread_ids_to_remove = [tid for tid, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for tid in thread_ids_to_remove:
                del self._thread_sandboxes[tid]
            self._last_activity.pop(sandbox_id, None)

        if sandbox:
            try:
                sandbox.client.kill()
                logger.info(f"Killed E2B sandbox {sandbox_id}")
            except Exception as e:
                logger.error(f"Failed to kill E2B sandbox {sandbox_id}: {e}")

    def sync_outputs_to_storage(self, sandbox_id: str, thread_id: str) -> None:
        """Sync output files from E2B sandbox back to persistent storage.

        Called after each agent turn in task mode. Copies files from the sandbox's
        /mnt/user-data/outputs and /mnt/user-data/workspace directories to R2/local
        storage so they survive sandbox teardown.
        """
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return

        try:
            from src.storage import get_storage

            storage = get_storage()

            for category in ("outputs", "workspace"):
                sandbox_dir = f"{VIRTUAL_PATH_PREFIX}/{category}"
                try:
                    entries = sandbox.client.files.list(path=sandbox_dir)
                    for entry in entries:
                        if entry.type == "file":
                            try:
                                data = sandbox.client.files.read(path=entry.path, format="bytes")
                                storage_key = f"threads/{thread_id}/{category}/{entry.name}"
                                storage.write(storage_key, data)
                                logger.debug(f"Synced {entry.name} from E2B sandbox to storage")
                            except Exception as e:
                                logger.warning(f"Failed to sync {entry.name} to storage: {e}")
                except Exception as e:
                    logger.debug(f"Could not list {category} in sandbox {sandbox_id}: {e}")

            logger.info(f"Synced outputs from E2B sandbox {sandbox_id} to storage")
        except Exception as e:
            logger.warning(f"Failed to sync outputs to storage: {e}")

    def is_task_mode(self) -> bool:
        """Check if this provider is running in task-scoped mode."""
        return self._config.get("mode") == "task"

    def shutdown(self) -> None:
        """Shutdown all E2B sandboxes. Thread-safe and idempotent."""
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())

        # Stop idle checker
        self._idle_checker_stop.set()
        if self._idle_checker_thread is not None and self._idle_checker_thread.is_alive():
            self._idle_checker_thread.join(timeout=5)

        logger.info(f"Shutting down {len(sandbox_ids)} E2B sandbox(es)")
        for sandbox_id in sandbox_ids:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to release E2B sandbox {sandbox_id} during shutdown: {e}")

"""E2B Sandbox Provider — manages E2B cloud sandbox lifecycle.

E2B provides secure, isolated cloud sandboxes. Each thread gets its own
sandbox instance with a full Linux environment.

Configuration in config.yaml:
    sandbox:
      use: src.community.e2b_sandbox:E2bSandboxProvider
      # Optional: E2B template ID (default: base)
      # template: my-custom-template
      # Optional: Sandbox timeout in seconds (default: 300 = 5 minutes)
      # timeout: 300
      # Optional: Environment variables to inject into the sandbox
      # environment:
      #   NODE_ENV: production
      #   API_KEY: $MY_API_KEY

Requires E2B_API_KEY in .env file.
"""

import atexit
import logging
import os
import threading
import time

from src.config import get_app_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import SandboxProvider

from .e2b_sandbox import E2bSandbox

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # 5 minutes
IDLE_CHECK_INTERVAL = 60  # Check every 60 seconds


class E2bSandboxProvider(SandboxProvider):
    """Sandbox provider that manages E2B cloud sandboxes.

    Each thread gets a dedicated E2B sandbox. Sandboxes are cached in-process
    and reused across multiple turns within the same thread.

    Idle sandboxes are automatically killed after the configured timeout.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sandboxes: dict[str, E2bSandbox] = {}  # sandbox_id -> E2bSandbox
        self._thread_sandboxes: dict[str, str] = {}  # thread_id -> sandbox_id
        self._last_activity: dict[str, float] = {}  # sandbox_id -> timestamp
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None

        self._config = self._load_config()

        # Register shutdown handler
        atexit.register(self.shutdown)

        # Start idle checker
        idle_timeout = self._config.get("timeout", DEFAULT_TIMEOUT)
        if idle_timeout > 0:
            self._start_idle_checker()

    def _load_config(self) -> dict:
        """Load E2B-specific configuration from app config."""
        config = get_app_config()
        sandbox_config = config.sandbox

        env_vars = self._resolve_env_vars(sandbox_config.environment or {})

        return {
            "template": getattr(sandbox_config, "template", None),
            "timeout": sandbox_config.idle_timeout or DEFAULT_TIMEOUT,
            "environment": env_vars,
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

    def _start_idle_checker(self) -> None:
        """Start background thread that kills idle sandboxes."""
        self._idle_checker_thread = threading.Thread(
            target=self._idle_checker_loop,
            name="e2b-idle-checker",
            daemon=True,
        )
        self._idle_checker_thread.start()

    def _idle_checker_loop(self) -> None:
        timeout = self._config.get("timeout", DEFAULT_TIMEOUT)
        while not self._idle_checker_stop.wait(timeout=IDLE_CHECK_INTERVAL):
            try:
                self._cleanup_idle_sandboxes(timeout)
            except Exception as e:
                logger.error(f"Error in E2B idle checker: {e}")

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        current_time = time.time()
        to_release = []

        with self._lock:
            for sandbox_id, last_activity in self._last_activity.items():
                if current_time - last_activity > idle_timeout:
                    to_release.append(sandbox_id)
                    logger.info(f"E2B sandbox {sandbox_id} idle, marking for release")

        for sandbox_id in to_release:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to release idle E2B sandbox {sandbox_id}: {e}")

    def _sync_skills_to_sandbox(self, sandbox: E2bSandbox) -> None:
        """Sync skills directory to E2B sandbox (runs in background thread)."""
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path
            if skills_path.exists():
                sandbox.client.commands.run(cmd=f"sudo mkdir -p {container_path} && sudo chown -R user:user {container_path}", timeout=10)
                self._sync_local_dir_to_sandbox(sandbox, skills_path, container_path)
                logger.info(f"Skills synced to E2B sandbox {sandbox.id}")
        except Exception as e:
            logger.warning(f"Could not sync skills to E2B sandbox: {e}")

    def _sync_storage_to_sandbox(self, thread_id: str, sandbox: E2bSandbox, category: str, sandbox_dir: str) -> None:
        """Sync files from persistent storage (R2/local) into the E2B sandbox."""
        try:
            from src.storage import get_storage

            storage = get_storage()
            prefix = f"threads/{thread_id}/{category}/"
            file_infos = storage.list_files(prefix)

            for info in file_infos:
                try:
                    data = storage.read(info.path)
                    sandbox_path = f"{sandbox_dir}/{info.filename}"
                    sandbox.client.files.write(path=sandbox_path, data=data)
                    logger.debug(f"Synced {info.filename} from storage to E2B sandbox")
                except Exception as e:
                    logger.warning(f"Failed to sync {info.filename} to E2B sandbox: {e}")
        except Exception as e:
            logger.warning(f"Failed to sync {category} from storage to E2B sandbox: {e}")

    def _sync_local_dir_to_sandbox(self, sandbox: E2bSandbox, host_dir, sandbox_dir: str) -> None:
        """Sync files from a local host directory into the E2B sandbox."""
        from pathlib import Path

        host_path = Path(host_dir)
        if not host_path.exists():
            return

        for file_path in host_path.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(host_path)
                sandbox_path = f"{sandbox_dir}/{relative}"
                try:
                    content = file_path.read_bytes()
                    sandbox.client.files.write(path=sandbox_path, data=content)
                except Exception as e:
                    logger.warning(f"Failed to sync {file_path} to E2B sandbox: {e}")

    def acquire(self, thread_id: str | None = None) -> str:
        """Acquire an E2B sandbox and return its ID.

        For the same thread_id, returns the same sandbox if still alive.
        """
        from e2b import Sandbox as E2bClient

        # Check for existing sandbox
        if thread_id:
            with self._lock:
                if thread_id in self._thread_sandboxes:
                    existing_id = self._thread_sandboxes[thread_id]
                    if existing_id in self._sandboxes:
                        sandbox = self._sandboxes[existing_id]
                        try:
                            if sandbox.client.is_running():
                                logger.info(f"Reusing E2B sandbox {existing_id} for thread {thread_id}")
                                self._last_activity[existing_id] = time.time()
                                return existing_id
                        except Exception:
                            pass
                        # Sandbox is dead, clean up
                        del self._sandboxes[existing_id]
                    del self._thread_sandboxes[thread_id]

        # Create new sandbox
        create_kwargs = {}
        template = self._config.get("template")
        if template:
            create_kwargs["template"] = template
        timeout = self._config.get("timeout", DEFAULT_TIMEOUT)
        if timeout:
            create_kwargs["timeout"] = timeout
        env_vars = self._config.get("environment", {})
        if env_vars:
            create_kwargs["envs"] = env_vars

        logger.info(f"Creating new E2B sandbox for thread {thread_id}")
        client = E2bClient.create(**create_kwargs)
        sandbox_id = client.sandbox_id

        sandbox = E2bSandbox(id=sandbox_id, client=client)

        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[thread_id] = sandbox_id

        has_template = bool(self._config.get("template"))

        if not has_template:
            # No custom template — create dirs manually (template has them pre-baked)
            dirs = [
                f"{VIRTUAL_PATH_PREFIX}/workspace",
                f"{VIRTUAL_PATH_PREFIX}/uploads",
                f"{VIRTUAL_PATH_PREFIX}/outputs",
            ]
            dir_list = " ".join(dirs)
            try:
                client.commands.run(cmd=f"sudo mkdir -p {dir_list} && sudo chown -R user:user {VIRTUAL_PATH_PREFIX}", timeout=10)
            except Exception as e:
                logger.error(f"Failed to create dirs in E2B sandbox {sandbox_id}: {e}")

        # Sync storage files synchronously — agent needs files before it runs
        if thread_id:
            self._sync_storage_to_sandbox(thread_id, sandbox, "uploads", f"{VIRTUAL_PATH_PREFIX}/uploads")
            self._sync_storage_to_sandbox(thread_id, sandbox, "workspace", f"{VIRTUAL_PATH_PREFIX}/workspace")

        # Skills sync in background — template has them pre-baked, this is only
        # for non-template sandboxes and is not needed before agent starts
        if not has_template:
            bg = threading.Thread(
                target=self._sync_skills_to_sandbox,
                args=(sandbox,),
                name=f"e2b-sync-skills-{sandbox_id}",
                daemon=True,
            )
            bg.start()

        logger.info(f"Created E2B sandbox {sandbox_id} for thread {thread_id}")
        return sandbox_id

    def get_existing(self, thread_id: str) -> str | None:
        """Get the sandbox ID for a thread if one already exists."""
        with self._lock:
            sandbox_id = self._thread_sandboxes.get(thread_id)
            if sandbox_id and sandbox_id in self._sandboxes:
                self._last_activity[sandbox_id] = time.time()
                return sandbox_id
        return None

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox by ID."""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
            return sandbox

    def release(self, sandbox_id: str) -> None:
        """Release (kill) an E2B sandbox."""
        sandbox = None
        thread_ids_to_remove: list[str] = []

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            thread_ids_to_remove = [tid for tid, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for tid in thread_ids_to_remove:
                del self._thread_sandboxes[tid]
            self._last_activity.pop(sandbox_id, None)

        if sandbox:
            try:
                sandbox.client.kill()
                logger.info(f"Killed E2B sandbox {sandbox_id}")
            except Exception as e:
                logger.error(f"Failed to kill E2B sandbox {sandbox_id}: {e}")

    def shutdown(self) -> None:
        """Shutdown all E2B sandboxes. Thread-safe and idempotent."""
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())

        # Stop idle checker
        self._idle_checker_stop.set()
        if self._idle_checker_thread is not None and self._idle_checker_thread.is_alive():
            self._idle_checker_thread.join(timeout=5)

        logger.info(f"Shutting down {len(sandbox_ids)} E2B sandbox(es)")
        for sandbox_id in sandbox_ids:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to release E2B sandbox {sandbox_id} during shutdown: {e}")

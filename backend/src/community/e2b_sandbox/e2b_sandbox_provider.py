"""E2B Sandbox Provider — manages E2B cloud sandbox lifecycle.

E2B provides secure, isolated cloud sandboxes. Each thread gets its own
sandbox instance with a full Linux environment.

Supports two lifecycle modes (configured via sandbox.mode in config.yaml):
  - "session" (default): Sandbox persists for the thread's lifetime (idle_timeout=300s).
  - "task": Short-lived sandboxes with a grace period (idle_timeout=60s).
    Outputs are synced to durable thread-file storage after each agent turn,
    so files survive sandbox teardown.

Requires E2B_API_KEY in .env file.
"""

import atexit
import logging
import os
import threading
import time

from src.config import get_app_config
from src.config.paths import VIRTUAL_PATH_PREFIX
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import SandboxProvider
from src.storage import get_thread_file_backend

from .e2b_sandbox import E2bSandbox

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TIMEOUT = 300
DEFAULT_TASK_TIMEOUT = 60
IDLE_CHECK_INTERVAL = 60


class E2bSandboxProvider(SandboxProvider):
    """Sandbox provider that manages E2B cloud sandboxes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sandboxes: dict[str, E2bSandbox] = {}
        self._thread_sandboxes: dict[str, str] = {}
        self._last_activity: dict[str, float] = {}
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None

        self._config = self._load_config()

        atexit.register(self.shutdown)

        idle_timeout = self._config.get("timeout", DEFAULT_SESSION_TIMEOUT)
        if idle_timeout > 0:
            self._start_idle_checker()

    def _load_config(self) -> dict:
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
        resolved = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                env_name = value[1:]
                resolved[key] = os.environ.get(env_name, "")
            else:
                resolved[key] = str(value)
        return resolved

    def _start_idle_checker(self) -> None:
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
                logger.error("Error in E2B idle checker: %s", e)

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        current_time = time.time()
        to_release = []

        with self._lock:
            for sandbox_id, last_activity in self._last_activity.items():
                if current_time - last_activity > idle_timeout:
                    to_release.append(sandbox_id)
                    logger.info("E2B sandbox %s idle, marking for release", sandbox_id)

        for sandbox_id in to_release:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error("Failed to release idle E2B sandbox %s: %s", sandbox_id, e)

    def _sync_skills_to_sandbox(self, sandbox: E2bSandbox) -> None:
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path
            if skills_path.exists():
                sandbox.client.commands.run(cmd=f"sudo mkdir -p {container_path} && sudo chown -R user:user {container_path}", timeout=10)
                self._sync_local_dir_to_sandbox(sandbox, skills_path, container_path)
                logger.info("Skills synced to E2B sandbox %s", sandbox.id)
        except Exception as e:
            logger.warning("Could not sync skills to E2B sandbox: %s", e)

    def _sync_storage_to_sandbox(self, thread_id: str, sandbox: E2bSandbox, category: str) -> None:
        """Sync files from durable thread-file backend into E2B sandbox."""
        try:
            feature = "uploads" if category == "uploads" else "workspace"
            backend = get_thread_file_backend(feature)
            virtual_dir = f"{VIRTUAL_PATH_PREFIX}/{category}"
            files = backend.list_virtual_files(thread_id, virtual_dir)

            for item in files:
                try:
                    data = backend.read_virtual_file(thread_id, item.virtual_path)
                    sandbox.client.files.write(path=item.virtual_path, data=data)
                    logger.debug("Synced %s to E2B sandbox", item.virtual_path)
                except Exception as e:
                    logger.warning("Failed to sync %s to E2B sandbox: %s", item.virtual_path, e)
        except Exception as e:
            logger.warning("Failed to sync %s from durable backend to E2B sandbox: %s", category, e)

    def _sync_local_dir_to_sandbox(self, sandbox: E2bSandbox, host_dir, sandbox_dir: str) -> None:
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
                    logger.warning("Failed to sync %s to E2B sandbox: %s", file_path, e)

    def acquire(self, thread_id: str | None = None) -> str:
        from e2b import Sandbox as E2bClient

        if thread_id:
            with self._lock:
                if thread_id in self._thread_sandboxes:
                    existing_id = self._thread_sandboxes[thread_id]
                    if existing_id in self._sandboxes:
                        sandbox = self._sandboxes[existing_id]
                        try:
                            if sandbox.client.is_running():
                                logger.info("Reusing E2B sandbox %s for thread %s", existing_id, thread_id)
                                self._last_activity[existing_id] = time.time()
                                return existing_id
                        except Exception:
                            pass
                        del self._sandboxes[existing_id]
                    del self._thread_sandboxes[thread_id]

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

        logger.info("Creating new E2B sandbox for thread %s", thread_id)
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
            dirs = [
                f"{VIRTUAL_PATH_PREFIX}/workspace",
                f"{VIRTUAL_PATH_PREFIX}/uploads",
                f"{VIRTUAL_PATH_PREFIX}/outputs",
            ]
            dir_list = " ".join(dirs)
            try:
                client.commands.run(cmd=f"sudo mkdir -p {dir_list} && sudo chown -R user:user {VIRTUAL_PATH_PREFIX}", timeout=10)
            except Exception as e:
                logger.error("Failed to create dirs in E2B sandbox %s: %s", sandbox_id, e)

        if thread_id:
            self._sync_storage_to_sandbox(thread_id, sandbox, "uploads")
            self._sync_storage_to_sandbox(thread_id, sandbox, "workspace")

        if not has_template:
            bg = threading.Thread(
                target=self._sync_skills_to_sandbox,
                args=(sandbox,),
                name=f"e2b-sync-skills-{sandbox_id}",
                daemon=True,
            )
            bg.start()

        logger.info("Created E2B sandbox %s for thread %s", sandbox_id, thread_id)
        return sandbox_id

    def get_existing(self, thread_id: str) -> str | None:
        with self._lock:
            sandbox_id = self._thread_sandboxes.get(thread_id)
            if sandbox_id and sandbox_id in self._sandboxes:
                self._last_activity[sandbox_id] = time.time()
                return sandbox_id
        return None

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
            return sandbox

    def release(self, sandbox_id: str) -> None:
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
                logger.info("Killed E2B sandbox %s", sandbox_id)
            except Exception as e:
                logger.error("Failed to kill E2B sandbox %s: %s", sandbox_id, e)

    def sync_outputs_to_storage(self, sandbox_id: str, thread_id: str) -> None:
        """Sync outputs/workspace from E2B sandbox back to durable thread-file backend."""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return

        categories = (
            ("outputs", "outputs"),
            ("workspace", "workspace"),
        )

        for category, feature in categories:
            backend = get_thread_file_backend(feature)
            sandbox_dir = f"{VIRTUAL_PATH_PREFIX}/{category}"
            try:
                entries = sandbox.client.files.list(path=sandbox_dir)
            except Exception as e:
                logger.debug("Could not list %s in sandbox %s: %s", category, sandbox_id, e)
                continue

            for entry in entries:
                if entry.type != "file":
                    continue
                try:
                    data = sandbox.client.files.read(path=entry.path, format="bytes")
                    backend.put_virtual_file(thread_id, entry.path, data)
                    logger.debug("Synced %s from E2B sandbox to durable backend", entry.path)
                except Exception as e:
                    logger.warning("Failed to sync %s to durable backend: %s", entry.path, e)

        logger.info("Synced outputs/workspace from E2B sandbox %s", sandbox_id)

    def is_task_mode(self) -> bool:
        return self._config.get("mode") == "task"

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())

        self._idle_checker_stop.set()
        if self._idle_checker_thread is not None and self._idle_checker_thread.is_alive():
            self._idle_checker_thread.join(timeout=5)

        logger.info("Shutting down %s E2B sandbox(es)", len(sandbox_ids))
        for sandbox_id in sandbox_ids:
            try:
                self.release(sandbox_id)
            except Exception as e:
                logger.error("Failed to release E2B sandbox %s during shutdown: %s", sandbox_id, e)

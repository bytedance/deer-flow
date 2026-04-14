import os
import re
import shutil
from pathlib import Path, PureWindowsPath

# Virtual path prefix seen by agents inside the sandbox
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _default_local_base_dir() -> Path:
    """Return the repo-local DeerFlow state directory without relying on cwd."""
    backend_dir = Path(__file__).resolve().parents[4]
    return backend_dir / ".deer-flow"


def _validate_thread_id(thread_id: str) -> str:
    """Validate a thread ID before using it in filesystem paths."""
    if not _SAFE_THREAD_ID_RE.match(thread_id):
        raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return thread_id


def _join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style.

    Docker Desktop on Windows expects bind mount sources to stay in Windows
    path form (for example ``C:\\repo\\backend\\.deer-flow``).  Using
    ``Path(base) / ...`` on a POSIX host can accidentally rewrite those paths
    with mixed separators, so this helper preserves the original style.
    """
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


def join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style."""
    return _join_host_path(base, *parts)


class Paths:
    """
    Centralized path configuration for DeerFlow application data.

    Directory layout (host side):
        {base_dir}/
        ├── memory.json
        ├── USER.md          <-- global user profile (injected into all agents)
        ├── agents/
        │   └── {agent_name}/
        │       ├── config.yaml
        │       ├── SOUL.md  <-- agent personality/identity (injected alongside lead prompt)
        │       └── memory.json
        └── threads/
            └── {thread_id}/
                └── user-data/         <-- mounted as /mnt/user-data/ inside sandbox
                    ├── workspace/     <-- /mnt/user-data/workspace/
                    ├── uploads/       <-- /mnt/user-data/uploads/
                    └── outputs/       <-- /mnt/user-data/outputs/

    BaseDir resolution (in priority order):
        1. Constructor argument `base_dir`
        2. DEER_FLOW_HOME environment variable
        3. Repo-local fallback derived from this module path: `{backend_dir}/.deer-flow`
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        """Host-visible base dir for Docker volume mount sources.

        When running inside Docker with a mounted Docker socket (DooD), the Docker
        daemon runs on the host and resolves mount paths against the host filesystem.
        Set DEER_FLOW_HOST_BASE_DIR to the host-side path that corresponds to this
        container's base_dir so that sandbox container volume mounts work correctly.

        Falls back to base_dir when the env var is not set (native/local execution).
        """
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    def _host_base_dir_str(self) -> str:
        """Return the host base dir as a raw string for bind mounts."""
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return env
        return str(self.base_dir)

    @property
    def base_dir(self) -> Path:
        """Root directory for all application data."""
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        return _default_local_base_dir()

    @property
    def memory_file(self) -> Path:
        """Path to the persisted memory file: `{base_dir}/memory.json`."""
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """Path to the global user profile file: `{base_dir}/USER.md`."""
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """Root directory for all custom agents: `{base_dir}/agents/`."""
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        """Directory for a specific agent: `{base_dir}/agents/{name}/`."""
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """Per-agent memory file: `{base_dir}/agents/{name}/memory.json`."""
        return self.agent_dir(name) / "memory.json"

    def thread_dir(self, thread_id: str) -> Path:
        """
        Host path for a thread's data: `{base_dir}/threads/{thread_id}/`

        This directory contains a `user-data/` subdirectory that is mounted
        as `/mnt/user-data/` inside the sandbox.

        Raises:
            ValueError: If `thread_id` contains unsafe characters (path separators
                        or `..`) that could cause directory traversal.
        """
        return self.base_dir / "threads" / _validate_thread_id(thread_id)

    def sandbox_work_dir(self, thread_id: str) -> Path:
        """
        Host path for the agent's workspace directory.
        Host: `{base_dir}/threads/{thread_id}/user-data/workspace/`
        Sandbox: `/mnt/user-data/workspace/`
        """
        return self.thread_dir(thread_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str) -> Path:
        """
        Host path for user-uploaded files.
        Host: `{base_dir}/threads/{thread_id}/user-data/uploads/`
        Sandbox: `/mnt/user-data/uploads/`
        """
        return self.thread_dir(thread_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str) -> Path:
        """
        Host path for agent-generated artifacts.
        Host: `{base_dir}/threads/{thread_id}/user-data/outputs/`
        Sandbox: `/mnt/user-data/outputs/`
        """
        return self.thread_dir(thread_id) / "user-data" / "outputs"

    def acp_workspace_dir(self, thread_id: str) -> Path:
        """
        Host path for the ACP workspace of a specific thread.
        Host: `{base_dir}/threads/{thread_id}/acp-workspace/`
        Sandbox: `/mnt/acp-workspace/`

        Each thread gets its own isolated ACP workspace so that concurrent
        sessions cannot read each other's ACP agent outputs.
        """
        return self.thread_dir(thread_id) / "acp-workspace"

    def sandbox_user_data_dir(self, thread_id: str) -> Path:
        """
        Host path for the user-data root.
        Host: `{base_dir}/threads/{thread_id}/user-data/`
        Sandbox: `/mnt/user-data/`
        """
        return self.thread_dir(thread_id) / "user-data"

    def host_thread_dir(self, thread_id: str) -> str:
        """Host path for a thread directory, preserving Windows path syntax."""
        return _join_host_path(self._host_base_dir_str(), "threads", _validate_thread_id(thread_id))

    def host_sandbox_user_data_dir(self, thread_id: str) -> str:
        """Host path for a thread's user-data root."""
        return _join_host_path(self.host_thread_dir(thread_id), "user-data")

    def host_sandbox_work_dir(self, thread_id: str) -> str:
        """Host path for the workspace mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id), "workspace")

    def host_sandbox_uploads_dir(self, thread_id: str) -> str:
        """Host path for the uploads mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id), "uploads")

    def host_sandbox_outputs_dir(self, thread_id: str) -> str:
        """Host path for the outputs mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id), "outputs")

    def host_acp_workspace_dir(self, thread_id: str) -> str:
        """Host path for the ACP workspace mount source."""
        return _join_host_path(self.host_thread_dir(thread_id), "acp-workspace")

    def ensure_thread_dirs(self, thread_id: str) -> None:
        """Create all standard sandbox directories for a thread.

        Directories are created with mode 0o777 so that sandbox containers
        (which may run as a different UID than the host backend process) can
        write to the volume-mounted paths without "Permission denied" errors.
        The explicit chmod() call is necessary because Path.mkdir(mode=...) is
        subject to the process umask and may not yield the intended permissions.

        Includes the ACP workspace directory so it can be volume-mounted into
        the sandbox container at ``/mnt/acp-workspace`` even before the first
        ACP agent invocation.
        """
        for d in [
            self.sandbox_work_dir(thread_id),
            self.sandbox_uploads_dir(thread_id),
            self.sandbox_outputs_dir(thread_id),
            self.acp_workspace_dir(thread_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    def delete_thread_dir(self, thread_id: str) -> None:
        """Delete all persisted data for a thread.

        The operation is idempotent: missing thread directories are ignored.
        """
        thread_dir = self.thread_dir(thread_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str) -> Path:
        """Resolve a sandbox virtual path to the actual host filesystem path.

        Args:
            thread_id: The thread ID.
            virtual_path: Virtual path as seen inside the sandbox, e.g.
                          ``/mnt/user-data/outputs/report.pdf``.
                          Leading slashes are stripped before matching.

        Returns:
            The resolved absolute host filesystem path.

        Raises:
            ValueError: If the path does not start with the expected virtual
                        prefix or a path-traversal attempt is detected.
        """
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        # Require an exact segment-boundary match to avoid prefix confusion
        # (e.g. reject paths like "mnt/user-dataX/...").
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual


# ── Singleton ────────────────────────────────────────────────────────────

_paths: Paths | None = None


def get_paths() -> Paths:
    """Return the global Paths singleton (lazy-initialized)."""
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """Resolve *path* to an absolute ``Path``.

    Relative paths are resolved relative to the application base directory.
    Absolute paths are returned as-is (after normalisation).
    """
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()

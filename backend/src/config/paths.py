import os
from pathlib import Path

# Virtual path prefix seen by agents inside the sandbox
VIRTUAL_PATH_PREFIX = "/mnt/user-data"


class Paths:
    """
    Centralized path configuration for DeerFlow application data.

    Directory layout (host side):
        {base_dir}/
        ├── memory.json
        └── threads/
            └── {thread_id}/          <-- mounted as /mnt/ inside sandbox
                └── user-data/
                    ├── workspace/     <-- /mnt/user-data/workspace/
                    ├── uploads/       <-- /mnt/user-data/uploads/
                    └── outputs/       <-- /mnt/user-data/outputs/

    BaseDir resolution (in priority order):
        1. Constructor argument `base_dir`
        2. DEER_FLOW_HOME environment variable
        3. Local dev fallback: cwd/.deer-flow  (when cwd is the backend/ dir)
        4. Default: $HOME/.deer-flow
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def base_dir(self) -> Path:
        """Root directory for all application data."""
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        cwd = Path.cwd()
        if cwd.name == "backend" or (cwd / "pyproject.toml").exists():
            return cwd / ".deer-flow"

        return Path.home() / ".deer-flow"

    @property
    def memory_file(self) -> Path:
        """Path to the persisted memory file: `{base_dir}/memory.json`."""
        return self.base_dir / "memory.json"

    def thread_dir(self, thread_id: str) -> Path:
        """
        Host path for a thread's data: `{base_dir}/threads/{thread_id}/`

        This directory is mounted as `/mnt/` inside the sandbox.
        """
        return self.base_dir / "threads" / thread_id

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

    def sandbox_user_data_dir(self, thread_id: str) -> Path:
        """
        Host path for the user-data root.
        Host: `{base_dir}/threads/{thread_id}/user-data/`
        Sandbox: `/mnt/user-data/`
        """
        return self.thread_dir(thread_id) / "user-data"

    def ensure_thread_dirs(self, thread_id: str) -> None:
        """Create all standard sandbox directories for a thread."""
        self.sandbox_work_dir(thread_id).mkdir(parents=True, exist_ok=True)
        self.sandbox_uploads_dir(thread_id).mkdir(parents=True, exist_ok=True)
        self.sandbox_outputs_dir(thread_id).mkdir(parents=True, exist_ok=True)

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

        if not stripped.startswith(prefix):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id)
        actual = (base / relative).resolve()

        if not str(actual).startswith(str(base.resolve())):
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

import os
import re
from pathlib import Path

#    Virtual 路径 prefix seen by agents inside the sandbox


VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


class Paths:
    """
    Centralized 路径 configuration for DeerFlow application 数据.

    Directory layout (host side):
        {base_dir}/
        ├── 内存.json
        ├── USER.md          <-- global 用户 profile (injected into all agents)
        ├── agents/
        │   └── {agent_name}/
        │       ├── 配置.yaml
        │       ├── SOUL.md  <-- 代理 personality/identity (injected alongside lead 提示词)
        │       └── 内存.json
        └── threads/
            └── {thread_id}/
                └── 用户-数据/         <-- mounted as /mnt/用户-数据/ inside sandbox
                    ├── 工作区/     <-- /mnt/用户-数据/工作区/
                    ├── uploads/       <-- /mnt/用户-数据/uploads/
                    └── outputs/       <-- /mnt/用户-数据/outputs/

    BaseDir resolution (in priority order):
        1. Constructor 参数 `base_dir`
        2. DEER_FLOW_HOME 环境 变量
        3. Local dev 回退: cwd/.deer-flow  (when cwd is the 后端/ dir)
        4. Default: $HOME/.deer-flow
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        """Host-可见 base dir for Docker volume mount sources.

        When running inside Docker with a mounted Docker socket (DooD), the Docker
        daemon runs on the host and resolves mount paths against the host filesystem.
        Set DEER_FLOW_HOST_BASE_DIR to the host-side 路径 that corresponds to this
        container's base_dir so that sandbox container volume mounts work correctly.

        Falls back to base_dir when the env var is not 集合 (native/local execution).
        """
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    @property
    def base_dir(self) -> Path:
        """Root 目录 for all application 数据."""
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
        """Path to the persisted 内存 文件: `{base_dir}/内存.json`."""
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """Path to the global 用户 profile 文件: `{base_dir}/USER.md`."""
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """Root 目录 for all custom agents: `{base_dir}/agents/`."""
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        """Directory for a specific 代理: `{base_dir}/agents/{名称}/`."""
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """Per-代理 内存 文件: `{base_dir}/agents/{名称}/内存.json`."""
        return self.agent_dir(name) / "memory.json"

    def thread_dir(self, thread_id: str) -> Path:
        """
        Host 路径 for a 线程's 数据: `{base_dir}/threads/{thread_id}/`

        This 目录 contains a `用户-数据/` subdirectory that is mounted
        as `/mnt/用户-数据/` inside the sandbox.

        Raises:
            ValueError: If `thread_id` contains unsafe characters (路径 separators
                        or `..`) that could cause 目录 traversal.
        """
        if not _SAFE_THREAD_ID_RE.match(thread_id):
            raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
        return self.base_dir / "threads" / thread_id

    def sandbox_work_dir(self, thread_id: str) -> Path:
        """
        Host 路径 for the 代理's 工作区 目录.
        Host: `{base_dir}/threads/{thread_id}/用户-数据/工作区/`
        Sandbox: `/mnt/用户-数据/工作区/`
        """
        return self.thread_dir(thread_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str) -> Path:
        """
        Host 路径 for 用户-uploaded files.
        Host: `{base_dir}/threads/{thread_id}/用户-数据/uploads/`
        Sandbox: `/mnt/用户-数据/uploads/`
        """
        return self.thread_dir(thread_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str) -> Path:
        """
        Host 路径 for 代理-generated artifacts.
        Host: `{base_dir}/threads/{thread_id}/用户-数据/outputs/`
        Sandbox: `/mnt/用户-数据/outputs/`
        """
        return self.thread_dir(thread_id) / "user-data" / "outputs"

    def sandbox_user_data_dir(self, thread_id: str) -> Path:
        """
        Host 路径 for the 用户-数据 root.
        Host: `{base_dir}/threads/{thread_id}/用户-数据/`
        Sandbox: `/mnt/用户-数据/`
        """
        return self.thread_dir(thread_id) / "user-data"

    def ensure_thread_dirs(self, thread_id: str) -> None:
        """Create all standard sandbox directories for a 线程.

        Directories are created with mode 0o777 so that sandbox containers
        (which may 运行 as a different UID than the host 后端 处理) can
        write to the volume-mounted paths without "Permission denied" errors.
        The explicit chmod() call is necessary because Path.mkdir(mode=...) is
        subject to the 处理 umask and may not yield the intended permissions.
        """
        for d in [
            self.sandbox_work_dir(thread_id),
            self.sandbox_uploads_dir(thread_id),
            self.sandbox_outputs_dir(thread_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str) -> Path:
        """Resolve a sandbox virtual 路径 to the actual host filesystem 路径.

        Args:
            thread_id: The 线程 ID.
            virtual_path: Virtual 路径 as seen inside the sandbox, e.g.
                          ``/mnt/用户-数据/outputs/report.pdf``.
                          Leading slashes are stripped before matching.

        Returns:
            The resolved absolute host filesystem 路径.

        Raises:
            ValueError: If the 路径 does not 开始 with the expected virtual
                        prefix or a 路径-traversal attempt is detected.
        """
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        #    Require an exact segment-boundary match to avoid prefix confusion


        #    (e.g. reject paths like "mnt/用户-dataX/...").


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


#    ── Singleton ────────────────────────────────────────────────────────────



_paths: Paths | None = None


def get_paths() -> Paths:
    """Return the global Paths singleton (lazy-initialized)."""
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """Resolve *路径* to an absolute ``Path``.

    Relative paths are resolved relative to the application base 目录.
    Absolute paths are returned as-is (after normalisation).
    """
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

# Virtual path prefix seen by agents inside the sandbox
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


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
        3. Local dev fallback: cwd/.deer-flow  (when cwd is the backend/ dir)
        4. Default: $HOME/.deer-flow
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

    # ── User-level paths ────────────────────────────────────────────────

    def user_dir(self, user_id: str) -> Path:
        """Directory for a specific user: `{base_dir}/users/{user_id}/`.

        Raises:
            ValueError: If `user_id` contains unsafe characters.
        """
        if not _SAFE_USER_ID_RE.match(user_id):
            raise ValueError(f"Invalid user_id {user_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
        return self.base_dir / "users" / user_id

    def user_memory_file(self, user_id: str) -> Path:
        """Per-user long-term memory file: `{base_dir}/users/{user_id}/memory.json`."""
        return self.user_dir(user_id) / "memory.json"

    def user_agent_memory_file(self, user_id: str, agent_name: str) -> Path:
        """Per-user, per-agent memory file: `{base_dir}/users/{user_id}/agents/{name}/memory.json`."""
        return self.user_dir(user_id) / "agents" / agent_name.lower() / "memory.json"

    def user_ov_workspace(self, user_id: str) -> Path:
        """Per-user OpenViking workspace: `{base_dir}/users/{user_id}/ov-workspace/`."""
        return self.user_dir(user_id) / "ov-workspace"

    def user_profile_file(self, user_id: str) -> Path:
        """Per-user profile: `{base_dir}/users/{user_id}/profile.json`."""
        return self.user_dir(user_id) / "profile.json"

    def session_memory_file(self, thread_id: str) -> Path:
        """Per-thread session memory: `{base_dir}/threads/{thread_id}/session-memory.json`."""
        return self.thread_dir(thread_id) / "session-memory.json"

    def thread_ownership_file(self) -> Path:
        """Global thread-to-user ownership mapping: `{base_dir}/thread-ownership.json`."""
        return self.base_dir / "thread-ownership.json"

    # ── Department-level paths ───────────────────────────────────────────

    def dept_dir(self, dept_id: str) -> Path:
        """Directory for a specific department: `{base_dir}/depts/{dept_id}/`.

        Raises:
            ValueError: If `dept_id` contains unsafe characters.
        """
        if not _SAFE_USER_ID_RE.match(dept_id):
            raise ValueError(
                f"Invalid dept_id {dept_id!r}: only alphanumeric characters, hyphens, and underscores are allowed."
            )
        return self.base_dir / "depts" / dept_id

    def dept_user_dir(self, dept_id: str, user_id: str) -> Path:
        """Directory for a user within a department: `{base_dir}/depts/{dept_id}/users/{user_id}/`."""
        return self.dept_dir(dept_id) / "users" / user_id

    def dept_user_agent_dir(self, dept_id: str, user_id: str, agent_name: str) -> Path:
        """Directory for an agent within a dept/user: `{base_dir}/depts/{dept_id}/users/{user_id}/agents/{agent_name}/`."""
        return self.dept_user_dir(dept_id, user_id) / "agents" / agent_name.lower()

    # ── Identity-aware paths ─────────────────────────────────────────────

    def identity_agent_dir(self, identity: "AgentIdentity") -> Path | None:
        """Return the agent-level directory for the given identity, or None.

        Priority:
          1. dept + user + agent   → depts/{dept_id}/users/{user_id}/agents/{agent_name}/
          2. agent only (legacy)   → agents/{agent_name}/
          3. None if no agent_name
        """
        if not identity.has_agent:
            return None
        if identity.has_dept and identity.has_user:
            return self.dept_user_agent_dir(identity.dept_id, identity.user_id, identity.agent_name)
        # Legacy: no dept/user, just agent_name
        return self.agent_dir(identity.agent_name)

    def identity_config_files(self, identity: "AgentIdentity") -> list[Path]:
        """Return ordered list of config.yaml paths for the given identity.

        Order: global → dept → user → agent (last wins in deep-merge).
        Only returns paths that correspond to real directory levels in the identity.
        """
        paths: list[Path] = [self.base_dir / "config.yaml"]

        if identity.has_dept:
            paths.append(self.dept_dir(identity.dept_id) / "config.yaml")

        if identity.has_dept and identity.has_user:
            paths.append(self.dept_user_dir(identity.dept_id, identity.user_id) / "config.yaml")

        agent_dir = self.identity_agent_dir(identity)
        if agent_dir is not None:
            paths.append(agent_dir / "config.yaml")

        return paths

    def identity_extensions_dirs(self, identity: "AgentIdentity") -> list[Path]:
        """Return ordered list of directories that may contain extensions_config.json.

        Order: global → dept → user → agent (intersection strategy applied by caller).
        """
        dirs: list[Path] = [self.base_dir]

        if identity.has_dept:
            dirs.append(self.dept_dir(identity.dept_id))

        if identity.has_dept and identity.has_user:
            dirs.append(self.dept_user_dir(identity.dept_id, identity.user_id))

        agent_dir = self.identity_agent_dir(identity)
        if agent_dir is not None:
            dirs.append(agent_dir)

        return dirs

    def identity_memory_file(self, identity: "AgentIdentity") -> Path:
        """Return the memory.json path scoped to the given identity.

        Falls back to the global memory.json when no identity is set.
        """
        agent_dir = self.identity_agent_dir(identity)
        if agent_dir is not None:
            return agent_dir / "memory.json"
        if identity.has_dept and identity.has_user:
            return self.dept_user_dir(identity.dept_id, identity.user_id) / "memory.json"
        return self.memory_file

    def identity_persona_dirs(self, identity: "AgentIdentity") -> list[Path]:
        """Return ordered list of directories to search for persona files (*.md).

        Order: global → dept → user → agent (Override files use last-wins,
        Append files are concatenated in order).
        """
        dirs: list[Path] = [self.base_dir]

        if identity.has_dept:
            dirs.append(self.dept_dir(identity.dept_id))

        if identity.has_dept and identity.has_user:
            dirs.append(self.dept_user_dir(identity.dept_id, identity.user_id))

        agent_dir = self.identity_agent_dir(identity)
        if agent_dir is not None:
            dirs.append(agent_dir)

        return dirs

    def identity_workspace_dir(self, identity: "AgentIdentity") -> Path | None:
        """Persistent workspace directory for the given identity, or None."""
        agent_dir = self.identity_agent_dir(identity)
        if agent_dir is None:
            return None
        return agent_dir / "workspace"

    def ensure_user_dirs(self, user_id: str) -> None:
        """Create standard directories for a user."""
        for d in [
            self.user_dir(user_id),
            self.user_ov_workspace(user_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def thread_dir(self, thread_id: str) -> Path:
        """
        Host path for a thread's data: `{base_dir}/threads/{thread_id}/`

        This directory contains a `user-data/` subdirectory that is mounted
        as `/mnt/user-data/` inside the sandbox.

        Raises:
            ValueError: If `thread_id` contains unsafe characters (path separators
                        or `..`) that could cause directory traversal.
        """
        if not _SAFE_THREAD_ID_RE.match(thread_id):
            raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
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

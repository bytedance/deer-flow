import posixpath
import re
from pathlib import Path

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadDataState, ThreadState
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.exceptions import (
    SandboxError,
    SandboxNotFoundError,
    SandboxRuntimeError,
)
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![:\w])/(?:[^\s\"'`;&|<>()]+)")
_LOCAL_BASH_SYSTEM_PATH_PREFIXES = (
    "/bin/",
    "/usr/bin/",
    "/usr/sbin/",
    "/sbin/",
    "/opt/homebrew/bin/",
    "/dev/",
)

_DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"
_ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"


def _get_skills_container_path() -> str:
    """Get the skills container path from config, with fallback to default.

    Result is cached after the first successful config load.  If config loading
    fails the default is returned *without* caching so that a later call can
    pick up the real value once the config is available.
    """
    cached = getattr(_get_skills_container_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config import get_app_config

        value = get_app_config().skills.container_path
        _get_skills_container_path._cached = value  # type: ignore[attr-defined]
        return value
    except Exception:
        return _DEFAULT_SKILLS_CONTAINER_PATH


def _get_skills_host_path() -> str | None:
    """Get the skills host filesystem path from config.

    Returns None if the skills directory does not exist or config cannot be
    loaded.  Only successful lookups are cached; failures are retried on the
    next call so that a transiently unavailable skills directory does not
    permanently disable skills access.
    """
    cached = getattr(_get_skills_host_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config import get_app_config

        config = get_app_config()
        skills_path = config.skills.get_skills_path()
        if skills_path.exists():
            value = str(skills_path)
            _get_skills_host_path._cached = value  # type: ignore[attr-defined]
            return value
    except Exception:
        pass
    return None


def _is_skills_path(path: str) -> bool:
    """Check if a path is under the skills container path."""
    skills_prefix = _get_skills_container_path()
    return path == skills_prefix or path.startswith(f"{skills_prefix}/")


def _resolve_skills_path(path: str) -> str:
    """Resolve a virtual skills path to a host filesystem path.

    Args:
        path: Virtual skills path (e.g. /mnt/skills/public/bootstrap/SKILL.md)

    Returns:
        Resolved host path.

    Raises:
        FileNotFoundError: If skills directory is not configured or doesn't exist.
    """
    skills_container = _get_skills_container_path()
    skills_host = _get_skills_host_path()
    if skills_host is None:
        raise FileNotFoundError(f"Skills directory not available for path: {path}")

    if path == skills_container:
        return skills_host

    relative = path[len(skills_container) :].lstrip("/")
    return _join_path_preserving_style(skills_host, relative)


def _is_acp_workspace_path(path: str) -> bool:
    """Check if a path is under the ACP workspace virtual path."""
    return path == _ACP_WORKSPACE_VIRTUAL_PATH or path.startswith(f"{_ACP_WORKSPACE_VIRTUAL_PATH}/")


def _extract_thread_id_from_thread_data(thread_data: "ThreadDataState | None") -> str | None:
    """Extract thread_id from thread_data by inspecting workspace_path.

    The workspace_path has the form
    ``{base_dir}/threads/{thread_id}/user-data/workspace``, so
    ``Path(workspace_path).parent.parent.name`` yields the thread_id.
    """
    if thread_data is None:
        return None
    workspace_path = thread_data.get("workspace_path")
    if not workspace_path:
        return None
    try:
        # {base_dir}/threads/{thread_id}/user-data/workspace → parent.parent = threads/{thread_id}
        return Path(workspace_path).parent.parent.name
    except Exception:
        return None


def _get_acp_workspace_host_path(thread_id: str | None = None) -> str | None:
    """Get the ACP workspace host filesystem path.

    When *thread_id* is provided, returns the per-thread workspace
    ``{base_dir}/threads/{thread_id}/acp-workspace/`` (not cached — the
    directory is created on demand by ``invoke_acp_agent_tool``).

    Falls back to the global ``{base_dir}/acp-workspace/`` when *thread_id*
    is ``None``; that result is cached after the first successful resolution.
    Returns ``None`` if the directory does not exist.
    """
    if thread_id is not None:
        try:
            from deerflow.config.paths import get_paths

            host_path = get_paths().acp_workspace_dir(thread_id)
            if host_path.exists():
                return str(host_path)
        except Exception:
            pass
        return None

    cached = getattr(_get_acp_workspace_host_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config.paths import get_paths

        host_path = get_paths().base_dir / "acp-workspace"
        if host_path.exists():
            value = str(host_path)
            _get_acp_workspace_host_path._cached = value  # type: ignore[attr-defined]
            return value
    except Exception:
        pass
    return None


def _resolve_acp_workspace_path(path: str, thread_id: str | None = None) -> str:
    """Resolve a virtual ACP workspace path to a host filesystem path.

    Args:
        path: Virtual path (e.g. /mnt/acp-workspace/hello_world.py)
        thread_id: Current thread ID for per-thread workspace resolution.
                   When ``None``, falls back to the global workspace.

    Returns:
        Resolved host path.

    Raises:
        FileNotFoundError: If ACP workspace directory does not exist.
        PermissionError: If path traversal is detected.
    """
    _reject_path_traversal(path)

    host_path = _get_acp_workspace_host_path(thread_id)
    if host_path is None:
        raise FileNotFoundError(f"ACP workspace directory not available for path: {path}")

    if path == _ACP_WORKSPACE_VIRTUAL_PATH:
        return host_path

    relative = path[len(_ACP_WORKSPACE_VIRTUAL_PATH) :].lstrip("/")
    resolved = _join_path_preserving_style(host_path, relative)

    if "/" in host_path and "\\" not in host_path:
        base_path = posixpath.normpath(host_path)
        candidate_path = posixpath.normpath(resolved)
        try:
            if posixpath.commonpath([base_path, candidate_path]) != base_path:
                raise PermissionError("Access denied: path traversal detected")
        except ValueError:
            raise PermissionError("Access denied: path traversal detected") from None
        return resolved

    resolved_path = Path(resolved).resolve()
    try:
        resolved_path.relative_to(Path(host_path).resolve())
    except ValueError:
        raise PermissionError("Access denied: path traversal detected")

    return str(resolved_path)


def _get_mcp_allowed_paths() -> list[str]:
    """Get the list of allowed paths from MCP config for file system server."""
    allowed_paths = []
    try:
        from deerflow.config.extensions_config import get_extensions_config

        extensions_config = get_extensions_config()

        for _, server in extensions_config.mcp_servers.items():
            if not server.enabled:
                continue

            # Only check the filesystem server
            args = server.args or []
            # Check if args has server-filesystem package
            has_filesystem = any("server-filesystem" in arg for arg in args)
            if not has_filesystem:
                continue
            # Unpack the allowed file system paths in config
            for arg in args:
                if not arg.startswith("-") and arg.startswith("/"):
                    allowed_paths.append(arg.rstrip("/") + "/")

    except Exception:
        pass

    return allowed_paths


def _path_variants(path: str) -> set[str]:
    return {path, path.replace("\\", "/"), path.replace("/", "\\")}


def _join_path_preserving_style(base: str, relative: str) -> str:
    if not relative:
        return base
    if "/" in base and "\\" not in base:
        return f"{base.rstrip('/')}/{relative}"
    return str(Path(base) / relative)


def _sanitize_error(error: Exception, runtime: "ToolRuntime[ContextT, ThreadState] | None" = None) -> str:
    """Sanitize an error message to avoid leaking host filesystem paths.

    In local-sandbox mode, resolved host paths in the error string are masked
    back to their virtual equivalents so that user-visible output never exposes
    the host directory layout.
    """
    msg = f"{type(error).__name__}: {error}"
    if runtime is not None and is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        msg = mask_local_paths_in_output(msg, thread_data)
    return msg


def replace_virtual_path(path: str, thread_data: ThreadDataState | None) -> str:
    """Replace virtual /mnt/user-data paths with actual thread data paths.

    Mapping:
        /mnt/user-data/workspace/* -> thread_data['workspace_path']/*
        /mnt/user-data/uploads/* -> thread_data['uploads_path']/*
        /mnt/user-data/outputs/* -> thread_data['outputs_path']/*

    Args:
        path: The path that may contain virtual path prefix.
        thread_data: The thread data containing actual paths.

    Returns:
        The path with virtual prefix replaced by actual path.
    """
    if thread_data is None:
        return path

    mappings = _thread_virtual_to_actual_mappings(thread_data)
    if not mappings:
        return path

    # Longest-prefix-first replacement with segment-boundary checks.
    for virtual_base, actual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
        if path == virtual_base:
            return actual_base
        if path.startswith(f"{virtual_base}/"):
            rest = path[len(virtual_base) :].lstrip("/")
            return _join_path_preserving_style(actual_base, rest)

    return path


def _thread_virtual_to_actual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    """Build virtual-to-actual path mappings for a thread."""
    mappings: dict[str, str] = {}

    workspace = thread_data.get("workspace_path")
    uploads = thread_data.get("uploads_path")
    outputs = thread_data.get("outputs_path")

    if workspace:
        mappings[f"{VIRTUAL_PATH_PREFIX}/workspace"] = workspace
    if uploads:
        mappings[f"{VIRTUAL_PATH_PREFIX}/uploads"] = uploads
    if outputs:
        mappings[f"{VIRTUAL_PATH_PREFIX}/outputs"] = outputs

    # Also map the virtual root when all known dirs share the same parent.
    actual_dirs = [Path(p) for p in (workspace, uploads, outputs) if p]
    if actual_dirs:
        common_parent = str(Path(actual_dirs[0]).parent)
        if all(str(path.parent) == common_parent for path in actual_dirs):
            mappings[VIRTUAL_PATH_PREFIX] = common_parent

    return mappings


def _thread_actual_to_virtual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    """Build actual-to-virtual mappings for output masking."""
    return {actual: virtual for virtual, actual in _thread_virtual_to_actual_mappings(thread_data).items()}


def mask_local_paths_in_output(output: str, thread_data: ThreadDataState | None) -> str:
    """Mask host absolute paths from local sandbox output using virtual paths.

    Handles user-data paths (per-thread), skills paths, and ACP workspace paths (global).
    """
    result = output

    # Mask skills host paths
    skills_host = _get_skills_host_path()
    skills_container = _get_skills_container_path()
    if skills_host:
        raw_base = str(Path(skills_host))
        resolved_base = str(Path(skills_host).resolve())
        for base in _path_variants(raw_base) | _path_variants(resolved_base):
            escaped = re.escape(base).replace(r"\\", r"[/\\]")
            pattern = re.compile(escaped + r"(?:[/\\][^\s\"';&|<>()]*)?")

            def replace_skills(match: re.Match, _base: str = base) -> str:
                matched_path = match.group(0)
                if matched_path == _base:
                    return skills_container
                relative = matched_path[len(_base) :].lstrip("/\\")
                return f"{skills_container}/{relative}" if relative else skills_container

            result = pattern.sub(replace_skills, result)

    # Mask ACP workspace host paths
    _thread_id = _extract_thread_id_from_thread_data(thread_data)
    acp_host = _get_acp_workspace_host_path(_thread_id)
    if acp_host:
        raw_base = str(Path(acp_host))
        resolved_base = str(Path(acp_host).resolve())
        for base in _path_variants(raw_base) | _path_variants(resolved_base):
            escaped = re.escape(base).replace(r"\\", r"[/\\]")
            pattern = re.compile(escaped + r"(?:[/\\][^\s\"';&|<>()]*)?")

            def replace_acp(match: re.Match, _base: str = base) -> str:
                matched_path = match.group(0)
                if matched_path == _base:
                    return _ACP_WORKSPACE_VIRTUAL_PATH
                relative = matched_path[len(_base) :].lstrip("/\\")
                return f"{_ACP_WORKSPACE_VIRTUAL_PATH}/{relative}" if relative else _ACP_WORKSPACE_VIRTUAL_PATH

            result = pattern.sub(replace_acp, result)

    # Mask user-data host paths
    if thread_data is None:
        return result

    mappings = _thread_actual_to_virtual_mappings(thread_data)
    if not mappings:
        return result

    for actual_base, virtual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
        raw_base = str(Path(actual_base))
        resolved_base = str(Path(actual_base).resolve())
        for base in _path_variants(raw_base) | _path_variants(resolved_base):
            escaped_actual = re.escape(base).replace(r"\\", r"[/\\]")
            pattern = re.compile(escaped_actual + r"(?:[/\\][^\s\"';&|<>()]*)?")

            def replace_match(match: re.Match, _base: str = base, _virtual: str = virtual_base) -> str:
                matched_path = match.group(0)
                if matched_path == _base:
                    return _virtual
                relative = matched_path[len(_base) :].lstrip("/\\")
                return f"{_virtual}/{relative}" if relative else _virtual

            result = pattern.sub(replace_match, result)

    return result


def _reject_path_traversal(path: str) -> None:
    """Reject paths that contain '..' segments to prevent directory traversal."""
    # Normalise to forward slashes, then check for '..' segments.
    normalised = path.replace("\\", "/")
    for segment in normalised.split("/"):
        if segment == "..":
            raise PermissionError("Access denied: path traversal detected")


def validate_local_tool_path(path: str, thread_data: ThreadDataState | None, *, read_only: bool = False) -> None:
    """Validate that a virtual path is allowed for local-sandbox access.

    This function is a security gate — it checks whether *path* may be
    accessed and raises on violation.  It does **not** resolve the virtual
    path to a host path; callers are responsible for resolution via
    ``_resolve_and_validate_user_data_path`` or ``_resolve_skills_path``.

    Allowed virtual-path families:
      - ``/mnt/user-data/*``  — always allowed (read + write)
      - ``/mnt/skills/*``     — allowed only when *read_only* is True
      - ``/mnt/acp-workspace/*`` — allowed only when *read_only* is True

    Args:
        path: The virtual path to validate.
        thread_data: Thread data (must be present for local sandbox).
        read_only: When True, skills and ACP workspace paths are permitted.

    Raises:
        SandboxRuntimeError: If thread data is missing.
        PermissionError: If the path is not allowed or contains traversal.
    """
    if thread_data is None:
        raise SandboxRuntimeError("Thread data not available for local sandbox")

    _reject_path_traversal(path)

    # Skills paths — read-only access only
    if _is_skills_path(path):
        if not read_only:
            raise PermissionError(f"Write access to skills path is not allowed: {path}")
        return

    # ACP workspace paths — read-only access only
    if _is_acp_workspace_path(path):
        if not read_only:
            raise PermissionError(f"Write access to ACP workspace is not allowed: {path}")
        return

    # User-data paths
    if path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
        return

    raise PermissionError(f"Only paths under {VIRTUAL_PATH_PREFIX}/, {_get_skills_container_path()}/, or {_ACP_WORKSPACE_VIRTUAL_PATH}/ are allowed")


def _validate_resolved_user_data_path(resolved: Path, thread_data: ThreadDataState) -> None:
    """Verify that a resolved host path stays inside allowed per-thread roots.

    Raises PermissionError if the path escapes workspace/uploads/outputs.
    """
    allowed_roots = [
        Path(p).resolve()
        for p in (
            thread_data.get("workspace_path"),
            thread_data.get("uploads_path"),
            thread_data.get("outputs_path"),
        )
        if p is not None
    ]

    if not allowed_roots:
        raise SandboxRuntimeError("No allowed local sandbox directories configured")

    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue

    raise PermissionError("Access denied: path traversal detected")


def _resolve_and_validate_user_data_path(path: str, thread_data: ThreadDataState) -> str:
    """Resolve a /mnt/user-data virtual path and validate it stays in bounds.

    Returns the resolved host path string.
    """
    resolved_str = replace_virtual_path(path, thread_data)
    resolved = Path(resolved_str).resolve()
    _validate_resolved_user_data_path(resolved, thread_data)
    return str(resolved)


def validate_local_bash_command_paths(command: str, thread_data: ThreadDataState | None) -> None:
    """Validate absolute paths in local-sandbox bash commands.

    In local mode, commands must use virtual paths under /mnt/user-data for
    user data access. Skills paths under /mnt/skills and ACP workspace paths
    under /mnt/acp-workspace are allowed (path-traversal checks only; write
    prevention for bash commands is not enforced here).
    A small allowlist of common system path prefixes is kept for executable
    and device references (e.g. /bin/sh, /dev/null).
    """
    if thread_data is None:
        raise SandboxRuntimeError("Thread data not available for local sandbox")

    unsafe_paths: list[str] = []
    allowed_paths = _get_mcp_allowed_paths()

    for absolute_path in _ABSOLUTE_PATH_PATTERN.findall(command):
        # Check for MCP filesystem server allowed paths
        if any(absolute_path.startswith(path) or absolute_path == path.rstrip("/") for path in allowed_paths):
            _reject_path_traversal(absolute_path)
            continue

        if absolute_path == VIRTUAL_PATH_PREFIX or absolute_path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            _reject_path_traversal(absolute_path)
            continue

        # Allow skills container path (resolved by tools.py before passing to sandbox)
        if _is_skills_path(absolute_path):
            _reject_path_traversal(absolute_path)
            continue

        # Allow ACP workspace path (path-traversal check only)
        if _is_acp_workspace_path(absolute_path):
            _reject_path_traversal(absolute_path)
            continue

        if any(absolute_path == prefix.rstrip("/") or absolute_path.startswith(prefix) for prefix in _LOCAL_BASH_SYSTEM_PATH_PREFIXES):
            continue

        unsafe_paths.append(absolute_path)

    if unsafe_paths:
        unsafe = ", ".join(sorted(dict.fromkeys(unsafe_paths)))
        raise PermissionError(f"Unsafe absolute paths in command: {unsafe}. Use paths under {VIRTUAL_PATH_PREFIX}")


def replace_virtual_paths_in_command(command: str, thread_data: ThreadDataState | None) -> str:
    """Replace all virtual paths (/mnt/user-data, /mnt/skills, /mnt/acp-workspace) in a command string.

    Args:
        command: The command string that may contain virtual paths.
        thread_data: The thread data containing actual paths.

    Returns:
        The command with all virtual paths replaced.
    """
    result = command

    # Replace skills paths
    skills_container = _get_skills_container_path()
    skills_host = _get_skills_host_path()
    if skills_host and skills_container in result:
        skills_pattern = re.compile(rf"{re.escape(skills_container)}(/[^\s\"';&|<>()]*)?")

        def replace_skills_match(match: re.Match) -> str:
            return _resolve_skills_path(match.group(0))

        result = skills_pattern.sub(replace_skills_match, result)

    # Replace ACP workspace paths
    _thread_id = _extract_thread_id_from_thread_data(thread_data)
    acp_host = _get_acp_workspace_host_path(_thread_id)
    if acp_host and _ACP_WORKSPACE_VIRTUAL_PATH in result:
        acp_pattern = re.compile(rf"{re.escape(_ACP_WORKSPACE_VIRTUAL_PATH)}(/[^\s\"';&|<>()]*)?")

        def replace_acp_match(match: re.Match, _tid: str | None = _thread_id) -> str:
            return _resolve_acp_workspace_path(match.group(0), _tid)

        result = acp_pattern.sub(replace_acp_match, result)

    # Replace user-data paths
    if VIRTUAL_PATH_PREFIX in result and thread_data is not None:
        pattern = re.compile(rf"{re.escape(VIRTUAL_PATH_PREFIX)}(/[^\s\"';&|<>()]*)?")

        def replace_user_data_match(match: re.Match) -> str:
            return replace_virtual_path(match.group(0), thread_data)

        result = pattern.sub(replace_user_data_match, result)

    return result


def get_thread_data(runtime: ToolRuntime[ContextT, ThreadState] | None) -> ThreadDataState | None:
    """Extract thread_data from runtime state."""
    if runtime is None:
        return None
    if runtime.state is None:
        return None
    return runtime.state.get("thread_data")


def is_local_sandbox(runtime: ToolRuntime[ContextT, ThreadState] | None) -> bool:
    """Check if the current sandbox is a local sandbox.

    Path replacement is only needed for local sandbox since aio sandbox
    already has /mnt/user-data mounted in the container.
    """
    if runtime is None:
        return False
    if runtime.state is None:
        return False
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        return False
    return sandbox_state.get("sandbox_id") == "local"


def sandbox_from_runtime(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """Extract sandbox instance from tool runtime.

    DEPRECATED: Use ensure_sandbox_initialized() for lazy initialization support.
    This function assumes sandbox is already initialized and will raise error if not.

    Raises:
        SandboxRuntimeError: If runtime is not available or sandbox state is missing.
        SandboxNotFoundError: If sandbox with the given ID cannot be found.
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")
    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        raise SandboxRuntimeError("Sandbox state not initialized in runtime")
    sandbox_id = sandbox_state.get("sandbox_id")
    if sandbox_id is None:
        raise SandboxRuntimeError("Sandbox ID not found in state")
    sandbox = get_sandbox_provider().get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError(f"Sandbox with ID '{sandbox_id}' not found", sandbox_id=sandbox_id)

    runtime.context["sandbox_id"] = sandbox_id  # Ensure sandbox_id is in context for downstream use
    return sandbox


def ensure_sandbox_initialized(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """Ensure sandbox is initialized, acquiring lazily if needed.

    On first call, acquires a sandbox from the provider and stores it in runtime state.
    Subsequent calls return the existing sandbox.

    Thread-safety is guaranteed by the provider's internal locking mechanism.

    Args:
        runtime: Tool runtime containing state and context.

    Returns:
        Initialized sandbox instance.

    Raises:
        SandboxRuntimeError: If runtime is not available or thread_id is missing.
        SandboxNotFoundError: If sandbox acquisition fails.
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")

    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")

    # Check if sandbox already exists in state
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                runtime.context["sandbox_id"] = sandbox_id  # Ensure sandbox_id is in context for releasing in after_agent
                return sandbox
            # Sandbox was released, fall through to acquire new one

    # Lazy acquisition: get thread_id and acquire sandbox
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id") if runtime.config else None
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available in runtime context")

    provider = get_sandbox_provider()
    sandbox_id = provider.acquire(thread_id)

    # Update runtime state - this persists across tool calls
    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

    # Retrieve and return the sandbox
    sandbox = provider.get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

    runtime.context["sandbox_id"] = sandbox_id  # Ensure sandbox_id is in context for releasing in after_agent
    return sandbox


def ensure_thread_directories_exist(runtime: ToolRuntime[ContextT, ThreadState] | None) -> None:
    """Ensure thread data directories (workspace, uploads, outputs) exist.

    This function is called lazily when any sandbox tool is first used.
    For local sandbox, it creates the directories on the filesystem.
    For other sandboxes (like aio), directories are already mounted in the container.

    Args:
        runtime: Tool runtime containing state and context.
    """
    if runtime is None:
        return

    # Only create directories for local sandbox
    if not is_local_sandbox(runtime):
        return

    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return

    # Check if directories have already been created
    if runtime.state.get("thread_directories_created"):
        return

    # Create the three directories
    import os

    for key in ["workspace_path", "uploads_path", "outputs_path"]:
        path = thread_data.get(key)
        if path:
            os.makedirs(path, exist_ok=True)

    # Mark as created to avoid redundant operations
    runtime.state["thread_directories_created"] = True


@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """Execute a bash command in a Linux environment.


    - Use `python` to run Python code.
    - Prefer a thread-local virtual environment in `/mnt/user-data/workspace/.venv`.
    - Use `python -m pip` (inside the virtual environment) to install Python packages.

    Args:
        description: Explain why you are running this command in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        command: The bash command to execute. Always use absolute paths for files and directories.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        thread_data = get_thread_data(runtime)
        if is_local_sandbox(runtime):
            validate_local_bash_command_paths(command, thread_data)
            command = replace_virtual_paths_in_command(command, thread_data)
            output = sandbox.execute_command(command)
            return mask_local_paths_in_output(output, thread_data)
        return sandbox.execute_command(command)
    except SandboxError as e:
        return f"Error: {e}"
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing command: {_sanitize_error(e, runtime)}"


@tool("ls", parse_docstring=True)
def ls_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, path: str) -> str:
    """List the contents of a directory up to 2 levels deep in tree format.

    Args:
        description: Explain why you are listing this directory in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the directory to list.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data, read_only=True)
            if _is_skills_path(path):
                path = _resolve_skills_path(path)
            elif _is_acp_workspace_path(path):
                path = _resolve_acp_workspace_path(path, _extract_thread_id_from_thread_data(thread_data))
            else:
                path = _resolve_and_validate_user_data_path(path, thread_data)
        children = sandbox.list_dir(path)
        if not children:
            return "(empty)"
        return "\n".join(children)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: Directory not found: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error listing directory: {_sanitize_error(e, runtime)}"


@tool("read_file", parse_docstring=True)
def read_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read the contents of a text file. Use this to examine source code, configuration files, logs, or any text-based file.

    Args:
        description: Explain why you are reading this file in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to read.
        start_line: Optional starting line number (1-indexed, inclusive). Use with end_line to read a specific range.
        end_line: Optional ending line number (1-indexed, inclusive). Use with start_line to read a specific range.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data, read_only=True)
            if _is_skills_path(path):
                path = _resolve_skills_path(path)
            elif _is_acp_workspace_path(path):
                path = _resolve_acp_workspace_path(path, _extract_thread_id_from_thread_data(thread_data))
            else:
                path = _resolve_and_validate_user_data_path(path, thread_data)
        content = sandbox.read_file(path)
        if not content:
            return "(empty)"
        if start_line is not None and end_line is not None:
            content = "\n".join(content.splitlines()[start_line - 1 : end_line])
        return content
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {requested_path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error reading file: {_sanitize_error(e, runtime)}"


@tool("write_file", parse_docstring=True)
def write_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    content: str,
    append: bool = False,
) -> str:
    """Write text content to a file.

    Args:
        description: Explain why you are writing to this file in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to write to. ALWAYS PROVIDE THIS PARAMETER SECOND.
        content: The content to write to the file. ALWAYS PROVIDE THIS PARAMETER THIRD.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data)
            path = _resolve_and_validate_user_data_path(path, thread_data)
        sandbox.write_file(path, content, append)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: Permission denied writing to file: {requested_path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {requested_path}"
    except OSError as e:
        return f"Error: Failed to write file '{requested_path}': {_sanitize_error(e, runtime)}"
    except Exception as e:
        return f"Error: Unexpected error writing file: {_sanitize_error(e, runtime)}"


@tool("str_replace", parse_docstring=True)
def str_replace_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    """Replace a substring in a file with another substring.
    If `replace_all` is False (default), the substring to replace must appear **exactly once** in the file.

    Args:
        description: Explain why you are replacing the substring in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to replace the substring in. ALWAYS PROVIDE THIS PARAMETER SECOND.
        old_str: The substring to replace. ALWAYS PROVIDE THIS PARAMETER THIRD.
        new_str: The new substring. ALWAYS PROVIDE THIS PARAMETER FOURTH.
        replace_all: Whether to replace all occurrences of the substring. If False, only the first occurrence will be replaced. Default is False.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        requested_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            validate_local_tool_path(path, thread_data)
            path = _resolve_and_validate_user_data_path(path, thread_data)
        content = sandbox.read_file(path)
        if not content:
            return "OK"
        if old_str not in content:
            return f"Error: String to replace not found in file: {requested_path}"
        if replace_all:
            content = content.replace(old_str, new_str)
        else:
            content = content.replace(old_str, new_str, 1)
        sandbox.write_file(path, content)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {requested_path}"
    except PermissionError:
        return f"Error: Permission denied accessing file: {requested_path}"
    except Exception as e:
        return f"Error: Unexpected error replacing string: {_sanitize_error(e, runtime)}"

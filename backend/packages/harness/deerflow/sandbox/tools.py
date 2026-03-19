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


def _get_skills_container_path() -> str:
    """Get the skills container 路径 from 配置, with 回退 to 默认.

    Result is cached after the 第一 successful 配置 load.  If 配置 加载中
    fails the 默认 is returned *without* caching so that a later call can
    pick 上 the real 值 once the 配置 is 可用的.
    """
    cached = getattr(_get_skills_container_path, "_cached", None)
    if cached is not None:
        return cached
    try:
        from deerflow.config import get_app_config

        value = get_app_config().skills.container_path
        _get_skills_container_path._cached = value  #    类型: ignore[attr-defined]


        return value
    except Exception:
        return _DEFAULT_SKILLS_CONTAINER_PATH


def _get_skills_host_path() -> str | None:
    """Get the skills host filesystem 路径 from 配置.

    Returns None if the skills 目录 does not exist or 配置 cannot be
    loaded.  Only successful lookups are cached; failures are retried on the
    下一个 call so that a transiently unavailable skills 目录 does not
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
            _get_skills_host_path._cached = value  #    类型: ignore[attr-defined]


            return value
    except Exception:
        pass
    return None


def _is_skills_path(path: str) -> bool:
    """Check if a 路径 is under the skills container 路径."""
    skills_prefix = _get_skills_container_path()
    return path == skills_prefix or path.startswith(f"{skills_prefix}/")


def _resolve_skills_path(path: str) -> str:
    """Resolve a virtual skills 路径 to a host filesystem 路径.

    Args:
        路径: Virtual skills 路径 (e.g. /mnt/skills/public/bootstrap/SKILL.md)

    Returns:
        Resolved host 路径.

    Raises:
        FileNotFoundError: If skills 目录 is not configured or doesn't exist.
    """
    skills_container = _get_skills_container_path()
    skills_host = _get_skills_host_path()
    if skills_host is None:
        raise FileNotFoundError(f"Skills directory not available for path: {path}")

    if path == skills_container:
        return skills_host

    relative = path[len(skills_container):].lstrip("/")
    return str(Path(skills_host) / relative) if relative else skills_host


def _path_variants(path: str) -> set[str]:
    return {path, path.replace("\\", "/"), path.replace("/", "\\")}


def _sanitize_error(error: Exception, runtime: "ToolRuntime[ContextT, ThreadState] | None" = None) -> str:
    """Sanitize an 错误 消息 to avoid leaking host filesystem paths.

    In local-sandbox mode, resolved host paths in the 错误 字符串 are masked
    back to their virtual equivalents so that 用户-可见 输出 never exposes
    the host 目录 layout.
    """
    msg = f"{type(error).__name__}: {error}"
    if runtime is not None and is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        msg = mask_local_paths_in_output(msg, thread_data)
    return msg


def replace_virtual_path(path: str, thread_data: ThreadDataState | None) -> str:
    """Replace virtual /mnt/用户-数据 paths with actual 线程 数据 paths.

    Mapping:
        /mnt/用户-数据/工作区/* -> thread_data['workspace_path']/*
        /mnt/用户-数据/uploads/* -> thread_data['uploads_path']/*
        /mnt/用户-数据/outputs/* -> thread_data['outputs_path']/*

    Args:
        路径: The 路径 that may contain virtual 路径 prefix.
        thread_data: The 线程 数据 containing actual paths.

    Returns:
        The 路径 with virtual prefix replaced by actual 路径.
    """
    if thread_data is None:
        return path

    mappings = _thread_virtual_to_actual_mappings(thread_data)
    if not mappings:
        return path

    #    Longest-prefix-第一 replacement with segment-boundary checks.


    for virtual_base, actual_base in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
        if path == virtual_base:
            return actual_base
        if path.startswith(f"{virtual_base}/"):
            rest = path[len(virtual_base) :].lstrip("/")
            return str(Path(actual_base) / rest) if rest else actual_base

    return path


def _thread_virtual_to_actual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    """Build virtual-to-actual 路径 mappings for a 线程."""
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

    #    Also map the virtual root when all known dirs share the same parent.


    actual_dirs = [Path(p) for p in (workspace, uploads, outputs) if p]
    if actual_dirs:
        common_parent = str(Path(actual_dirs[0]).parent)
        if all(str(path.parent) == common_parent for path in actual_dirs):
            mappings[VIRTUAL_PATH_PREFIX] = common_parent

    return mappings


def _thread_actual_to_virtual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    """Build actual-to-virtual mappings for 输出 masking."""
    return {actual: virtual for virtual, actual in _thread_virtual_to_actual_mappings(thread_data).items()}


def mask_local_paths_in_output(output: str, thread_data: ThreadDataState | None) -> str:
    """Mask host absolute paths from local sandbox 输出 using virtual paths.

    Handles both 用户-数据 paths (per-线程) and skills paths (global).
    """
    result = output

    #    Mask skills host paths


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
                relative = matched_path[len(_base):].lstrip("/\\")
                return f"{skills_container}/{relative}" if relative else skills_container

            result = pattern.sub(replace_skills, result)

    #    Mask 用户-数据 host paths


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
                relative = matched_path[len(_base):].lstrip("/\\")
                return f"{_virtual}/{relative}" if relative else _virtual

            result = pattern.sub(replace_match, result)

    return result


def _reject_path_traversal(path: str) -> None:
    """Reject paths that contain '..' segments to prevent 目录 traversal."""
    #    Normalise to forward slashes, then 检查 对于 '..' segments.


    normalised = path.replace("\\", "/")
    for segment in normalised.split("/"):
        if segment == "..":
            raise PermissionError("Access denied: path traversal detected")


def validate_local_tool_path(path: str, thread_data: ThreadDataState | None, *, read_only: bool = False) -> None:
    """Validate that a virtual 路径 is allowed for local-sandbox access.

    This 函数 is a 安全 gate — it checks whether *路径* may be
    accessed and raises on violation.  It does **not** resolve the virtual
    路径 to a host 路径; callers are responsible for resolution via
    ``_resolve_and_validate_user_data_path`` or ``_resolve_skills_path``.

    Allowed virtual-路径 families:
      - ``/mnt/用户-数据/*``  — always allowed (read + write)
      - ``/mnt/skills/*``     — allowed only when *read_only* is True

    Args:
        路径: The virtual 路径 to 验证.
        thread_data: 线程 数据 (must be present for local sandbox).
        read_only: When True, skills paths are permitted.

    Raises:
        SandboxRuntimeError: If 线程 数据 is missing.
        PermissionError: If the 路径 is not allowed or contains traversal.
    """
    if thread_data is None:
        raise SandboxRuntimeError("Thread data not available for local sandbox")

    _reject_path_traversal(path)

    #    Skills paths — read-only access only


    if _is_skills_path(path):
        if not read_only:
            raise PermissionError(f"Write access to skills path is not allowed: {path}")
        return

    #    用户-数据 paths


    if path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
        return

    raise PermissionError(f"Only paths under {VIRTUAL_PATH_PREFIX}/ or {_get_skills_container_path()}/ are allowed")


def _validate_resolved_user_data_path(resolved: Path, thread_data: ThreadDataState) -> None:
    """Verify that a resolved host 路径 stays inside allowed per-线程 roots.

    Raises PermissionError if the 路径 escapes 工作区/uploads/outputs.
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
    """Resolve a /mnt/用户-数据 virtual 路径 and 验证 it stays in bounds.

    Returns the resolved host 路径 字符串.
    """
    resolved_str = replace_virtual_path(path, thread_data)
    resolved = Path(resolved_str).resolve()
    _validate_resolved_user_data_path(resolved, thread_data)
    return str(resolved)


def validate_local_bash_command_paths(command: str, thread_data: ThreadDataState | None) -> None:
    """Validate absolute paths in local-sandbox bash commands.

    In local mode, commands must use virtual paths under /mnt/用户-数据 for
    用户 数据 access. Skills paths under /mnt/skills are allowed for reading.
    A small allowlist of common 系统 路径 prefixes is kept for executable
    and 设备 references (e.g. /bin/sh, /dev/null).
    """
    if thread_data is None:
        raise SandboxRuntimeError("Thread data not available for local sandbox")

    unsafe_paths: list[str] = []

    for absolute_path in _ABSOLUTE_PATH_PATTERN.findall(command):
        if absolute_path == VIRTUAL_PATH_PREFIX or absolute_path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            _reject_path_traversal(absolute_path)
            continue

        #    Allow skills container 路径 (resolved by tools.py before passing to sandbox)


        if _is_skills_path(absolute_path):
            _reject_path_traversal(absolute_path)
            continue

        if any(
            absolute_path == prefix.rstrip("/") or absolute_path.startswith(prefix)
            for prefix in _LOCAL_BASH_SYSTEM_PATH_PREFIXES
        ):
            continue

        unsafe_paths.append(absolute_path)

    if unsafe_paths:
        unsafe = ", ".join(sorted(dict.fromkeys(unsafe_paths)))
        raise PermissionError(f"Unsafe absolute paths in command: {unsafe}. Use paths under {VIRTUAL_PATH_PREFIX}")


def replace_virtual_paths_in_command(command: str, thread_data: ThreadDataState | None) -> str:
    """Replace all virtual paths (/mnt/用户-数据 and /mnt/skills) in a command 字符串.

    Args:
        command: The command 字符串 that may contain virtual paths.
        thread_data: The 线程 数据 containing actual paths.

    Returns:
        The command with all virtual paths replaced.
    """
    result = command

    #    Replace skills paths


    skills_container = _get_skills_container_path()
    skills_host = _get_skills_host_path()
    if skills_host and skills_container in result:
        skills_pattern = re.compile(rf"{re.escape(skills_container)}(/[^\s\"';&|<>()]*)?")

        def replace_skills_match(match: re.Match) -> str:
            return _resolve_skills_path(match.group(0))

        result = skills_pattern.sub(replace_skills_match, result)

    #    Replace 用户-数据 paths


    if VIRTUAL_PATH_PREFIX in result and thread_data is not None:
        pattern = re.compile(rf"{re.escape(VIRTUAL_PATH_PREFIX)}(/[^\s\"';&|<>()]*)?")

        def replace_user_data_match(match: re.Match) -> str:
            return replace_virtual_path(match.group(0), thread_data)

        result = pattern.sub(replace_user_data_match, result)

    return result


def get_thread_data(runtime: ToolRuntime[ContextT, ThreadState] | None) -> ThreadDataState | None:
    """Extract thread_data from runtime 状态."""
    if runtime is None:
        return None
    if runtime.state is None:
        return None
    return runtime.state.get("thread_data")


def is_local_sandbox(runtime: ToolRuntime[ContextT, ThreadState] | None) -> bool:
    """Check if the 当前 sandbox is a local sandbox.

    Path replacement is only needed for local sandbox since aio sandbox
    already has /mnt/用户-数据 mounted in the container.
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
    """Extract sandbox instance from 工具 runtime.

    DEPRECATED: Use ensure_sandbox_initialized() for lazy initialization support.
    This 函数 assumes sandbox is already initialized and will raise 错误 if not.

    Raises:
        SandboxRuntimeError: If runtime is not 可用的 or sandbox 状态 is missing.
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

    runtime.context["sandbox_id"] = sandbox_id  #    Ensure sandbox_id is in context 对于 downstream use


    return sandbox


def ensure_sandbox_initialized(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """Ensure sandbox is initialized, acquiring lazily if needed.

    On 第一 call, acquires a sandbox from the provider and stores it in runtime 状态.
    Subsequent calls 返回 the existing sandbox.

    线程-safety is guaranteed by the provider's internal locking mechanism.

    Args:
        runtime: 工具 runtime containing 状态 and context.

    Returns:
        Initialized sandbox instance.

    Raises:
        SandboxRuntimeError: If runtime is not 可用的 or thread_id is missing.
        SandboxNotFoundError: If sandbox acquisition fails.
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")

    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")

    #    Check 如果 sandbox already exists in 状态


    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                runtime.context["sandbox_id"] = sandbox_id  #    Ensure sandbox_id is in context 对于 releasing in after_agent


                return sandbox
            #    Sandbox was released, fall through to acquire 新建 one



    #    Lazy acquisition: get thread_id and acquire sandbox


    thread_id = runtime.context.get("thread_id")
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available in runtime context")

    provider = get_sandbox_provider()
    sandbox_id = provider.acquire(thread_id)

    #    Update runtime 状态 - this persists across 工具 calls


    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

    #    Retrieve and 返回 the sandbox


    sandbox = provider.get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

    runtime.context["sandbox_id"] = sandbox_id  #    Ensure sandbox_id is in context 对于 releasing in after_agent


    return sandbox


def ensure_thread_directories_exist(runtime: ToolRuntime[ContextT, ThreadState] | None) -> None:
    """Ensure 线程 数据 directories (工作区, uploads, outputs) exist.

    This 函数 is called lazily when any sandbox 工具 is 第一 used.
    For local sandbox, it creates the directories on the filesystem.
    For other sandboxes (like aio), directories are already mounted in the container.

    Args:
        runtime: 工具 runtime containing 状态 and context.
    """
    if runtime is None:
        return

    #    Only 创建 directories 对于 local sandbox


    if not is_local_sandbox(runtime):
        return

    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return

    #    Check 如果 directories have already been created


    if runtime.state.get("thread_directories_created"):
        return

    #    Create the three directories


    import os

    for key in ["workspace_path", "uploads_path", "outputs_path"]:
        path = thread_data.get(key)
        if path:
            os.makedirs(path, exist_ok=True)

    #    Mark as created to avoid redundant operations


    runtime.state["thread_directories_created"] = True


@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """Execute a bash command in a Linux 环境.


    - Use `python` to 运行 Python code.
    - Prefer a 线程-local virtual 环境 in `/mnt/用户-数据/工作区/.venv`.
    - Use `python -m pip` (inside the virtual 环境) to install Python packages.

    Args:
        描述: Explain why you are running this command in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        command: The bash command to 执行. Always use absolute paths for files and directories.
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
    """List the contents of a 目录 上 to 2 levels deep in tree format.

    Args:
        描述: Explain why you are listing this 目录 in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        路径: The **absolute** 路径 to the 目录 to 列表.
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
    """Read the contents of a text 文件. Use this to examine source code, configuration files, logs, or any text-based 文件.

    Args:
        描述: Explain why you are reading this 文件 in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        路径: The **absolute** 路径 to the 文件 to read.
        start_line: Optional starting line 数字 (1-indexed, inclusive). Use with end_line to read a specific range.
        end_line: Optional ending line 数字 (1-indexed, inclusive). Use with start_line to read a specific range.
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
    """Write text content to a 文件.

    Args:
        描述: Explain why you are writing to this 文件 in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        路径: The **absolute** 路径 to the 文件 to write to. ALWAYS PROVIDE THIS PARAMETER SECOND.
        content: The content to write to the 文件. ALWAYS PROVIDE THIS PARAMETER THIRD.
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
    """Replace a substring in a 文件 with another substring.
    If `replace_all` is False (默认), the substring to replace must appear **exactly once** in the 文件.

    Args:
        描述: Explain why you are replacing the substring in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        路径: The **absolute** 路径 to the 文件 to replace the substring in. ALWAYS PROVIDE THIS PARAMETER SECOND.
        old_str: The substring to replace. ALWAYS PROVIDE THIS PARAMETER THIRD.
        new_str: The 新建 substring. ALWAYS PROVIDE THIS PARAMETER FOURTH.
        replace_all: Whether to replace all occurrences of the substring. If False, only the 第一 occurrence will be replaced. Default is False.
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

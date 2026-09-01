"""Built-in tool for running explicitly requested Windows host programs."""

from __future__ import annotations

import math
import os

from langchain.tools import tool

from deerflow.sandbox.host_path_compat import is_program_argument_path, split_program_argument
from deerflow.sandbox.security import is_host_bash_allowed, uses_local_sandbox_provider
from deerflow.tools.types import Runtime


def _normalize_program_argument(value: str) -> str:
    prefix, candidate = split_program_argument(value)
    if is_program_argument_path(value):
        from deerflow.sandbox.tools import normalize_local_tool_path

        return f"{prefix}{normalize_local_tool_path(candidate)}"
    return value


def _is_windows_host_program_platform() -> bool:
    return os.name == "nt"


def _resolve_program_timeout(requested: float | None, configured: object) -> float:
    from deerflow.sandbox.local.local_sandbox import DEFAULT_COMMAND_TIMEOUT_SECONDS

    try:
        configured_timeout = float(configured)
    except (TypeError, ValueError):
        configured_timeout = float(DEFAULT_COMMAND_TIMEOUT_SECONDS)
    if not math.isfinite(configured_timeout) or configured_timeout <= 0:
        configured_timeout = float(DEFAULT_COMMAND_TIMEOUT_SECONDS)
    if requested is None:
        return configured_timeout
    if not math.isfinite(requested) or requested <= 0:
        raise ValueError("timeout must be positive and finite")
    return min(float(requested), configured_timeout)


def _sanitize_program_exception(error: Exception, *, sandbox: object | None, thread_data: object | None, injected_env: dict[str, str] | None) -> str | None:
    """Return a launch error with host paths and injected secrets removed."""
    try:
        from deerflow.sandbox.tools import mask_local_paths_in_output, mask_secret_values

        detail = f"{type(error).__name__}: {error}"
        reverse_paths = getattr(sandbox, "_reverse_resolve_paths_in_output", None)
        if not callable(reverse_paths):
            # No acquired sandbox means custom-mount mappings are unavailable;
            # do not expose an exception string that may contain a host path.
            return None
        detail = reverse_paths(detail)
        detail = mask_local_paths_in_output(detail, thread_data)
        return mask_secret_values(detail, injected_env)
    except Exception:
        return None


@tool("run_host_program", parse_docstring=True)
def run_host_program_tool(
    runtime: Runtime,
    description: str,
    program_path: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout: float | None = None,
) -> str:
    """Run a Windows program from a configured local sandbox mount.

    Use this for a native ``.exe``, ``.cmd``/``.bat`` or ``.ps1`` program when
    the requested program lives under a configured ``sandbox.mounts`` host
    directory. Host paths in ``program_path``, ``args`` and ``cwd`` are
    accepted and normalized to the mount's virtual ``container_path`` before
    authorization. This tool is available only in trusted local mode.

    Args:
        description: Explain why the program is being run.
        program_path: Program path, as a configured virtual or Windows host path. For ``.cmd``/``.bat`` files, paths containing ``%`` or ``^`` are not supported by the Windows command wrapper.
        args: Optional program arguments. Configured host paths in arguments are normalized; absolute argument paths must resolve inside a configured mount. ``%``, ``^``, quotes, and control characters are not supported for batch arguments.
        cwd: Optional working directory, as a configured virtual or Windows host path.
        timeout: Optional wall-clock timeout in seconds.
    """
    sandbox = None
    thread_data = None
    injected_env = None
    try:
        from deerflow.config import get_app_config
        from deerflow.runtime.secret_context import read_active_secrets
        from deerflow.sandbox.tools import (
            _is_custom_mount_path,
            _truncate_bash_output,
            ensure_sandbox_initialized,
            get_thread_data,
            is_local_sandbox,
            mask_local_paths_in_output,
            mask_secret_values,
            normalize_local_tool_path,
            validate_local_tool_path,
        )

        if not _is_windows_host_program_platform():
            return "Error: run_host_program is only available on Windows"
        if not is_local_sandbox(runtime) and not uses_local_sandbox_provider():
            return "Error: run_host_program requires LocalSandboxProvider"
        if not is_host_bash_allowed():
            return "Error: Host program execution is disabled. Set sandbox.allow_host_bash: true only in a trusted local environment."
        if runtime.state is None or get_thread_data(runtime) is None:
            return "Error: Thread data is not available"

        normalized_program = normalize_local_tool_path(program_path)
        normalized_args = [_normalize_program_argument(value) for value in (args or [])]
        normalized_cwd = normalize_local_tool_path(cwd) if cwd else None
        thread_data = get_thread_data(runtime)
        validate_local_tool_path(normalized_program, thread_data, read_only=True)
        if not _is_custom_mount_path(normalized_program):
            return "Error: Program must be inside a configured sandbox mount"
        if os.path.splitext(normalized_program)[1].lower() not in {".exe", ".cmd", ".bat", ".ps1"}:
            return "Error: Only .exe, .cmd, .bat, and .ps1 programs are supported"
        if normalized_cwd:
            validate_local_tool_path(normalized_cwd, thread_data, read_only=True)
            if not _is_custom_mount_path(normalized_cwd):
                return "Error: Working directory must be inside a configured sandbox mount"
        injected_env = read_active_secrets(getattr(runtime, "context", None)) or None
        sandbox_config = get_app_config().sandbox
        timeout = _resolve_program_timeout(timeout, getattr(sandbox_config, "bash_command_timeout", None))

        sandbox = ensure_sandbox_initialized(runtime)
        if not is_local_sandbox(runtime):
            return "Error: run_host_program requires LocalSandboxProvider"
        if not hasattr(sandbox, "execute_program"):
            return "Error: LocalSandboxProvider does not support native program execution"

        output = sandbox.execute_program(
            normalized_program,
            normalized_args,
            cwd=normalized_cwd,
            env=injected_env,
            timeout=timeout,
        )
        max_chars = sandbox_config.bash_output_max_chars if sandbox_config else 20000
        return _truncate_bash_output(mask_secret_values(mask_local_paths_in_output(output, thread_data), injected_env), max_chars)
    except PermissionError as exc:
        if sandbox is None:
            return "Error: Permission denied: Host path is not allowed"
        detail = _sanitize_program_exception(error=exc, sandbox=sandbox, thread_data=thread_data, injected_env=injected_env)
        if detail is None:
            return "Error: Permission denied while running program"
        return f"Error: Permission denied: {detail}"
    except FileNotFoundError:
        return "Error: Program not found"
    except ValueError as exc:
        if sandbox is not None:
            detail = _sanitize_program_exception(error=exc, sandbox=sandbox, thread_data=thread_data, injected_env=injected_env)
            if detail is None:
                return "Error: Invalid program request"
            return f"Error: {detail}"
        return f"Error: {exc}"
    except Exception as exc:
        detail = _sanitize_program_exception(error=exc, sandbox=sandbox, thread_data=thread_data, injected_env=injected_env)
        if detail is None:
            return "Error: Unexpected error running program"
        return f"Error: Unexpected error running program: {detail}"


__all__ = ["run_host_program_tool"]

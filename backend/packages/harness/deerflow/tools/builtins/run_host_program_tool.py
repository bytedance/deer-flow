"""Built-in tool for running explicitly requested Windows host programs."""

from __future__ import annotations

import math
import os

from langchain.tools import tool

from deerflow.sandbox.security import is_host_bash_allowed, uses_local_sandbox_provider
from deerflow.tools.types import Runtime


def _looks_like_path(value: str) -> bool:
    candidate = value.partition("=")[2] if "=" in value else value
    return bool(candidate) and (candidate.startswith(("/", "\\")) or (len(candidate) >= 3 and candidate[1] == ":" and candidate[2] in {"/", "\\"}))


def _normalize_program_argument(value: str) -> str:
    if "=" in value:
        prefix, separator, candidate = value.partition("=")
        if _looks_like_path(candidate):
            return f"{prefix}{separator}{_normalize_program_argument(candidate)}"
    if _looks_like_path(value):
        from deerflow.sandbox.tools import normalize_local_tool_path

        return normalize_local_tool_path(value)
    return value


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
        program_path: Program path, as a configured virtual or Windows host path.
        args: Optional program arguments. Configured host paths in arguments are normalized.
        cwd: Optional working directory, as a configured virtual or Windows host path.
        timeout: Optional wall-clock timeout in seconds.
    """
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

        if os.name != "nt":
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
        return f"Error: Permission denied: {exc}"
    except FileNotFoundError:
        return f"Error: Program not found: {program_path}"
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: Unexpected error running program: {type(exc).__name__}: {exc}"


__all__ = ["run_host_program_tool"]

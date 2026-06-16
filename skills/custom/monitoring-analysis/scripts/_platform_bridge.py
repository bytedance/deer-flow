"""Platform bridge — call integration CLI subprocess for report data.

When ``USE_PLATFORM=true`` is set, query scripts (query_daily.py /
query_weekly.py / query_monthly.py) route through this module instead
of the direct ``_ins_provider.py`` path.

The bridge invokes::

    python -m deerflow.integrations.cli \\
        --capability <key> \\
        --tenant-id <id> \\
        --user-id <id> \\
        --params <json>

and parses the JSON output. On failure, the caller falls back to the
legacy provider path.

Execution environment
---------------------
The CLI bridge requires ``features-tool`` (InS HTTP client), which is only
available inside the sandbox Docker container (``/opt/features-tool``).
When the query script runs on the host backend (where features-tool is
not importable), this bridge automatically routes the CLI call into the
sandbox container via ``docker exec``, using the container name derived
from ``DEER_FLOW_THREAD_ID`` (same hashing logic as AioSandboxProvider).

Architecture note: the CLI returns canonical model JSON (TrendSeries,
HealthAssessment, etc.), which has a different shape than the
KPI-aggregated dicts produced by ``_ins_provider.py``. This bridge
returns the raw CLI output — callers are responsible for transforming
the canonical shape into whatever the script expects.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CLI_MODULE = "deerflow.integrations.cli"

_DEFAULT_TIMEOUT = 60.0

_CONTAINER_PREFIX = "deer-flow-sandbox"

# Temp directory for params files — must be accessible from the container
_PARAMS_DIR = tempfile.gettempdir()


def _write_params_file(params_json: str) -> str:
    """Write params JSON to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="deerflow_params_", dir=_PARAMS_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(params_json)
    return path


def _cleanup_params_file(path: str) -> None:
    """Remove the temp params file (best-effort, never raises)."""
    try:
        os.unlink(path)
    except OSError:
        pass

# Environment variables that must be forwarded into the sandbox container
# when routing via docker exec.
_ENV_FORWARD_KEYS = (
    "DEER_FLOW_INTERNAL_AUTH_VALUE",
    "DEER_FLOW_EFFECTIVE_USER_ID",
    "DEER_FLOW_TENANT_ID",
    "USE_PLATFORM",
    "INS_BASE_URL",
    "INS_CONNECT_TIMEOUT",
    "INS_READ_TIMEOUT",
    "INS_WRITE_TIMEOUT",
    "INS_POOL_TIMEOUT",
    "FEATURES_TOOL_ROOT",
)


class PlatformBridgeError(Exception):
    """Raised when the CLI subprocess fails or returns invalid output."""


def _is_in_sandbox() -> bool:
    """Return True if this process is running inside the sandbox container."""
    return Path("/opt/features-tool").is_dir()


def _sandbox_container_name() -> str | None:
    """Derive the sandbox container name from DEER_FLOW_THREAD_ID.

    Mirrors AioSandboxProvider._deterministic_sandbox_id:
    ``container_name = deer-flow-sandbox-{sha256(thread_id)[:8]}``
    """
    thread_id = os.environ.get("DEER_FLOW_THREAD_ID")
    if not thread_id:
        return None
    sandbox_id = hashlib.sha256(thread_id.encode()).hexdigest()[:8]
    return f"{_CONTAINER_PREFIX}-{sandbox_id}"


def _docker_exec_cmd(
    inner_cmd: list[str],
    container_name: str,
) -> list[str]:
    """Wrap an inner CLI command in ``docker exec`` with env forwarding."""
    cmd = ["docker", "exec"]
    for key in _ENV_FORWARD_KEYS:
        value = os.environ.get(key)
        if value is not None:
            cmd.extend(["-e", f"{key}={value}"])
    cmd.append(container_name)
    cmd.extend(inner_cmd)
    return cmd


def _docker_cp_params_file(host_path: str, container_name: str) -> str:
    """Copy params file from host into container at a fixed path.

    Returns the container-side path.
    """
    container_path = "/tmp/deerflow_params.json"
    subprocess.run(
        ["docker", "cp", host_path, f"{container_name}:{container_path}"],
        check=True,
        capture_output=True,
    )
    return container_path


def _python_executable() -> str:
    """Resolve the Python interpreter to use for the subprocess.

    Prefers the same interpreter running this process so packages
    resolve identically.
    """
    return sys.executable


def call_capability(
    capability: str,
    params: dict[str, Any],
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Invoke the integration CLI subprocess and return parsed JSON output.

    When running on the host (outside the sandbox container), the CLI call
    is automatically routed into the sandbox container via ``docker exec``
    so that features-tool and other container-only dependencies are available.

    Args:
        capability: Capability key, e.g. ``"monitoring.trend"``.
        params: Query parameters as a dict (serialized to JSON for --params).
        tenant_id: Tenant ID. Defaults to ``DEER_FLOW_TENANT_ID`` env var.
        user_id: User ID. Defaults to ``DEER_FLOW_EFFECTIVE_USER_ID`` env var
            or ``"cli-subprocess"``.
        timeout: Subprocess timeout in seconds.
        python_executable: Optional interpreter override.

    Returns:
        Parsed JSON output dict from the CLI.

    Raises:
        PlatformBridgeError: On subprocess failure, timeout, or invalid JSON.
    """
    if tenant_id is None:
        tenant_id = os.environ.get("DEER_FLOW_TENANT_ID", "default")
    if user_id is None:
        user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID", "cli-subprocess")

    in_sandbox = _is_in_sandbox()
    if in_sandbox:
        # sandbox base image ships python3.10, but deerflow-harness needs >=3.12
        interpreter = python_executable or "python3.12"
    else:
        interpreter = "python3"

    # Write params to a temp file to avoid ARG_MAX limit on command-line args
    params_json = json.dumps(params, ensure_ascii=False)
    params_file = _write_params_file(params_json)

    try:
        inner_cmd = [
            interpreter,
            "-m",
            _CLI_MODULE,
            "--capability",
            capability,
            "--tenant-id",
            tenant_id,
            "--user-id",
            user_id,
            "--params-file",
            params_file,
        ]

        if not in_sandbox:
            container_name = _sandbox_container_name()
            if container_name is None:
                raise PlatformBridgeError(
                    "Cannot route CLI to sandbox: DEER_FLOW_THREAD_ID not set"
                )
            # Copy params file into container for docker exec
            container_params_path = _docker_cp_params_file(params_file, container_name)
            inner_cmd[-1] = container_params_path
            cmd = _docker_exec_cmd(inner_cmd, container_name)
            logger.info(
                "Platform bridge (docker exec → %s): %s (tenant=%s, user=%s)",
                container_name, capability, tenant_id, user_id,
            )
        else:
            cmd = inner_cmd
            logger.info(
                "Platform bridge (in-container): %s (tenant=%s, user=%s)",
                capability, tenant_id, user_id,
            )

        return _run_subprocess(cmd, timeout=timeout, label=f"capability {capability}")
    finally:
        _cleanup_params_file(params_file)


def call_action(
    action: str,
    adapter: str,
    params: dict[str, Any],
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Invoke the integration CLI in action mode for adapter-internal computation.

    Action mode bypasses CapabilityRouter and calls adapter-internal pure
    functions directly. Used for InS-specific KPI aggregation and point
    selection that understand the data model (position_types, endpoint_series).

    When running on the host (outside the sandbox container), the CLI call
    is automatically routed into the sandbox container via ``docker exec``.

    Args:
        action: Action name, e.g. ``"aggregate_kpi"`` or ``"select_points"``.
        adapter: Adapter key, e.g. ``"ins_prod"``.
        params: Action parameters as a dict (serialized to JSON for --params).
        tenant_id: Tenant ID. Defaults to ``DEER_FLOW_TENANT_ID`` env var.
        user_id: User ID. Defaults to ``DEER_FLOW_EFFECTIVE_USER_ID`` env var
            or ``"cli-subprocess"``.
        timeout: Subprocess timeout in seconds.
        python_executable: Optional interpreter override.

    Returns:
        Parsed JSON output dict from the CLI.

    Raises:
        PlatformBridgeError: On subprocess failure, timeout, or invalid JSON.

    Example:
        >>> result = call_action(
        ...     action="aggregate_kpi",
        ...     adapter="ins_prod",
        ...     params={
        ...         "trend_data": {"EQ1": [...]},
        ...         "kpi_keys": ["runtime_rate"],
        ...     },
        ... )
        >>> kpis = result["data"]["kpis"]["EQ1"]["runtime_rate"]
    """
    if tenant_id is None:
        tenant_id = os.environ.get("DEER_FLOW_TENANT_ID", "default")
    if user_id is None:
        user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID", "cli-subprocess")

    in_sandbox = _is_in_sandbox()
    if in_sandbox:
        # sandbox base image ships python3.10, but deerflow-harness needs >=3.12
        interpreter = python_executable or "python3.12"
    else:
        interpreter = "python3"

    # Write params to a temp file to avoid ARG_MAX limit on command-line args
    params_json = json.dumps(params, ensure_ascii=False)
    params_file = _write_params_file(params_json)

    try:
        inner_cmd = [
            interpreter,
            "-m",
            _CLI_MODULE,
            "--action",
            action,
            "--adapter",
            adapter,
            "--tenant-id",
            tenant_id,
            "--user-id",
            user_id,
            "--params-file",
            params_file,
        ]

        if not in_sandbox:
            container_name = _sandbox_container_name()
            if container_name is None:
                raise PlatformBridgeError(
                    "Cannot route CLI to sandbox: DEER_FLOW_THREAD_ID not set"
                )
            # Copy params file into container for docker exec
            container_params_path = _docker_cp_params_file(params_file, container_name)
            inner_cmd[-1] = container_params_path
            cmd = _docker_exec_cmd(inner_cmd, container_name)
            logger.info(
                "Platform bridge action (docker exec → %s): %s on %s (tenant=%s, user=%s)",
                container_name, action, adapter, tenant_id, user_id,
            )
        else:
            cmd = inner_cmd
            logger.info(
                "Platform bridge action (in-container): %s on %s (tenant=%s, user=%s)",
                action, adapter, tenant_id, user_id,
            )

        return _run_subprocess(cmd, timeout=timeout, label=f"action {action}")
    finally:
        _cleanup_params_file(params_file)


def _run_subprocess(
    cmd: list[str],
    *,
    timeout: float,
    label: str,
) -> dict[str, Any]:
    """Execute the CLI subprocess and parse its JSON output.

    Shared by ``call_capability`` and ``call_action``.
    """
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PlatformBridgeError(
            f"CLI subprocess timed out after {timeout}s for {label}"
        ) from exc
    except OSError as exc:
        raise PlatformBridgeError(
            f"Failed to launch CLI subprocess: {exc}"
        ) from exc

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if not stdout:
        raise PlatformBridgeError(
            f"CLI subprocess produced no stdout (exit={completed.returncode}, stderr={stderr[:500]})"
        )

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PlatformBridgeError(
            f"CLI subprocess returned invalid JSON: {stdout[:200]}"
        ) from exc

    if stderr:
        logger.debug("CLI subprocess stderr: %s", stderr[:1000])

    if not isinstance(result, dict):
        raise PlatformBridgeError(
            f"CLI subprocess returned non-dict: {type(result).__name__}"
        )

    if not result.get("ok"):
        error_msg = result.get("error", "unknown error")
        error_type = result.get("error_type", "UnknownError")
        if stderr:
            error_msg += f" [stderr: {stderr[:500]}]"
        raise PlatformBridgeError(
            f"CLI subprocess failed [{error_type}]: {error_msg}"
        )

    return result


def is_platform_mode() -> bool:
    """Check if ``USE_PLATFORM`` env var is set to a truthy value."""
    value = os.environ.get("USE_PLATFORM", "").lower()
    return value in ("true", "1", "yes")

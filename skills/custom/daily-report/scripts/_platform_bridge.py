"""平台桥接层 — 通过子进程调用集成 CLI 获取日报数据。

桥接调用方式::

    python -m deerflow.integrations.cli \\
        --capability <key> \\
        --tenant-id <id> \\
        --user-id <id> \\
        --params <json>

并解析 JSON 输出。失败时调用方回退到旧路径。

运行环境
--------
CLI 桥接依赖 ``features-tool``（InS HTTP 客户端），仅在 sandbox Docker 容器
（``/opt/features-tool``）中可用。当查询脚本在宿主机后端运行时，桥接层自动通过
``docker exec`` 将调用路由到 sandbox 容器，容器名由 ``DEER_FLOW_THREAD_ID``
的 sha256 哈希派生（与 AioSandboxProvider 逻辑一致）。

架构说明：CLI 返回规范模型 JSON（TrendSeries 等），桥接层原样返回原始 CLI 输出，
调用方负责将规范格式转换为脚本所需的结构。
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

# 临时目录，用于存放 params 文件（需对容器可见）
_PARAMS_DIR = tempfile.gettempdir()


def _write_params_file(params_json: str) -> str:
    """将 params JSON 写入临时文件并返回路径。"""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="deerflow_params_", dir=_PARAMS_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(params_json)
    return path


def _cleanup_params_file(path: str) -> None:
    """删除临时 params 文件（尽力而为，不抛异常）。"""
    try:
        os.unlink(path)
    except OSError:
        pass


# 通过 docker exec 路由时需要转发到容器内的环境变量
_ENV_FORWARD_KEYS = (
    "DEER_FLOW_INTERNAL_AUTH_VALUE",
    "DEER_FLOW_EFFECTIVE_USER_ID",
    "DEER_FLOW_TENANT_ID",
    "USE_PLATFORM",
    "INS_USERNAME",
    "INS_PASSWORD",
    "INS_BASE_URL",
    "INS_CONNECT_TIMEOUT",
    "INS_READ_TIMEOUT",
    "INS_WRITE_TIMEOUT",
    "INS_POOL_TIMEOUT",
    "FEATURES_TOOL_ROOT",
)


class PlatformBridgeError(Exception):
    """CLI 子进程失败或返回无效输出时抛出。"""


def _is_in_sandbox() -> bool:
    """判断当前进程是否运行在 sandbox 容器内。"""
    return Path("/opt/features-tool").is_dir()


def _sandbox_container_name() -> str | None:
    """根据 ``DEER_FLOW_THREAD_ID`` 派生 sandbox 容器名。

    与 AioSandboxProvider._deterministic_sandbox_id 逻辑一致：
    ``容器名 = deer-flow-sandbox-{sha256(thread_id)[:8]}``
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
    """将内部 CLI 命令包装为 ``docker exec`` 命令，并转发环境变量。"""
    cmd = ["docker", "exec"]
    for key in _ENV_FORWARD_KEYS:
        value = os.environ.get(key)
        if value is not None:
            cmd.extend(["-e", f"{key}={value}"])
    cmd.append(container_name)
    cmd.extend(inner_cmd)
    return cmd


def _docker_cp_params_file(host_path: str, container_name: str) -> str:
    """将 params 文件从宿主机复制到容器内固定路径。

    Returns:
        容器内的文件路径
    """
    container_path = "/tmp/deerflow_params.json"
    subprocess.run(
        ["docker", "cp", host_path, f"{container_name}:{container_path}"],
        check=True,
        capture_output=True,
    )
    return container_path


def _python_executable() -> str:
    """解析用于子进程的 Python 解释器路径。

    优先使用当前进程的同一解释器，确保包解析一致。
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
    """调用集成 CLI 子进程的能力接口并返回 JSON 输出。

    当运行在宿主机（不在 sandbox 容器内）时，自动通过 ``docker exec``
    路由到 sandbox 容器，确保 features-tool 等依赖可用。

    Args:
        capability: 能力键，如 ``"monitoring.trend"``
        params: 查询参数字典（序列化为 JSON 后通过临时文件传递）
        tenant_id: 租户 ID，默认取 ``DEER_FLOW_TENANT_ID`` 环境变量
        user_id: 用户 ID，默认取 ``DEER_FLOW_EFFECTIVE_USER_ID`` 或 ``"cli-subprocess"``
        timeout: 子进程超时秒数
        python_executable: 可选解释器覆盖

    Returns:
        CLI 返回的 JSON 输出字典

    Raises:
        PlatformBridgeError: 子进程失败、超时或返回无效 JSON
    """
    if tenant_id is None:
        tenant_id = os.environ.get("DEER_FLOW_TENANT_ID", "default")
    if user_id is None:
        user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID", "cli-subprocess")

    in_sandbox = _is_in_sandbox()
    if in_sandbox:
        # sandbox 基础镜像自带 python3.10，deerflow-harness 需要 >=3.12
        interpreter = python_executable or "python3.12"
    else:
        interpreter = "python3"

    # 通过临时文件传递参数，避免命令行 ARG_MAX 限制
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
            # 将 params 文件复制到容器内供 docker exec 使用
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
    """以 action 模式调用集成 CLI，执行适配器内部计算。

    Action 模式绕过 CapabilityRouter，直接调用适配器内部的纯函数。
    用于 InS 特定的 KPI 聚合和测点选择，这些操作需要理解数据模型
    （position_types、endpoint_series）。

    当运行在宿主机时，自动通过 ``docker exec`` 路由到 sandbox 容器。

    Args:
        action: action 名称，如 ``"aggregate_kpi"`` / ``"select_points"``
        adapter: 适配器键，如 ``"ins_prod"``
        params: action 参数字典
        tenant_id: 租户 ID，默认取 ``DEER_FLOW_TENANT_ID`` 环境变量
        user_id: 用户 ID，默认取 ``DEER_FLOW_EFFECTIVE_USER_ID`` 或 ``"cli-subprocess"``
        timeout: 子进程超时秒数
        python_executable: 可选解释器覆盖

    Returns:
        CLI 返回的 JSON 输出字典

    Raises:
        PlatformBridgeError: 子进程失败、超时或返回无效 JSON
    """
    if tenant_id is None:
        tenant_id = os.environ.get("DEER_FLOW_TENANT_ID", "default")
    if user_id is None:
        user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID", "cli-subprocess")

    in_sandbox = _is_in_sandbox()
    if in_sandbox:
        # sandbox 基础镜像自带 python3.10，deerflow-harness 需要 >=3.12
        interpreter = python_executable or "python3.12"
    else:
        interpreter = "python3"

    # 通过临时文件传递参数，避免命令行 ARG_MAX 限制
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
            # 将 params 文件复制到容器内供 docker exec 使用
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
    """执行 CLI 子进程并解析其 JSON 输出。

    由 ``call_capability`` 和 ``call_action`` 共用。
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
    """检查 ``USE_PLATFORM`` 环境变量是否设为真值。"""
    value = os.environ.get("USE_PLATFORM", "").lower()
    return value in ("true", "1", "yes")

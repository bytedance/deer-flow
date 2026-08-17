"""Process-local bridge from Agent tool wrappers to the Gateway task service."""

from __future__ import annotations

from typing import Any, Protocol

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.tasks.models import TaskSubmitRequest


class McpTaskConfigurationError(RuntimeError):
    """The configured long-running MCP contract cannot run safely."""


class McpTaskSubmitter(Protocol):
    async def submit(
        self,
        *,
        driver_name: str,
        request: TaskSubmitRequest,
        now: Any | None = None,
    ) -> dict: ...


_submitter: McpTaskSubmitter | None = None
_TaskServerConfigSnapshot = tuple[dict[str, dict[str, Any]], Any]
_task_server_config_snapshot: _TaskServerConfigSnapshot | None = None


def _task_server_configs(extensions_config: ExtensionsConfig) -> _TaskServerConfigSnapshot:
    servers: dict[str, dict[str, Any]] = {}
    for server_name, server in extensions_config.get_enabled_mcp_servers().items():
        if not server.task_toolsets:
            continue
        runtime_config = server.model_dump(mode="json")
        for presentation_field in ("description", "routing", "tools", "tool_name_prefix"):
            runtime_config.pop(presentation_field, None)
        servers[server_name] = runtime_config
    interceptors = (extensions_config.model_extra or {}).get("mcpInterceptors") if servers else None
    return servers, interceptors


def set_mcp_task_config_snapshot(extensions_config: ExtensionsConfig | None) -> None:
    """Freeze task-enabled server settings for one Gateway process lifetime."""
    global _task_server_config_snapshot
    _task_server_config_snapshot = None if extensions_config is None else _task_server_configs(extensions_config)


def validate_mcp_task_config_snapshot(extensions_config: ExtensionsConfig) -> None:
    """Reject hot changes that would split tool discovery from background calls."""
    if _task_server_config_snapshot is None:
        return
    current = _task_server_configs(extensions_config)
    if current == _task_server_config_snapshot:
        return
    current_servers, current_interceptors = current
    startup_servers, startup_interceptors = _task_server_config_snapshot
    changed = sorted(server_name for server_name in current_servers.keys() | startup_servers.keys() if current_servers.get(server_name) != startup_servers.get(server_name))
    if current_interceptors != startup_interceptors:
        changed.append("mcpInterceptors")
    names = ", ".join(changed) or "<unknown>"
    raise McpTaskConfigurationError(f"MCP task-enabled server configuration changed after Gateway startup ({names}); restart DeerFlow before using durable task tools")


def set_mcp_task_submitter(submitter: McpTaskSubmitter | None) -> None:
    """Install or clear the Gateway-owned submit boundary for this process."""
    global _submitter
    _submitter = submitter


def get_mcp_task_submitter() -> McpTaskSubmitter:
    if _submitter is None:
        raise McpTaskConfigurationError("The MCP task runtime is not initialized. Run this tool through the Gateway with mcp_tasks.enabled=true and a SQL database backend.")
    return _submitter


def configured_task_toolset_count(extensions_config: ExtensionsConfig) -> int:
    return sum(len(server.task_toolsets) for server in extensions_config.get_enabled_mcp_servers().values())


def validate_mcp_task_runtime_configuration(
    *,
    mcp_tasks_config: Any,
    extensions_config: ExtensionsConfig,
    repository_available: bool,
) -> None:
    """Fail startup when task toolsets would silently fall back to sync calls."""
    if configured_task_toolset_count(extensions_config) == 0:
        return
    if not bool(getattr(mcp_tasks_config, "enabled", False)):
        raise McpTaskConfigurationError("MCP task_toolsets are configured, so mcp_tasks.enabled=true is required; DeerFlow will not silently expose these tools as synchronous calls.")
    if not repository_available:
        raise McpTaskConfigurationError("MCP task_toolsets require durable SQL persistence. Set database.backend to 'sqlite' or 'postgres'; the memory backend cannot recover tasks after restart.")
    from deerflow.mcp.client import build_server_params

    for server_name, server in extensions_config.get_enabled_mcp_servers().items():
        if not server.task_toolsets:
            continue
        try:
            build_server_params(server_name, server)
        except ValueError as exc:
            raise McpTaskConfigurationError(str(exc)) from exc

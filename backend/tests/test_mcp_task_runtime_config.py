from types import SimpleNamespace

import pytest

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.tasks.runtime import (
    McpTaskConfigurationError,
    set_mcp_task_config_snapshot,
    validate_mcp_task_config_snapshot,
    validate_mcp_task_runtime_configuration,
)


def _extensions() -> ExtensionsConfig:
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "task_toolsets": [
                        {
                            "name": "reports",
                            "submit_tool": "submit_report",
                            "status_tool": "status_report",
                            "cancel_tool": "cancel_report",
                        }
                    ]
                }
            }
        }
    )


def test_configured_task_toolsets_require_enabled_runtime() -> None:
    with pytest.raises(McpTaskConfigurationError, match="mcp_tasks.enabled=true"):
        validate_mcp_task_runtime_configuration(
            mcp_tasks_config=SimpleNamespace(enabled=False),
            extensions_config=_extensions(),
            repository_available=True,
        )


def test_configured_task_toolsets_require_sql_persistence() -> None:
    with pytest.raises(McpTaskConfigurationError, match="database.backend"):
        validate_mcp_task_runtime_configuration(
            mcp_tasks_config=SimpleNamespace(enabled=True),
            extensions_config=_extensions(),
            repository_available=False,
        )


def test_no_task_toolsets_leave_existing_mcp_runtime_unchanged() -> None:
    validate_mcp_task_runtime_configuration(
        mcp_tasks_config=SimpleNamespace(enabled=False),
        extensions_config=ExtensionsConfig(),
        repository_available=False,
    )


def test_task_toolset_server_transport_is_validated_at_startup() -> None:
    extensions = _extensions()
    extensions.mcp_servers["reports"].command = None

    with pytest.raises(McpTaskConfigurationError, match="requires 'command'"):
        validate_mcp_task_runtime_configuration(
            mcp_tasks_config=SimpleNamespace(enabled=True),
            extensions_config=extensions,
            repository_available=True,
        )


def test_task_enabled_server_changes_require_gateway_restart() -> None:
    startup = _extensions()
    current = _extensions()
    current.mcp_servers["reports"].env["TOKEN"] = "rotated"
    set_mcp_task_config_snapshot(startup)
    try:
        with pytest.raises(McpTaskConfigurationError, match="reports.*restart"):
            validate_mcp_task_config_snapshot(current)
    finally:
        set_mcp_task_config_snapshot(None)


def test_unrelated_extension_changes_do_not_invalidate_task_runtime_snapshot() -> None:
    startup = _extensions()
    current = ExtensionsConfig.model_validate(
        {
            **startup.model_dump(by_alias=True),
            "skills": {"writer": {"enabled": False}},
            "mcpServers": {
                **startup.model_dump(by_alias=True)["mcpServers"],
                "search": {"command": "search-mcp"},
            },
        }
    )
    current.mcp_servers["reports"].description = "Updated Agent-facing description"
    set_mcp_task_config_snapshot(startup)
    try:
        validate_mcp_task_config_snapshot(current)
    finally:
        set_mcp_task_config_snapshot(None)


def test_disabled_task_server_changes_do_not_invalidate_task_runtime_snapshot() -> None:
    startup = _extensions()
    startup.mcp_servers["reports"].enabled = False
    current = _extensions()
    current.mcp_servers["reports"].enabled = False
    current.mcp_servers["reports"].env["TOKEN"] = "rotated"
    set_mcp_task_config_snapshot(startup)
    try:
        validate_mcp_task_config_snapshot(current)
    finally:
        set_mcp_task_config_snapshot(None)


def test_mcp_interceptor_changes_require_gateway_restart_for_task_tools() -> None:
    startup = _extensions()
    current = ExtensionsConfig.model_validate(
        {
            **startup.model_dump(by_alias=True),
            "mcpInterceptors": ["example.interceptor:build"],
        }
    )
    set_mcp_task_config_snapshot(startup)
    try:
        with pytest.raises(McpTaskConfigurationError, match="mcpInterceptors.*restart"):
            validate_mcp_task_config_snapshot(current)
    finally:
        set_mcp_task_config_snapshot(None)


def test_mcp_interceptor_changes_remain_hot_reloadable_without_task_tools() -> None:
    startup = ExtensionsConfig()
    current = ExtensionsConfig.model_validate({"mcpInterceptors": ["example.interceptor:build"]})
    set_mcp_task_config_snapshot(startup)
    try:
        validate_mcp_task_config_snapshot(current)
    finally:
        set_mcp_task_config_snapshot(None)

from types import SimpleNamespace

import pytest

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.tasks.runtime import McpTaskConfigurationError, validate_mcp_task_runtime_configuration


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

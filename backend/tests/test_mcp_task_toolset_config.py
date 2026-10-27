import pytest
from pydantic import ValidationError

from app.gateway.routers.mcp import McpServerConfigResponse
from deerflow.config.extensions_config import ExtensionsConfig


def test_task_toolsets_preserve_raw_tool_names_and_support_multiple_groups() -> None:
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "http",
                    "url": "https://example.test/mcp",
                    "task_toolsets": [
                        {
                            "name": "report-generation",
                            "submit_tool": "submit_report",
                            "status_tool": "get_report_status",
                            "cancel_tool": "cancel_report",
                        },
                        {
                            "name": "data-export",
                            "submit_tool": "start_export",
                            "status_tool": "get_export_status",
                            "cancel_tool": "cancel_export",
                        },
                    ],
                }
            }
        }
    )

    toolsets = config.mcp_servers["reports"].task_toolsets
    assert [toolset.name for toolset in toolsets] == ["report-generation", "data-export"]
    assert toolsets[0].model_dump() == {
        "name": "report-generation",
        "submit_tool": "submit_report",
        "status_tool": "get_report_status",
        "cancel_tool": "cancel_report",
    }
    response = McpServerConfigResponse.model_validate(config.mcp_servers["reports"].model_dump())
    assert response.task_toolsets[0].submit_tool == "submit_report"


@pytest.mark.parametrize(
    "duplicate_field,duplicate_value",
    [
        ("status_tool", "submit_report"),
        ("cancel_tool", "submit_report"),
    ],
)
def test_task_toolsets_reject_reusing_one_raw_tool_in_multiple_roles(
    duplicate_field: str,
    duplicate_value: str,
) -> None:
    toolset = {
        "name": "report-generation",
        "submit_tool": "submit_report",
        "status_tool": "get_report_status",
        "cancel_tool": "cancel_report",
    }
    toolset[duplicate_field] = duplicate_value

    with pytest.raises(ValidationError, match="must be unique across task_toolsets"):
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "reports": {
                        "task_toolsets": [toolset],
                    }
                }
            }
        )


def test_task_toolsets_reject_reusing_one_raw_tool_across_groups() -> None:
    with pytest.raises(ValidationError, match="submit_report.*must be unique"):
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "reports": {
                        "task_toolsets": [
                            {
                                "name": "first",
                                "submit_tool": "submit_report",
                                "status_tool": "status_report",
                                "cancel_tool": "cancel_report",
                            },
                            {
                                "name": "second",
                                "submit_tool": "start_export",
                                "status_tool": "submit_report",
                                "cancel_tool": "cancel_export",
                            },
                        ]
                    }
                }
            }
        )


@pytest.mark.parametrize(
    ("server_name", "task_name", "match"),
    [
        ("   ", "reports", "server name.*128"),
        ("s" * 129, "reports", "server name.*128"),
        ("reports", "   ", "task toolset name must not be empty"),
        ("reports", "t" * 256, "at most 255"),
    ],
)
def test_task_toolsets_reject_names_that_do_not_fit_durable_storage(
    server_name: str,
    task_name: str,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    server_name: {
                        "task_toolsets": [
                            {
                                "name": task_name,
                                "submit_tool": "submit_report",
                                "status_tool": "status_report",
                                "cancel_tool": "cancel_report",
                            }
                        ]
                    }
                }
            }
        )

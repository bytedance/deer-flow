from app.gateway.routers.agents import (
    ToolGroupsResponse,
    _configured_tool_group_names,
    router,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import ToolGroupConfig


def test_tool_group_catalog_preserves_operator_order_and_deduplicates() -> None:
    config = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        tool_groups=[
            ToolGroupConfig(name="web"),
            ToolGroupConfig(name="file:read"),
            ToolGroupConfig(name="web"),
            ToolGroupConfig(name="knowledge"),
        ],
    )

    response = ToolGroupsResponse(tool_groups=_configured_tool_group_names(config))

    assert response.model_dump() == {
        "tool_groups": ["web", "file:read", "knowledge"],
    }


def test_tool_group_catalog_does_not_reserve_a_valid_agent_name() -> None:
    paths = {route.path for route in router.routes}

    assert "/api/agent-tool-groups" in paths
    assert "/api/agents/tool-groups" not in paths

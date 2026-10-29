from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext, Permissions
from app.gateway.deps import get_config
from app.gateway.routers.agents import (
    ToolGroupsResponse,
    _configured_tool_group_names,
    router,
)
from deerflow.config.agents_api_config import AgentsApiConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import ToolGroupConfig


@pytest.fixture
def tool_group_config() -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        tool_groups=[
            ToolGroupConfig(name="web"),
            ToolGroupConfig(name="file:read"),
            ToolGroupConfig(name="web"),
            ToolGroupConfig(name="knowledge"),
        ],
    )


@pytest.fixture
def tool_group_client(monkeypatch: pytest.MonkeyPatch, tool_group_config: AppConfig):
    api_config = AgentsApiConfig(enabled=True)
    auth = AuthContext(
        user=User(email="tool-groups@example.com", password_hash="test-only"),
        permissions=[Permissions.AGENTS_READ],
    )
    monkeypatch.setattr("app.gateway.routers.agents.get_agents_api_config", lambda: api_config)
    monkeypatch.setattr("app.gateway.authz._authenticate", AsyncMock(return_value=auth))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: tool_group_config
    with TestClient(app) as client:
        yield client, auth, api_config


def test_tool_group_catalog_preserves_operator_order_and_deduplicates(tool_group_config: AppConfig) -> None:
    response = ToolGroupsResponse(tool_groups=_configured_tool_group_names(tool_group_config))

    assert response.model_dump() == {
        "tool_groups": ["web", "file:read", "knowledge"],
    }


def test_tool_group_catalog_does_not_reserve_a_valid_agent_name() -> None:
    paths = {route.path for route in router.routes}

    assert "/api/agent-tool-groups" in paths
    assert "/api/agents/tool-groups" not in paths


def test_tool_group_catalog_returns_configured_names_over_http(tool_group_client) -> None:
    client, _, _ = tool_group_client

    response = client.get("/api/agent-tool-groups")

    assert response.status_code == 200
    assert response.json() == {"tool_groups": ["web", "file:read", "knowledge"]}


def test_tool_group_catalog_rejects_disabled_agents_api(tool_group_client) -> None:
    client, _, api_config = tool_group_client
    api_config.enabled = False

    response = client.get("/api/agent-tool-groups")

    assert response.status_code == 403
    assert "Custom-agent management API is disabled" in response.json()["detail"]


@pytest.mark.parametrize("permissions", [[], [Permissions.AGENTS_WRITE]])
def test_tool_group_catalog_requires_agents_read_permission(tool_group_client, permissions: list[str]) -> None:
    client, auth, _ = tool_group_client
    auth.permissions = permissions

    response = client.get("/api/agent-tool-groups")

    assert response.status_code == 403
    assert response.json() == {"detail": "Permission denied: agents:read"}


def test_tool_group_catalog_requires_authentication(tool_group_client) -> None:
    client, auth, _ = tool_group_client
    auth.user = None

    response = client.get("/api/agent-tool-groups")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}

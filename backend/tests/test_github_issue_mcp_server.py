import asyncio
import json
import sys

import httpx
import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient

from deerflow.config.extensions_config import McpServerConfig
from deerflow.mcp.client import build_server_params
from deerflow.mcp.tools import get_mcp_tools
from deerflow.mcp_servers import github_issue
from deerflow.mcp_servers.github_issue import fetch_github_issue


@pytest.mark.asyncio
async def test_fetch_github_issue_returns_normalized_issue():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/acme/demo/issues/42"

        return httpx.Response(
            200,
            json={
                "number": 42,
                "title": "Checkpoint recovery",
                "body": "Agent should resume",
                "state": "open",
                "labels": [{"name": "bug"}, {"name": "agent"}],
                "html_url": "https://github.com/acme/demo/issues/42",
                "user": {"login": "alice"},
            },
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://api.github.com",
    ) as client:
        result = await fetch_github_issue(client, "acme/demo", 42)

    assert result == {
        "repository": "acme/demo",
        "number": 42,
        "title": "Checkpoint recovery",
        "body": "Agent should resume",
        "state": "open",
        "labels": ["bug", "agent"],
        "url": "https://github.com/acme/demo/issues/42",
        "author": "alice",
    }


@pytest.mark.asyncio
async def test_mcp_registers_get_github_issue_tool():
    tools = await github_issue.mcp.list_tools()

    assert "get_github_issue" in [tool.name for tool in tools]


@pytest.mark.asyncio
async def test_get_github_issue_tool_delegates_and_closes_client(monkeypatch):
    expected = {"repository": "acme/demo", "number": 42}
    captured = {}

    async def fake_fetch(client, repository, issue_number):
        captured["client"] = client
        assert client.base_url == httpx.URL("https://api.github.com")
        assert repository == "acme/demo"
        assert issue_number == 42
        return expected

    monkeypatch.setattr(github_issue, "fetch_github_issue", fake_fetch)

    result = await github_issue.get_github_issue("acme/demo", 42)

    assert result == expected
    assert captured["client"].is_closed


@pytest.mark.asyncio
async def test_get_github_issue_tool_uses_github_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    async def fake_fetch(client, repository, issue_number):
        assert client.headers["Authorization"] == "Bearer test-token"
        return {"repository": repository, "number": issue_number}

    monkeypatch.setattr(github_issue, "fetch_github_issue", fake_fetch)

    result = await github_issue.get_github_issue("acme/demo", 42)

    assert result == {"repository": "acme/demo", "number": 42}


def test_main_runs_mcp_over_stdio(monkeypatch):
    captured = {}

    def fake_run(*, transport):
        captured["transport"] = transport

    monkeypatch.setattr(github_issue.mcp, "run", fake_run)

    github_issue.main()

    assert captured["transport"] == "stdio"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deerflow_client_discovers_github_issue_tool_over_stdio():
    server_config = McpServerConfig(
        enabled=True,
        type="stdio",
        command=sys.executable,
        args=["-m", "deerflow.mcp_servers.github_issue"],
    )
    connection = build_server_params("github_issue", server_config)
    client = MultiServerMCPClient(
        {"github_issue": connection},
        tool_name_prefix=True,
    )

    tools = await asyncio.wait_for(
        client.get_tools(server_name="github_issue"),
        timeout=60,
    )

    assert "github_issue_get_github_issue" in [tool.name for tool in tools]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_mcp_tools_loads_server_from_extensions_config(tmp_path, monkeypatch):
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github_issue": {
                        "enabled": True,
                        "type": "stdio",
                        "command": sys.executable,
                        "args": ["-m", "deerflow.mcp_servers.github_issue"],
                        "env": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    tools = await asyncio.wait_for(get_mcp_tools(), timeout=60)

    assert "github_issue_get_github_issue" in [tool.name for tool in tools]

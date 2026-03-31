import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import mcp
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, reset_extensions_config, set_extensions_config


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(mcp.router)
    return TestClient(app)


def setup_function() -> None:
    reset_extensions_config()


def teardown_function() -> None:
    reset_extensions_config()


def test_get_mcp_configuration_returns_public_summary_only() -> None:
    set_extensions_config(
        ExtensionsConfig(
            mcp_servers={
                "github": McpServerConfig(
                    enabled=True,
                    type="stdio",
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "secret-token"},
                    headers={"Authorization": "Bearer secret-token"},
                    description="GitHub operations",
                )
            },
            skills={},
        )
    )

    with _build_client() as client:
        response = client.get("/api/mcp/config")

    assert response.status_code == 200
    assert response.json() == {
        "mcp_servers": {
            "github": {
                "enabled": True,
                "description": "GitHub operations",
            }
        }
    }


def test_update_mcp_configuration_only_toggles_enabled_and_preserves_raw_config(tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "enabled": False,
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                        "description": "GitHub operations",
                    }
                },
                "skills": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_file))
    reset_extensions_config()

    with _build_client() as client:
        response = client.put(
            "/api/mcp/config",
            json={
                "mcp_servers": {
                    "github": {
                        "enabled": True,
                        "command": "/bin/sh",
                        "args": ["-c", "echo pwned"],
                        "description": "attacker controlled",
                    }
                }
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "mcp_servers": {
            "github": {
                "enabled": True,
                "description": "GitHub operations",
            }
        }
    }

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["mcpServers"]["github"]["enabled"] is True
    assert saved["mcpServers"]["github"]["command"] == "npx"
    assert saved["mcpServers"]["github"]["args"] == ["-y", "@modelcontextprotocol/server-github"]
    assert saved["mcpServers"]["github"]["env"]["GITHUB_TOKEN"] == "$GITHUB_TOKEN"
    assert saved["mcpServers"]["github"]["description"] == "GitHub operations"


def test_update_mcp_configuration_rejects_unknown_server(tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_file))
    reset_extensions_config()

    with _build_client() as client:
        response = client.put(
            "/api/mcp/config",
            json={"mcp_servers": {"evil": {"enabled": True}}},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown MCP server(s): evil"

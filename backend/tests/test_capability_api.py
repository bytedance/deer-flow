"""Exercise catalog installation through HTTP and the existing on-disk MCP store."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway import capabilities
from app.gateway.deps import get_config
from app.gateway.routers import capabilities as router
from app.gateway.routers import mcp
from deerflow.config.extensions_config import ExtensionsConfig


@pytest.fixture
def capability_client(tmp_path, monkeypatch):
    path = tmp_path / "extensions_config.json"
    path.write_text(json.dumps({"mcpServers": {"legacy": {"enabled": True, "type": "http", "url": "https://private.example/mcp", "headers": {"Authorization": "Bearer private-secret"}, "capability": {"plugin_id": 42}}}, "skills": {}}))
    monkeypatch.setattr(ExtensionsConfig, "resolve_config_path", lambda *args: path)
    monkeypatch.setattr(mcp, "reload_extensions_config", lambda: None)
    monkeypatch.setattr(mcp, "reset_mcp_tools_cache", lambda: None)
    app = FastAPI()
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(system_role=request.headers.get("test-role", "admin"))
        return await call_next(request)

    app.include_router(router.router)
    app.include_router(mcp.router)
    with TestClient(app) as client:
        yield client, path


def test_discovery_never_exposes_connection_secrets_and_tolerates_legacy_extras(capability_client):
    client, _ = capability_client
    result = client.get("/api/capabilities/installations/mcp", headers={"test-role": "user"})
    assert result.status_code == 200
    assert result.json()["can_manage"] is False
    item = result.json()["items"][0]
    assert item["id"] and item["plugin_id"] is None
    assert item["auth_status"] == "configured" and item["health"] == "unknown"
    for excluded in ("private-secret", "private.example", "Authorization", "headers"):
        assert excluded not in result.text


def test_catalog_install_edit_disable_delete_preserves_existing_store_and_identity(capability_client):
    client, path = capability_client
    body = {"plugin_id": "github", "name": "team-code", "configuration": {"enabled": True, "type": "http", "url": "https://example.test/mcp", "headers": {"Authorization": "Bearer team-secret"}}}
    response = client.post("/api/capabilities/installations", json=body)
    assert response.status_code == 200, response.text
    installed = next(item for item in response.json()["items"] if item["name"] == "team-code")
    identity = installed["id"]
    assert installed["plugin_id"] == "github"
    raw = json.loads(path.read_text())
    assert raw["mcpServers"]["legacy"]["headers"]["Authorization"] == "Bearer private-secret"
    assert raw["mcpServers"]["team-code"]["headers"]["Authorization"] == "Bearer team-secret"
    # Old clients do not know about capability metadata; editing must retain identity.
    result = client.put("/api/mcp/config/server", json={"server_name": "team-code", "server": {"enabled": False, "type": "http", "url": "https://example.test/new", "headers": {"Authorization": "***"}}})
    assert result.status_code == 200, result.text
    saved = json.loads(path.read_text())["mcpServers"]["team-code"]
    assert saved["capability"]["id"] == identity
    assert saved["capability"]["plugin_id"] == "github"
    assert saved["headers"]["Authorization"] == "Bearer team-secret"
    assert saved["enabled"] is False
    duplicate = client.post("/api/capabilities/installations", json=body)
    assert duplicate.status_code == 409
    assert client.delete("/api/mcp/config/servers/team-code").status_code == 200
    assert set(json.loads(path.read_text())["mcpServers"]) == {"legacy"}
    recreated = client.post("/api/capabilities/installations", json=body)
    replacement = next(item for item in recreated.json()["items"] if item["name"] == "team-code")
    assert replacement["id"] != identity


def test_only_admin_may_install_and_bad_configuration_is_422(capability_client):
    client, path = capability_client
    before = path.read_bytes()
    payload = {"plugin_id": "github", "name": "new", "configuration": {"headers": "invalid-secret"}}
    assert client.post("/api/capabilities/installations", json=payload, headers={"test-role": "user"}).status_code == 403
    invalid = client.post("/api/capabilities/installations", json=payload)
    assert invalid.status_code == 422
    assert "invalid-secret" not in invalid.text
    assert path.read_bytes() == before


def test_adapter_failure_is_isolated_and_lark_configured_is_not_verified(capability_client, monkeypatch):
    client, _ = capability_client
    monkeypatch.setattr(capabilities, "get_lark_integration_status", lambda *args: SimpleNamespace(installed=True, manifest_version="1", auth=SimpleNamespace(status="authenticated", verified=False)))
    assert client.get("/api/capabilities/installations/lark").json()["items"][0]["auth_status"] == "configured"
    assert client.get("/api/capabilities/installations/unknown").status_code == 422
    assert client.get("/api/capabilities/catalog").status_code == 200
    assert client.get("/api/capabilities/installations/mcp").status_code == 200


@pytest.mark.parametrize(
    "provider,credentials",
    [
        ("dingtalk", {"access_token": "robot-token", "sign_secret": "SEC-secret"}),
        ("wecom", {"webhook_key": "webhook-secret"}),
        ("hubspot", {"access_token": "private-token"}),
    ],
)
def test_business_install_uses_existing_mcp_lifecycle(capability_client, provider, credentials):
    client, path = capability_client
    payload = {"plugin_id": provider, "name": "team-" + provider, "configuration": credentials}
    assert client.post("/api/capabilities/installations", json=payload, headers={"test-role": "user"}).status_code == 403
    response = client.post("/api/capabilities/installations", json=payload)
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1
    installed = response.json()["items"][0]
    assert installed["adapter"] == "mcp" and installed["plugin_id"] == provider
    saved = json.loads(path.read_text())["mcpServers"][payload["name"]]
    assert saved["args"][-1] == provider
    assert set(saved["env"].values()) == set(credentials.values())
    for secret in credentials.values():
        assert secret not in response.text
        assert secret not in client.get("/api/mcp/config").text
    # Masked edits and toggles must continue to work without opening Python execution.
    masked = client.get("/api/mcp/config").json()["mcp_servers"][payload["name"]]
    masked["enabled"] = False
    assert client.put("/api/mcp/config/server", json={"server_name": payload["name"], "server": masked}).status_code == 200
    masked["enabled"] = True
    assert client.put("/api/mcp/config/server", json={"server_name": payload["name"], "server": masked}).status_code == 200
    assert client.delete("/api/mcp/config/servers/" + payload["name"]).status_code == 200
    assert set(json.loads(path.read_text())["mcpServers"]) == {"legacy"}


def test_business_config_rejects_arbitrary_execution_and_preserves_store(capability_client):
    from deerflow.capabilities.business import connection_config

    client, path = capability_client
    before = path.read_bytes()
    payload = {"plugin_id": "hubspot", "name": "bad", "configuration": {"access_token": "private-token", "command": "evil"}}
    assert client.post("/api/capabilities/installations", json=payload).status_code == 422
    definition = connection_config("hubspot", {"access_token": "private-token"})
    for change in ({"args": ["-c", "print(1)"]}, {"args": ["-I", "-m", "other.module", "hubspot"]}, {"env": {**definition["env"], "PYTHONPATH": "/tmp"}}):
        response = client.post("/api/mcp/config/servers", json={"mcp_servers": {"bad": {**definition, **change}}})
        assert response.status_code == 400
    assert path.read_bytes() == before


@pytest.mark.parametrize("configuration", [{"type": "http"}, {"type": "http", "url": ""}, {"type": "http", "url": "file:///tmp/a"}, {"type": "http", "url": "https://user:secret@example.test"}, {"type": "http", "url": "not-a-url"}])
def test_catalog_rejects_incomplete_or_unsafe_http_configuration(capability_client, configuration):
    client, path = capability_client
    before = path.read_bytes()
    response = client.post("/api/capabilities/installations", json={"plugin_id": "github", "name": "bad", "configuration": configuration})
    assert response.status_code == 422
    assert "secret" not in response.text
    assert path.read_bytes() == before


@pytest.mark.parametrize("route", ["/api/mcp/config/servers", "/api/mcp/config"])
@pytest.mark.parametrize("fallback", [False, True])
def test_mcp_writes_reject_colliding_installation_ids(capability_client, route, fallback):
    from deerflow.capabilities.runtime import installation_id

    client, path = capability_client
    raw = json.loads(path.read_text())
    identity = installation_id("legacy", {}) if fallback else "shared"
    if not fallback:
        raw["mcpServers"]["legacy"]["capability"] = {"id": identity}
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    method = client.post if route.endswith("/servers") else client.put
    candidate = {"other": {"type": "http", "url": "https://example.test", "capability": {"id": identity}}}
    if route == "/api/mcp/config":
        candidate["legacy"] = raw["mcpServers"]["legacy"]
    response = method(route, json={"mcp_servers": candidate})
    assert response.status_code == 400
    assert path.read_bytes() == before


def test_targeted_edit_enable_and_delete_handle_identity_collisions(capability_client):
    from deerflow.capabilities.runtime import installation_id

    client, path = capability_client
    raw = json.loads(path.read_text())
    raw["mcpServers"]["second"] = {"type": "http", "url": "https://example.test", "enabled": False}
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    response = client.put("/api/mcp/config/server", json={"server_name": "second", "server": {"type": "http", "url": "https://example.test", "capability": {"id": installation_id("legacy", {})}}})
    assert response.status_code == 400
    assert path.read_bytes() == before
    raw["mcpServers"]["second"]["capability"] = {"id": installation_id("legacy", {})}
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    response = client.patch("/api/mcp/config", json={"server_name": "second", "enabled": True})
    assert response.status_code == 400
    assert path.read_bytes() == before
    discovery = client.get("/api/capabilities/installations/mcp").json()["items"]
    assert len({item["id"] for item in discovery}) == 2
    assert all(item["selectable"] is False for item in discovery)
    assert client.delete("/api/mcp/config/servers/second").status_code == 200
    assert client.get("/api/capabilities/installations/mcp").json()["items"][0]["selectable"] is True

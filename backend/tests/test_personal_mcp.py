"""Personal MCP persistence, HTTP ownership and real MCP credential routing."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.tools import ToolException

from app.gateway.routers import personal_mcp
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.user_config import load_user_mcp_config, read_user_mcp_config, user_mcp_config_path
from deerflow.runtime.user_context import reset_current_user, set_current_user


@pytest.fixture
def personal_client(tmp_path, monkeypatch):
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: Paths(base_dir=tmp_path))
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        if name := request.headers.get("test-user"):
            request.state.user = SimpleNamespace(id=name, system_role=request.headers.get("test-role", "admin"))
            request.state.auth_source = "session"
        return await call_next(request)

    app.include_router(personal_mcp.router)
    with TestClient(app) as client:
        yield client


def create(client, user, *, name="github", token=None, role="admin"):
    return client.post(
        "/api/mcp/personal/config/servers",
        headers={"test-user": user, "test-role": role},
        json={"mcp_servers": {name: {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": token or f"Bearer {user}"}}}},
    )


def test_persistent_same_name_connections_are_owner_only(personal_client):
    client = personal_client
    assert client.get("/api/mcp/personal/config").status_code == 401
    for user in ("alice", "bob"):
        result = create(client, user)
        assert result.status_code == 200, result.text
        assert result.json()["mcp_servers"]["github"]["headers"]["Authorization"] == "***"
    assert read_user_mcp_config("alice")["mcpServers"]["github"]["headers"]["Authorization"] == "Bearer alice"
    assert read_user_mcp_config("bob")["mcpServers"]["github"]["headers"]["Authorization"] == "Bearer bob"
    assert user_mcp_config_path("alice").stat().st_mode & 0o777 == 0o600
    assert create(client, "alice").status_code == 409
    assert create(client, "alice", name="only-alice").status_code == 200
    assert client.delete("/api/mcp/personal/config/servers/only-alice", headers={"test-user": "bob"}).status_code == 404
    result = client.get("/api/mcp/personal/config", headers={"test-user": "bob"})
    assert "only-alice" not in result.text
    before = user_mcp_config_path("alice").read_bytes()
    assert client.patch("/api/mcp/personal/config", headers={"test-user": "bob"}, json={"server_name": "github", "enabled": False}).status_code == 200
    assert user_mcp_config_path("alice").read_bytes() == before
    # A fresh read from disk, not a request-local cache, retains each owner.
    assert len(load_user_mcp_config("alice").get_enabled_mcp_servers()) == 2
    assert not load_user_mcp_config("bob").get_enabled_mcp_servers()


def test_masked_edit_and_delete_do_not_touch_platform_or_peer(personal_client, tmp_path, monkeypatch):
    client = personal_client
    platform = tmp_path / "platform.json"
    platform.write_text(json.dumps({"mcpServers": {"github": {"type": "http", "url": "https://example.com/platform"}}}))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(platform))
    before = platform.read_bytes()
    create(client, "alice")
    create(client, "bob")
    result = client.put("/api/mcp/personal/config/server", headers={"test-user": "alice"}, json={"server_name": "github", "server": {"type": "http", "url": "https://example.com/updated", "headers": {"Authorization": "***"}}})
    assert result.status_code == 200, result.text
    assert read_user_mcp_config("alice")["mcpServers"]["github"]["headers"]["Authorization"] == "Bearer alice"
    assert client.delete("/api/mcp/personal/config/servers/github", headers={"test-user": "alice"}).status_code == 200
    assert not load_user_mcp_config("alice").mcp_servers
    assert read_user_mcp_config("bob")["mcpServers"]["github"]["headers"]["Authorization"] == "Bearer bob"
    assert platform.read_bytes() == before


def test_personal_values_do_not_resolve_platform_environment(personal_client, monkeypatch):
    monkeypatch.setenv("PLATFORM_ONLY_KEY", "platform-secret")
    assert create(personal_client, "alice", token="$PLATFORM_ONLY_KEY").status_code == 200
    config = load_user_mcp_config("alice")
    assert next(iter(config.mcp_servers.values())).headers["Authorization"] == "$PLATFORM_ONLY_KEY"


def test_catalog_listing_and_installation_respect_owner(personal_client, monkeypatch, tmp_path):
    from app.gateway.deps import get_config
    from app.gateway.routers import capabilities

    app = personal_client.app
    app.include_router(capabilities.router)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    platform = tmp_path / "deployment.json"
    platform.write_text(json.dumps({"mcpServers": {"shared": {"type": "http", "url": "https://example.com/platform"}}}))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(platform))
    monkeypatch.setattr("deerflow.community.url_safety.validate_public_http_url", lambda *a, **k: None)
    response = personal_client.post(
        "/api/capabilities/installations",
        headers={"test-user": "alice", "test-role": "user"},
        json={"plugin_id": "github", "name": "my-github", "scope": "user", "configuration": {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer alice"}}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["can_manage"] is True
    assert response.json()["items"][0]["scope"] == "user"
    for user, expected in (("alice", {"shared", "my-github"}), ("bob", {"shared"})):
        response = personal_client.get("/api/capabilities/installations/mcp?scope=all", headers={"test-user": user})
        assert response.status_code == 200, response.text
        assert {item["name"] for item in response.json()["items"]} == expected
        assert "Bearer alice" not in response.text


def test_tool_assembly_combines_platform_and_only_current_owner(personal_client, monkeypatch, tmp_path):
    from langchain_core.tools import StructuredTool

    from deerflow.tools.mcp_metadata import tag_mcp_tool
    from deerflow.tools.tools import get_available_tools

    path = tmp_path / "deployment.json"
    path.write_text(json.dumps({"mcpServers": {"shared": {"type": "http", "url": "https://example.com/mcp"}}}))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    shared = tag_mcp_tool(StructuredTool.from_function(lambda: "platform", name="shared_test", description="Shared tool"), server_name="shared")
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: [shared])

    async def discover(config, **kwargs):
        name = next(iter(config.mcp_servers))

        async def echo():
            return config.mcp_servers[name].headers["Authorization"]

        return [tag_mcp_tool(StructuredTool.from_function(coroutine=echo, name=name + "_test", description="Personal tool"), server_name=name)]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", discover)
    config = SimpleNamespace(tools=[], models=[], get_model_config=lambda _: None)
    for user in ("alice", "bob"):
        create(personal_client, user)
        identity = set_current_user(SimpleNamespace(id=user))
        try:
            tools = get_available_tools(app_config=config)
            assert shared in tools
            personal = [tool for tool in tools if tool.name.startswith("personal_")]
            assert len(personal) == 1
            assert personal[0].invoke({}) == f"Bearer {user}"
            # Selecting the peer's installation cannot add that peer's tools.
            peer = "bob" if user == "alice" else "alice"
            peer_id = next(iter(read_user_mcp_config(peer)["mcpServers"].values()), {}).get("capability", {}).get("id", "not-owned")
            assert not any(tool.name.startswith("personal_") for tool in get_available_tools(app_config=config, mcp_plugins=[peer_id]))
        finally:
            reset_current_user(identity)


def test_deployment_name_collision_does_not_publish_a_personal_tool(personal_client, monkeypatch, tmp_path):
    from langchain_core.tools import StructuredTool

    from deerflow.tools.mcp_metadata import tag_mcp_tool
    from deerflow.tools.tools import get_available_tools

    assert create(personal_client, "alice").status_code == 200
    name = next(iter(load_user_mcp_config("alice").mcp_servers))
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps({"mcpServers": {name: {"type": "http", "url": "https://example.com/platform"}}}))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    platform = tag_mcp_tool(StructuredTool.from_function(lambda: "platform", name=name + "_test", description="Shared tool"), server_name=name)
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: [platform])

    async def discover(config, **kwargs):
        async def personal():
            return "personal"

        return [tag_mcp_tool(StructuredTool.from_function(coroutine=personal, name=name + "_test", description="Personal tool"), server_name=name)]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", discover)
    config = SimpleNamespace(tools=[], models=[], get_model_config=lambda _: None)
    identity = set_current_user(SimpleNamespace(id="alice"))
    try:
        tools = get_available_tools(app_config=config)
        assert [tool for tool in tools if tool.name == name + "_test"] == [platform]
        personal_id = read_user_mcp_config("alice")["mcpServers"]["github"]["capability"]["id"]
        selected = get_available_tools(app_config=config, mcp_plugins=[personal_id])
        assert not any(tool.name == name + "_test" for tool in selected)
    finally:
        reset_current_user(identity)


def test_untrusted_users_cannot_launch_packages_or_connect_to_private_hosts(personal_client, monkeypatch):
    client = personal_client
    response = client.post("/api/mcp/personal/config/servers", headers={"test-user": "alice", "test-role": "user"}, json={"mcp_servers": {"shell": {"type": "stdio", "command": "npx", "args": ["untrusted-package"]}}})
    assert response.status_code == 403
    response = client.post("/api/mcp/personal/config/servers", headers={"test-user": "alice", "test-role": "user"}, json={"mcp_servers": {"private": {"type": "http", "url": "http://127.0.0.1/mcp", "personal_public_network": False}}})
    assert response.status_code == 400
    monkeypatch.setattr("deerflow.community.url_safety.validate_public_http_url", lambda *a, **k: None)
    assert create(client, "alice", role="user").status_code == 200
    assert read_user_mcp_config("alice")["mcpServers"]["github"]["personal_public_network"] is True


@pytest.mark.asyncio
async def test_personal_network_rechecks_destination_before_each_request(monkeypatch):
    from deerflow.mcp import personal_network

    client_class = httpx.AsyncClient
    received = []
    blocked = False

    def transport(request):
        received.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    monkeypatch.setattr(personal_network.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(transport), **kwargs))
    monkeypatch.setattr(personal_network, "validate_public_http_url", lambda *a, **k: "private address" if blocked else None)
    async with personal_network.personal_httpx_client_factory() as client:
        assert (await client.get("https://example.com/mcp")).status_code == 302
        assert received == ["https://example.com/mcp"]
        blocked = True
        with pytest.raises(ValueError, match="public HTTP"):
            await client.get("https://example.com/mcp")
        assert len(received) == 1


@pytest.mark.asyncio
async def test_real_mcp_calls_keep_credentials_separate_and_reject_stale_tools(personal_client, monkeypatch):
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    from deerflow.mcp import client as mcp_client
    from deerflow.mcp.user_tools import _load

    server = FastMCP("identity", stateless_http=True, json_response=True, transport_security=TransportSecuritySettings(allowed_hosts=["example.com"]))
    received = []

    @server.tool()
    async def whoami(ctx: Context) -> str:
        credential = ctx.request_context.request.headers.get("authorization")
        received.append(credential)
        return credential

    app = server.streamable_http_app()
    build = mcp_client.build_server_params

    def params(name, config):
        result = build(name, config)
        result["httpx_client_factory"] = lambda headers=None, timeout=None, auth=None: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=headers, timeout=timeout or 30, auth=auth)
        return result

    monkeypatch.setattr(mcp_client, "build_server_params", params)
    for user in ("alice", "bob"):
        assert create(personal_client, user).status_code == 200

    async def run(user):
        identity = set_current_user(SimpleNamespace(id=user))
        try:
            tools = await _load(user, load_user_mcp_config(user))
            assert len(tools) == 1
            await tools[0].ainvoke({})
            return tools[0]
        finally:
            reset_current_user(identity)

    async with app.router.lifespan_context(app):
        alice_tool, bob_tool = await asyncio.gather(run("alice"), run("bob"))
        assert sorted(received) == ["Bearer alice", "Bearer bob"]
        assert alice_tool.name != bob_tool.name
        identity = set_current_user(SimpleNamespace(id="bob"))
        try:
            with pytest.raises(ToolException, match="another user"):
                await alice_tool.ainvoke({})
            assert personal_client.patch("/api/mcp/personal/config", headers={"test-user": "bob"}, json={"server_name": "github", "enabled": False}).status_code == 200
            with pytest.raises(ToolException, match="changed, disabled or removed"):
                await bob_tool.ainvoke({})
            assert len(received) == 2
        finally:
            reset_current_user(identity)


@pytest.mark.asyncio
async def test_background_calls_resolve_only_persisted_task_owner(personal_client, monkeypatch):
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    create(personal_client, "alice")
    name = next(iter(load_user_mcp_config("alice").mcp_servers))
    received = []

    async def invoke(self, **kwargs):
        received.append(self._extensions_config.mcp_servers[kwargs["server_name"]].headers["Authorization"])

    monkeypatch.setattr(McpTaskToolCaller, "_call_configured_tool", invoke)
    caller = McpTaskToolCaller(ExtensionsConfig())
    await caller.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")
    with pytest.raises(LookupError, match="Personal MCP"):
        await caller.call_tool(server_name=name, tool_name="status", arguments={}, user_id="bob", thread_id="thread", connection_scope="personal")
    assert received == ["Bearer alice"]

    # The same deployment name must not steal an existing personal task after
    # the Gateway restarts with that deployment entry in its startup snapshot.
    deployment = McpTaskToolCaller(ExtensionsConfig.model_validate({"mcpServers": {name: {"type": "http", "url": "https://example.com/platform", "headers": {"Authorization": "platform"}}}}))
    await deployment.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")
    await deployment.call_tool(server_name=name, tool_name="status", arguments={}, user_id="bob", thread_id="thread")
    assert received == ["Bearer alice", "Bearer alice", "platform"]
    assert personal_client.patch("/api/mcp/personal/config", headers={"test-user": "alice"}, json={"server_name": "github", "enabled": False}).status_code == 200
    with pytest.raises(LookupError, match="Personal MCP"):
        await deployment.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")

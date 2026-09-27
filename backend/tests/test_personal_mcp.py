"""Personal MCP persistence, HTTP ownership and real MCP credential routing."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.parametrize("contents", ["{", "[]"])
def test_corrupt_personal_config_returns_client_errors_without_overwriting_it(personal_client, contents):
    path = user_mcp_config_path("alice")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    headers = {"test-user": "alice"}
    requests = [
        ("GET", "/api/mcp/personal/config", None),
        ("POST", "/api/mcp/personal/config/servers", {"mcp_servers": {"new": {"type": "http", "url": "https://example.com/mcp"}}}),
        ("PUT", "/api/mcp/personal/config/server", {"server_name": "new", "server": {"type": "http", "url": "https://example.com/mcp"}}),
        ("PATCH", "/api/mcp/personal/config", {"server_name": "new", "enabled": False}),
        ("DELETE", "/api/mcp/personal/config/servers/new", None),
    ]
    for method, url, body in requests:
        response = personal_client.request(method, url, headers=headers, json=body)
        assert response.status_code == 400, (method, response.text)
        assert "Extensions configuration" in response.json()["detail"]
        assert path.read_text() == contents
    assert personal_client.get("/api/mcp/personal/config", headers={"test-user": "bob"}).status_code == 200


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
async def test_personal_tool_guard_reuses_validation_and_rejects_file_replacement(personal_client, monkeypatch):
    import os

    from langchain_core.tools import StructuredTool

    import deerflow.mcp.user_config as user_config
    from deerflow.config.extensions_config import atomic_write_extensions_config
    from deerflow.mcp.user_tools import _guard

    assert create(personal_client, "alice").status_code == 200
    old_name = next(iter(load_user_mcp_config("alice").mcp_servers))
    load = user_config.load_user_mcp_config
    reads = 0

    def counted_load(user_id):
        nonlocal reads
        reads += 1
        return load(user_id)

    monkeypatch.setattr(user_config, "load_user_mcp_config", counted_load)
    calls = []

    async def invoke():
        calls.append(True)
        return "ok"

    tool = _guard(StructuredTool.from_function(coroutine=invoke, name="personal_test", description="Personal test"), "alice", old_name)
    identity = set_current_user(SimpleNamespace(id="alice"))
    try:
        assert await tool.ainvoke({}) == "ok"
        assert await tool.ainvoke({}) == "ok"
        assert reads == 1

        path = user_mcp_config_path("alice")
        before = path.stat()
        raw = read_user_mcp_config("alice")
        raw["mcpServers"]["github"]["headers"]["Authorization"] = "Bearer ALICE"
        atomic_write_extensions_config(path, raw)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
        assert after.st_ino != before.st_ino
        with pytest.raises(ToolException, match="changed, disabled or removed"):
            await tool.ainvoke({})
        assert reads == 2
        assert len(calls) == 2
    finally:
        reset_current_user(identity)


@pytest.mark.asyncio
async def test_background_calls_resolve_only_persisted_task_owner(personal_client, monkeypatch):
    import deerflow.mcp.user_config as user_config
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    create(personal_client, "alice")
    name = next(iter(load_user_mcp_config("alice").mcp_servers))
    received = []
    loaded = []
    load = user_config.load_user_mcp_config

    def counted_load(user_id):
        loaded.append(user_id)
        return load(user_id)

    monkeypatch.setattr(user_config, "load_user_mcp_config", counted_load)

    async def invoke(self, **kwargs):
        received.append(self._extensions_config.mcp_servers[kwargs["server_name"]].headers["Authorization"])

    monkeypatch.setattr(McpTaskToolCaller, "_call_configured_tool", invoke)
    caller = McpTaskToolCaller(ExtensionsConfig())
    await caller.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")
    first_caller = caller._personal_callers["alice"][1]
    await caller.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")
    assert caller._personal_callers["alice"][1] is first_caller
    assert loaded == ["alice"]
    with pytest.raises(LookupError, match="Personal MCP"):
        await caller.call_tool(server_name=name, tool_name="status", arguments={}, user_id="bob", thread_id="thread", connection_scope="personal")
    assert received == ["Bearer alice", "Bearer alice"]

    # The same deployment name must not steal an existing personal task after
    # the Gateway restarts with that deployment entry in its startup snapshot.
    deployment = McpTaskToolCaller(ExtensionsConfig.model_validate({"mcpServers": {name: {"type": "http", "url": "https://example.com/platform", "headers": {"Authorization": "platform"}}}}))
    await deployment.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")
    await deployment.call_tool(server_name=name, tool_name="status", arguments={}, user_id="bob", thread_id="thread")
    assert received == ["Bearer alice", "Bearer alice", "Bearer alice", "platform"]
    assert personal_client.patch("/api/mcp/personal/config", headers={"test-user": "alice"}, json={"server_name": "github", "enabled": False}).status_code == 200
    with pytest.raises(LookupError, match="Personal MCP"):
        await deployment.call_tool(server_name=name, tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal")


@pytest.mark.asyncio
async def test_background_caller_rebuilds_after_personal_credential_edit(personal_client, monkeypatch):
    from deerflow.config.extensions_config import atomic_write_extensions_config
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    assert create(personal_client, "alice").status_code == 200
    old_name = next(iter(load_user_mcp_config("alice").mcp_servers))

    async def credential(self, **kwargs):
        return self._extensions_config.mcp_servers[kwargs["server_name"]].headers["Authorization"]

    monkeypatch.setattr(McpTaskToolCaller, "_call_configured_tool", credential)
    caller = McpTaskToolCaller(ExtensionsConfig())
    request = {"tool_name": "status", "arguments": {}, "user_id": "alice", "thread_id": "thread", "connection_scope": "personal"}
    assert await caller.call_tool(server_name=old_name, **request) == "Bearer alice"
    previous = caller._personal_callers["alice"][1]

    path = user_mcp_config_path("alice")
    raw = read_user_mcp_config("alice")
    raw["mcpServers"]["github"]["headers"]["Authorization"] = "Bearer ALICE"
    atomic_write_extensions_config(path, raw)
    with pytest.raises(LookupError, match="Personal MCP"):
        await caller.call_tool(server_name=old_name, **request)
    new_name = next(iter(load_user_mcp_config("alice").mcp_servers))
    assert await caller.call_tool(server_name=new_name, **request) == "Bearer ALICE"
    assert caller._personal_callers["alice"][1] is not previous
    path.unlink()
    with pytest.raises(LookupError, match="Personal MCP"):
        await caller.call_tool(server_name=new_name, **request)


@pytest.mark.asyncio
async def test_background_caller_keeps_only_recent_owners(personal_client, monkeypatch):
    import deerflow.mcp.task_tool_caller as task_tool_caller

    monkeypatch.setattr(task_tool_caller, "_MAX_PERSONAL_CALLERS", 2)

    async def credential(self, **kwargs):
        return self._extensions_config.mcp_servers[kwargs["server_name"]].headers["Authorization"]

    monkeypatch.setattr(task_tool_caller.McpTaskToolCaller, "_call_configured_tool", credential)
    caller = task_tool_caller.McpTaskToolCaller(ExtensionsConfig())
    names = {}
    for user_id in ("alice", "bob", "carol"):
        assert create(personal_client, user_id).status_code == 200
        names[user_id] = next(iter(load_user_mcp_config(user_id).mcp_servers))
        assert await caller.call_tool(server_name=names[user_id], tool_name="status", arguments={}, user_id=user_id, thread_id="thread", connection_scope="personal") == f"Bearer {user_id}"
    assert list(caller._personal_callers) == ["bob", "carol"]
    assert await caller.call_tool(server_name=names["alice"], tool_name="status", arguments={}, user_id="alice", thread_id="thread", connection_scope="personal") == "Bearer alice"
    assert list(caller._personal_callers) == ["carol", "alice"]


@pytest.mark.asyncio
async def test_gateway_registers_driver_for_personal_only_task_toolsets(personal_client):
    from langchain_core.tools import StructuredTool

    from app.gateway.app import lifespan
    from deerflow.config.extensions_config import atomic_write_extensions_config
    from deerflow.config.mcp_tasks_config import McpTasksConfig
    from deerflow.mcp.tasks import ORDINARY_MCP_TASK_DRIVER
    from deerflow.mcp.tools import get_mcp_tools

    path = user_mcp_config_path("alice")
    atomic_write_extensions_config(
        path,
        {"mcpServers": {"reports": {"type": "http", "url": "https://example.com/mcp", "task_toolsets": [{"name": "reports", "submit_tool": "submit_report", "status_tool": "status_report", "cancel_tool": "cancel_report"}]}}},
    )
    personal = load_user_mcp_config("alice")
    server_name = next(iter(personal.mcp_servers))
    deployment = ExtensionsConfig()
    startup = SimpleNamespace(log_level="INFO", memory=SimpleNamespace(enabled=False, token_counting="char", shutdown_flush_timeout_seconds=5.0), mcp_tasks=McpTasksConfig(enabled=True))
    app = FastAPI()

    @asynccontextmanager
    async def runtime(gateway, _config):
        gateway.state.mcp_task_repo = object()
        yield

    class FakeClient:
        def __init__(self, _servers, *, tool_interceptors, **_kwargs):
            self.tool_interceptors = tool_interceptors
            self.callbacks = None

        async def get_tools(self, *, server_name):
            async def call(topic: str) -> str:
                return topic

            return [StructuredTool.from_function(coroutine=call, name=f"{server_name}_{name}", description=name) for name in ("submit_report", "status_report", "cancel_report")]

    channel = MagicMock()
    channel.get_status.return_value = {}
    with (
        patch("app.gateway.app.get_app_config", return_value=startup),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", AsyncMock(return_value=channel)),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=deployment),
        patch("app.mcp_tasks.McpTaskService.start", AsyncMock()),
        patch("app.mcp_tasks.McpTaskService.stop", AsyncMock()),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient),
    ):
        async with lifespan(app):
            assert not deployment.mcp_servers
            assert app.state.mcp_task_service.drivers.get(ORDINARY_MCP_TASK_DRIVER) is not None
            tools = await get_mcp_tools(personal, personal_user_id="alice")
            assert [tool.name for tool in tools] == [f"{server_name}_submit_report"]
            app.state.mcp_task_service.submit = AsyncMock(return_value={"id": "local-1", "status": "submitted"})
            identity = set_current_user(SimpleNamespace(id="alice"))
            try:
                result = await tools[0].coroutine(
                    runtime=SimpleNamespace(context={"thread_id": "thread-1", "thread_incarnation": "incarnation-1", "run_id": "run-1"}, config={}, tool_call_id="call-1"),
                    topic="MCP",
                )
            finally:
                reset_current_user(identity)
            assert result["task_id"] == "local-1"
            submitted = app.state.mcp_task_service.submit.await_args.kwargs
            assert submitted["driver_name"] == ORDINARY_MCP_TASK_DRIVER
            assert submitted["request"].driver_data["connection_scope"] == "personal"

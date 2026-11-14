"""Administrator-granted MCP identities stay owner-bound and revocable."""

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langgraph.runtime import Runtime
from pydantic import ValidationError
from support.mcp_agent_auth import agent_auth_env as agent_auth_env
from support.mcp_agent_auth import agent_mcp_transport as agent_mcp_transport

from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig, pop_current_app_config, push_current_app_config, reset_app_config, set_app_config
from deerflow.config.extensions_config import McpServerConfig


@pytest.mark.parametrize(
    "options",
    [
        {"type": "stdio"},
        {"type": "sse"},
        {"user_auth": {"users": {"alice": "secret"}}},
        {"headers_from_context": {"headers": {"aUtHoRiZaTiOn": "token"}}},
    ],
)
def test_agent_auth_rejects_competing_sources_and_unsupported_transports(options):
    with pytest.raises(ValidationError):
        McpServerConfig.model_validate({"type": "http", "url": "https://mcp.example", "agent_auth": True, **options})


@pytest.fixture
def real_subagents(monkeypatch):
    # conftest stubs this module to break collection-time import cycles.
    # Restore production execution, including its persistent loop and registry.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_mcp_auth_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    for name in ("deerflow.tools.builtins.task_tool", "deerflow.subagents.batch_service"):
        target = importlib.import_module(name)
        for attribute in ("SubagentExecutor", "SubagentStatus", "cleanup_background_task", "force_cleanup_background_task", "get_background_task_result", "request_cancel_background_task", "run_on_isolated_subagent_loop"):
            monkeypatch.setattr(target, attribute, getattr(module, attribute))
    yield module
    module._shutdown_isolated_subagent_loop()


def test_admission_pins_the_approved_definition(agent_auth_env):
    from deerflow.mcp.agent_auth import capture_agent_authority

    env = agent_auth_env
    authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
    assert authority is not None
    (env.directory / "SOUL.md").write_text("Changed after admission.", encoding="utf-8")
    assert authority.soul == env.soul
    assert authority.agent_config().model_dump() == env.agent.model_dump()
    env.agent.tool_groups.append("unreviewed-group")
    assert authority.agent_config().tool_groups == ["mcp"]
    with pytest.raises(ToolException):
        capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)


def test_owners_and_agent_names_both_bound_admission(agent_auth_env):
    from deerflow.mcp.agent_auth import capture_agent_authority

    env = agent_auth_env
    assert capture_agent_authority(env.config, user_id="bob", agent_config=env.agent) is None
    assert capture_agent_authority(env.config, user_id="alice", agent_config=AgentConfig(name="other")) is None
    assert capture_agent_authority(env.config, user_id="alice", agent_config=None) is None


@pytest.mark.asyncio
async def test_agent_auth_uses_oauth_and_rechecks_revocation_with_a_cached_token(agent_auth_env, monkeypatch):
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, build_agent_auth_interceptor, capture_agent_authority

    env = agent_auth_env
    authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
    runtime = Runtime(context={"user_id": "alice", AGENT_AUTH_CONTEXT_KEY: authority})
    interceptor = build_agent_auth_interceptor(env.config.extensions)
    token_requests, calls = [], []

    def token_response(request):
        token_requests.append(request)
        return httpx.Response(200, json={"access_token": "agent-access-token", "expires_in": 3600})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(token_response), **kwargs))

    async def handler(request):
        calls.append(request)
        return "ok"

    request = MCPToolCallRequest(name="search", args={}, server_name="tickets", runtime=runtime)
    assert await interceptor(request, handler) == "ok"
    assert await interceptor(request, handler) == "ok"
    assert len(token_requests) == 1
    assert b"client_id=research-client" in token_requests[0].content
    assert {k.lower(): v for k, v in calls[0].headers.items()}["authorization"] == "Bearer agent-access-token"
    revoked = env.config.model_copy(deep=True)
    revoked.mcp_agent_auth["research-tickets"].enabled = False
    set_app_config(revoked)
    push_current_app_config(env.config)
    try:
        with pytest.raises(ToolException):
            await interceptor(request, handler)
    finally:
        pop_current_app_config()
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("forged", [None, {"binding_id": "research-tickets"}, {"agent_name": "research-bot", "user_id": "alice"}])
async def test_context_data_never_grants_an_agent_credential(agent_auth_env, forged):
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, build_agent_auth_interceptor

    interceptor = build_agent_auth_interceptor(agent_auth_env.config.extensions)

    async def handler(request):
        pytest.fail("An unauthorized request reached the MCP transport")

    runtime = Runtime(context={"user_id": "alice", "agent_name": "research-bot", AGENT_AUTH_CONTEXT_KEY: forged})
    with pytest.raises(ToolException):
        await interceptor(MCPToolCallRequest(name="search", args={}, server_name="tickets", runtime=runtime), handler)


@pytest.mark.parametrize(
    "updates",
    [
        {"owners": ["*"]},
        {"owners": "alice"},
        {"owners": ["alice", "alice"]},
        {"owners": [" alice"]},
        {"agent": "../other"},
        {"definition_digests": []},
        {"definition_digests": ["unreviewed"]},
        {"oauth": {"token_url": "https://idp.example/token", "grant_type": "refresh_token", "refresh_token": "not-supported"}},
        {"oauth": {"token_url": "https://idp.example/token", "client_id": "account"}},
    ],
)
def test_invalid_operator_grants_fail_configuration(agent_auth_env, updates):
    from deerflow.config.mcp_agent_auth_config import McpAgentCredentialBinding

    binding = agent_auth_env.config.mcp_agent_auth["research-tickets"].model_dump()
    with pytest.raises(ValidationError):
        McpAgentCredentialBinding.model_validate({**binding, **updates})


def test_ambiguous_bindings_fail_configuration(agent_auth_env):
    data = agent_auth_env.config.model_dump()
    data["mcp_agent_auth"]["second-grant"] = data["mcp_agent_auth"]["research-tickets"]
    with pytest.raises(ValidationError, match="overlap"):
        AppConfig.model_validate(data)


def test_personal_file_cannot_claim_deployment_credentials(agent_auth_env):
    from deerflow.mcp.user_config import load_user_mcp_config, user_mcp_config_path

    path = user_mcp_config_path("alice")
    path.parent.mkdir(parents=True)
    path.write_text(agent_auth_env.config.extensions.model_dump_json(by_alias=True), encoding="utf-8")
    with pytest.raises(ValueError, match="deployment"):
        load_user_mcp_config("alice")


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted", [False, True])
async def test_existing_tool_rejects_newly_enabled_protection(agent_auth_env, agent_mcp_transport, admitted):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.config.extensions_config import McpUserScopedAuthConfig
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, capture_agent_authority
    from deerflow.mcp.tools import get_mcp_tools

    old = agent_auth_env.config.model_copy(deep=True)
    old.extensions.mcp_servers["tickets"].agent_auth = False
    old.extensions.mcp_servers["tickets"].user_auth = McpUserScopedAuthConfig(users={"alice": "Bearer research-client-old-user"})
    set_app_config(old)
    graph = StateGraph(MessagesState, context_schema=dict)
    graph.add_node("tools", ToolNode(await get_mcp_tools(old.extensions), handle_tool_errors=False))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    compiled = graph.compile()
    value = {"messages": [AIMessage(content="", tool_calls=[{"name": "tickets_search", "args": {}, "id": "search-1", "type": "tool_call"}])]}
    context = {"user_id": "alice"}
    await compiled.ainvoke(value, context=context)
    assert agent_mcp_transport.calls == [("search", "Bearer research-client-old-user")]
    set_app_config(agent_auth_env.config)
    if admitted:
        context[AGENT_AUTH_CONTEXT_KEY] = capture_agent_authority(agent_auth_env.config, user_id="alice", agent_config=agent_auth_env.agent)
    push_current_app_config(old)
    try:
        with pytest.raises(ToolException):
            await compiled.ainvoke(value, context=context)
    finally:
        pop_current_app_config()
    assert len(agent_mcp_transport.calls) == 1
    assert agent_mcp_transport.token_clients == []


@pytest.mark.asyncio
@pytest.mark.parametrize("live_destination_changed", [False, True])
async def test_task_reference_rejects_changed_live_or_captured_destination(agent_auth_env, agent_mcp_transport, live_destination_changed):
    from deerflow.mcp.agent_auth import capture_agent_authority
    from deerflow.mcp.task_tool_caller import McpTaskConnectionUnavailableError, McpTaskToolCaller

    env = agent_auth_env
    reference = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent).references[0].model_dump(mode="json")
    replacement = env.config.model_copy(deep=True)
    replacement.extensions.mcp_servers["tickets"].url = "https://replacement.example/mcp"
    if live_destination_changed:
        set_app_config(replacement)
    caller = McpTaskToolCaller(replacement.extensions)
    with pytest.raises(McpTaskConnectionUnavailableError):
        await caller.call_tool(server_name="tickets", tool_name="poll_job", arguments={}, user_id="alice", thread_id="thread-1", agent_auth=reference)
    assert agent_mcp_transport.calls == []
    assert agent_mcp_transport.token_clients == []


@pytest.mark.asyncio
async def test_task_reference_without_destination_fails_closed(agent_auth_env, agent_mcp_transport):
    from deerflow.mcp.agent_auth import capture_agent_authority
    from deerflow.mcp.task_tool_caller import McpTaskConnectionUnavailableError, McpTaskToolCaller

    env = agent_auth_env
    reference = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent).references[0].model_dump(mode="json")
    del reference["destination_digest"]
    with pytest.raises(McpTaskConnectionUnavailableError):
        await McpTaskToolCaller(env.config.extensions).call_tool(server_name="tickets", tool_name="poll_job", arguments={}, user_id="alice", thread_id="thread-1", agent_auth=reference)
    assert agent_mcp_transport.calls == []
    assert agent_mcp_transport.token_clients == []


@pytest.mark.asyncio
async def test_concurrent_owners_never_share_tokens_and_secret_rotation_keeps_identity(agent_auth_env, agent_mcp_transport, caplog):
    from deerflow.mcp.agent_auth import capture_agent_authority
    from deerflow.mcp.task_tool_caller import McpTaskConnectionUnavailableError, McpTaskToolCaller

    env = agent_auth_env
    bob_dir = env.directory.parents[2] / "bob" / "agents" / env.agent.name
    bob_dir.mkdir(parents=True)
    (bob_dir / "SOUL.md").write_text(env.soul, encoding="utf-8")
    binding = env.config.mcp_agent_auth["research-tickets"].model_copy(deep=True)
    binding.owners = ["bob"]
    binding.oauth.client_id = "research-client-bob"
    env.config.mcp_agent_auth["bob-tickets"] = binding
    references = {user: capture_agent_authority(env.config, user_id=user, agent_config=env.agent).references[0].model_dump(mode="json") for user in ("alice", "bob")}
    caller = McpTaskToolCaller(env.config.extensions)

    async def call(user):
        return await caller.call_tool(server_name="tickets", tool_name="search", arguments={}, user_id=user, thread_id="thread-" + user, agent_auth=references[user])

    with caplog.at_level("INFO", logger="deerflow.mcp.agent_auth"):
        await asyncio.gather(call("alice"), call("bob"), call("alice"), call("bob"))
    assert sorted(agent_mcp_transport.token_clients) == ["research-client", "research-client-bob"]
    assert sorted(agent_mcp_transport.calls) == sorted([("search", "Bearer research-client-token")] * 2 + [("search", "Bearer research-client-bob-token")] * 2)
    assert "server=tickets agent=research-bot owner=alice binding=research-tickets" in caplog.text
    assert "private-client-secret" not in caplog.text and "research-client-token" not in caplog.text
    with pytest.raises(McpTaskConnectionUnavailableError):
        await caller.call_tool(server_name="tickets", tool_name="search", arguments={}, user_id="bob", thread_id="thread-bob", agent_auth=references["alice"])
    assert len(agent_mcp_transport.calls) == 4
    env.config.mcp_agent_auth["research-tickets"].oauth.client_secret = "rotated-secret"
    await call("alice")
    assert agent_mcp_transport.token_forms[-1]["client_secret"] == ["rotated-secret"]
    # Retargeting the binding to a different client must not impersonate it
    # for tasks admitted under the original account.
    env.config.mcp_agent_auth["research-tickets"].oauth.client_id = "replacement-account"
    with pytest.raises(McpTaskConnectionUnavailableError):
        await call("alice")
    assert len(agent_mcp_transport.calls) == 5
    assert len(agent_mcp_transport.token_clients) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_during_fetch", [False, True])
async def test_token_failure_and_concurrent_revocation_never_fall_back(agent_auth_env, monkeypatch, revoke_during_fetch):
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, build_agent_auth_interceptor, capture_agent_authority

    env = agent_auth_env
    authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
    started, release = asyncio.Event(), asyncio.Event()

    async def token_endpoint(request):
        started.set()
        await release.wait()
        if revoke_during_fetch:
            return httpx.Response(200, json={"access_token": "never-send-this-token", "expires_in": 3600})
        return httpx.Response(401, json={"error": "private-client-secret"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(token_endpoint), **kwargs))
    interceptor = build_agent_auth_interceptor(env.config.extensions)

    async def handler(request):
        pytest.fail("Credential failure must not fall back to discovery auth")

    request = MCPToolCallRequest(name="search", args={}, server_name="tickets", runtime=Runtime(context={"user_id": "alice", AGENT_AUTH_CONTEXT_KEY: authority}))
    pending = asyncio.create_task(interceptor(request, handler))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        if revoke_during_fetch:
            env.config.mcp_agent_auth["research-tickets"].enabled = False
        release.set()
        with pytest.raises(ToolException) as caught:
            await pending
        assert "private-client-secret" not in str(caught.value)
        assert "never-send-this-token" not in str(caught.value)
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["poll", "cancel"])
@pytest.mark.parametrize("revoked", [False, True])
async def test_durable_task_keeps_agent_identity_after_restart_and_definition_rollout(agent_auth_env, agent_mcp_transport, tmp_path, monkeypatch, operation, revoked):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from app.mcp_tasks import McpTaskService
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.config.extensions_config import McpTaskToolsetConfig, reset_extensions_config
    from deerflow.mcp import agent_auth
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, agent_definition_digest, capture_agent_authority
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller
    from deerflow.mcp.tasks import ORDINARY_MCP_TASK_DRIVER, McpTaskDriverRegistry, OrdinaryMcpTaskDriver
    from deerflow.mcp.tasks.runtime import set_mcp_task_config_snapshot, set_mcp_task_submitter, validate_mcp_task_config_snapshot
    from deerflow.mcp.tools import get_mcp_tools
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.mcp_tasks import McpTaskRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    env = agent_auth_env
    server = env.config.extensions.mcp_servers["tickets"]
    server.task_toolsets = [McpTaskToolsetConfig(name="job", submit_tool="submit_job", status_tool="poll_job", cancel_tool="cancel_job")]
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(env.config.extensions.model_dump_json(by_alias=True), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    reset_extensions_config()
    startup = env.config.extensions
    set_mcp_task_config_snapshot(startup)
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "database")))
    sf = get_session_factory()
    repo = McpTaskRepository(sf)
    async with sf() as session:
        session.add(ThreadMetaRow(thread_id="t-agent", incarnation="inc-1", user_id="alice", metadata_json={}))
        await session.commit()

    def service():
        drivers = McpTaskDriverRegistry()
        drivers.register(ORDINARY_MCP_TASK_DRIVER, OrdinaryMcpTaskDriver(McpTaskToolCaller(startup)))
        return McpTaskService(repository=repo, drivers=drivers, poll_interval_seconds=1, lease_seconds=120, max_concurrent_polls=1)

    try:
        first = service()
        set_mcp_task_submitter(first)
        tools = await get_mcp_tools()
        graph = StateGraph(MessagesState, context_schema=dict)
        graph.add_node("tools", ToolNode(tools, handle_tool_errors=False))
        graph.add_edge(START, "tools")
        graph.add_edge("tools", END)
        authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
        result = await graph.compile().ainvoke(
            {"messages": [AIMessage(content="", tool_calls=[{"name": "tickets_submit_job", "args": {}, "id": "submit-1", "type": "tool_call"}])]},
            context={"user_id": "alice", "thread_id": "t-agent", "thread_incarnation": "inc-1", AGENT_AUTH_CONTEXT_KEY: authority},
        )
        task_id = json.loads(result["messages"][-1].content)["task_id"]
        saved = await repo.get(task_id, user_id="alice", thread_id="t-agent", thread_incarnation="inc-1")
        reference = saved["driver_data"]["agent_auth"]
        assert reference["definition_digest"] == authority.references[0].definition_digest
        assert "private-client-secret" not in json.dumps(saved, default=str)
        assert "research-client-token" not in json.dumps(saved, default=str)

        updated = env.config.model_copy(deep=True)
        updated.mcp_agent_auth["research-tickets"].definition_digests = [agent_definition_digest(env.agent, "New reviewed definition.")]
        if revoked:
            updated.mcp_agent_auth["research-tickets"].owners = []
        set_app_config(updated)
        validate_mcp_task_config_snapshot(updated.extensions)
        agent_auth._token_managers.clear()
        restarted = service()
        if operation == "cancel":
            await restarted.cancel_task(task_id=task_id, thread_id="t-agent", user_id="alice", thread_incarnation="inc-1")
        await restarted.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
        saved = await repo.get(task_id, user_id="alice", thread_id="t-agent", thread_incarnation="inc-1")
        if revoked:
            assert saved["status"] == "failed"
            assert "revoked" in saved["error"]
            assert agent_mcp_transport.calls == [("submit_job", "Bearer research-client-token")]
            assert agent_mcp_transport.token_clients == ["research-client"]
        else:
            assert agent_mcp_transport.calls == [("submit_job", "Bearer research-client-token"), (operation + "_job", "Bearer research-client-token")]
            assert saved["status"] == ("cancelled" if operation == "cancel" else "working")
            assert agent_mcp_transport.token_clients == ["research-client", "research-client"]
    finally:
        set_mcp_task_submitter(None)
        set_mcp_task_config_snapshot(None)
        reset_extensions_config()
        await close_engine()


@pytest.mark.no_auto_user
def test_gateway_admits_owner_and_assembles_the_verified_snapshot(agent_auth_env, agent_mcp_transport, tmp_path, monkeypatch):
    from _agent_e2e_helpers import FakeToolCallingModel
    from langchain_core.messages import AIMessage
    from starlette.testclient import TestClient

    from app.gateway.app import create_app
    from deerflow.config.agents_config import load_agent_config
    from deerflow.config.extensions_config import reset_extensions_config
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, agent_definition_digest

    env = agent_auth_env
    data = env.config.model_dump(mode="json", exclude={"extensions"})
    data.update(
        models=[{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline", "api_key": "unused"}],
        agents_api={"enabled": True},
        database={"backend": "sqlite", "sqlite_dir": str(tmp_path / "gateway-db")},
        title={"enabled": False},
        memory={"enabled": False},
        summarization={"enabled": False},
        tool_search={"enabled": False},
    )
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    extensions_path.write_text(env.config.extensions.model_dump_json(by_alias=True), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("AUTH_JWT_SECRET", "isolated-agent-auth-test-secret-1234567890")
    monkeypatch.setattr("app.gateway.auth.config._auth_config", None)
    monkeypatch.setattr("app.gateway.deps._cached_local_provider", None)
    monkeypatch.setattr("app.gateway.deps._cached_repo", None)
    reset_app_config()
    reset_extensions_config()
    prompts = []
    mutate_definition = []

    class Model(FakeToolCallingModel):
        def _generate(self, messages, *args, **kwargs):
            prompts.append(messages)
            return super()._generate(messages, *args, **kwargs)

    def model_factory(*args, **kwargs):
        if mutate_definition:
            mutate_definition.pop()()
        return Model(responses=[AIMessage(content="", tool_calls=[{"name": "tickets_search", "args": {}, "id": "call-search", "type": "tool_call"}]), AIMessage(content="done")])

    monkeypatch.setattr("deerflow.agents.lead_agent.agent.create_chat_model", model_factory)
    try:
        with TestClient(create_app()) as client:

            def register(email):
                client.cookies.clear()
                response = client.post("/api/v1/auth/register", json={"email": email, "password": "strong-test-password-123"})
                assert response.status_code == 201, response.text
                client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
                created = client.post("/api/agents", json={"name": env.agent.name, "soul": env.soul, "skills": [], "tool_groups": ["mcp"]})
                assert created.status_code == 201, created.text
                return response.json()["id"]

            def run(context):
                thread = client.post("/api/threads", json={})
                assert thread.status_code == 200, thread.text
                return client.post(
                    f"/api/threads/{thread.json()['thread_id']}/runs/wait",
                    json={
                        "assistant_id": "lead_agent",
                        "input": {"messages": [{"role": "user", "content": "Search tickets."}]},
                        "context": {"mode": "flash", "subagent_enabled": False, **context},
                        "config": {"configurable": {AGENT_AUTH_CONTEXT_KEY: {"binding": "research-tickets", "user_id": "alice"}}},
                    },
                )

            owner = register("owner@example.com")
            config = load_agent_config(env.agent.name, user_id=owner)
            binding = data["mcp_agent_auth"]["research-tickets"]
            binding["owners"] = [owner]
            binding["definition_digests"] = [agent_definition_digest(config, env.soul)]
            config_path.write_text(json.dumps(data), encoding="utf-8")
            directory = tmp_path / "users" / owner / "agents" / env.agent.name
            mutate_definition.append(lambda: (directory / "SOUL.md").write_text("Unreviewed replacement.", encoding="utf-8"))
            response = run({"agent_name": env.agent.name})
            assert response.status_code == 200, response.text
            assert agent_mcp_transport.calls == [("search", "Bearer research-client-token")], response.text
            assert "Bearer discovery-secret" in agent_mcp_transport.discoveries
            system = str(prompts[0][0].content)
            assert env.soul in system and "Unreviewed replacement." not in system
            response = run({"agent_name": env.agent.name})
            assert response.status_code == 403, response.text
            assert len(agent_mcp_transport.calls) == 1

            (directory / "SOUL.md").write_text(env.soul, encoding="utf-8")
            for context in ({"agent_name": env.agent.name, "is_bootstrap": True}, {}):
                response = run(context)
                assert response.status_code == 200, response.text
                assert len(agent_mcp_transport.calls) == 1
            register("other-owner@example.com")
            denied = client.post("/api/mcp/personal/config/servers", json={"mcp_servers": {"tickets": {"type": "http", "url": "https://mcp.example", "agent_auth": True}}})
            assert denied.status_code == 422, denied.text
            response = run({"agent_name": env.agent.name, AGENT_AUTH_CONTEXT_KEY: {"binding": "research-tickets", "user_id": owner}})
            assert response.status_code == 200, response.text
            assert len(agent_mcp_transport.calls) == 1
            assert agent_mcp_transport.token_clients == ["research-client"]
    finally:
        reset_extensions_config()
        reset_app_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("delegation", ["task", "batch_task"])
@pytest.mark.parametrize("revoked", [False, True])
async def test_delegation_inherits_parent_identity_including_durable_recovery(agent_auth_env, agent_mcp_transport, real_subagents, tmp_path, monkeypatch, delegation, revoked):
    from _agent_e2e_helpers import FakeToolCallingModel, build_single_tool_call_model
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.config.extensions_config import reset_extensions_config
    from deerflow.config.model_config import ModelConfig
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, capture_agent_authority
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.subagent_batches import SubagentBatchRepository, SubagentBatchRow
    from deerflow.subagents.batch_runtime import set_subagent_batch_submitter
    from deerflow.subagents.batch_service import SubagentBatchService
    from deerflow.tools.builtins.batch_task_tool import batch_task
    from deerflow.tools.builtins.task_tool import task_tool

    env = agent_auth_env
    env.config.models = [ModelConfig(name="offline", use="langchain_openai:ChatOpenAI", model="offline", api_key="unused")]
    env.config.tool_search.enabled = False
    env.config.memory.enabled = False
    env.config.summarization.enabled = False
    env.config.title.enabled = False
    env.config.subagent_batches.enabled = True
    # A child with its own admin binding must still use its caller's identity.
    child_binding = env.config.mcp_agent_auth["research-tickets"].model_copy(deep=True)
    child_binding.agent = "general-purpose"
    child_binding.oauth.client_id = "other-child-account"
    env.config.mcp_agent_auth["child-tickets"] = child_binding
    authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(env.config.extensions.model_dump_json(by_alias=True), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    reset_extensions_config()
    observed = []

    class ChildModel(FakeToolCallingModel):
        def _generate(self, messages, *args, **kwargs):
            observed.extend(message for message in messages if message.type == "tool")
            return super()._generate(messages, *args, **kwargs)

    monkeypatch.setattr(real_subagents, "create_chat_model", lambda **kwargs: ChildModel(responses=build_single_tool_call_model(tool_name="tickets_search", tool_args={}).responses))
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "batch-db")))
    repo = SubagentBatchRepository(get_session_factory())

    def service():
        return SubagentBatchService(repository=repo, config=env.config.subagent_batches, runtime_config=env.config.subagent_runtime, app_config=env.config)

    first, restarted = service(), None
    set_subagent_batch_submitter(first)
    try:
        graph = StateGraph(ThreadState, context_schema=dict)
        graph.add_node("tools", ToolNode([task_tool, batch_task], handle_tool_errors=False))
        graph.add_edge(START, "tools")
        graph.add_edge("tools", END)
        args = {"subagent_type": "general-purpose"}
        if delegation == "task":
            args.update(description="Search", prompt="Search tickets.")
            if revoked:
                env.config.mcp_agent_auth["research-tickets"].enabled = False
        else:
            args.update(title="Search", items=[{"key": "item-1", "prompt": "Search tickets."}])
        result = await asyncio.wait_for(
            graph.compile().ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"name": delegation, "args": args, "id": "delegate-1", "type": "tool_call"}])]},
                config={"metadata": {"model_name": "offline", "tool_groups": ["mcp"], "available_skills": []}},
                context={"user_id": "alice", "thread_id": "t-delegate", "run_id": "r-delegate", AGENT_AUTH_CONTEXT_KEY: authority},
            ),
            timeout=30,
        )
        message = result["messages"][-1]
        if delegation == "batch_task":
            batch_id = message.additional_kwargs["subagent_batch_id"]
            async with get_session_factory()() as session:
                saved_spec = (await session.get(SubagentBatchRow, batch_id)).execution_spec
            references = saved_spec["mcp_agent_auth"]
            assert references[0]["binding"] == "research-tickets"
            assert "private-client-secret" not in json.dumps(saved_spec)
            if revoked:
                env.config.mcp_agent_auth["research-tickets"].enabled = False
            restarted = service()
            await restarted.run_once(now=datetime.now(UTC))
            await asyncio.wait_for(asyncio.gather(*list(restarted._executions.values())), timeout=30)
            saved = await repo.get_batch(batch_id, user_id="alice")
            assert saved["counts"]["succeeded"] == 1, saved
        if revoked:
            assert any("revoked" in str(message.content) for message in observed), observed
            assert agent_mcp_transport.calls == []
            assert agent_mcp_transport.token_clients == []
        else:
            assert agent_mcp_transport.calls == [("search", "Bearer research-client-token")], message
            assert agent_mcp_transport.token_clients == ["research-client"]
    finally:
        set_subagent_batch_submitter(None)
        await first.stop()
        if restarted is not None:
            await restarted.stop()
        reset_extensions_config()
        await close_engine()

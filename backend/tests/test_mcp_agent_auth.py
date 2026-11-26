"""Administrator-granted MCP identities stay owner-bound and revocable."""

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from fastapi import HTTPException
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langgraph.runtime import Runtime
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from support.mcp_agent_auth import agent_auth_env as agent_auth_env
from support.mcp_agent_auth import agent_mcp_transport as agent_mcp_transport

from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig, pop_current_app_config, push_current_app_config, reset_app_config, set_app_config
from deerflow.config.extensions_config import McpServerConfig
from deerflow.config.mcp_agent_auth_config import McpAgentCredentialBinding, McpAgentGrant, McpAgentGrantSubject, StoredMcpAgentGrant
from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.mcp_agent_grants import McpAgentGrantRow, make_mcp_agent_grant_store
from deerflow.persistence.mcp_agent_grants.file import FileMcpAgentGrantStore
from deerflow.persistence.mcp_agent_grants.sql import SqlMcpAgentGrantStore


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


# --- runtime grants (grants: runtime) -------------------------------------------


@pytest.fixture
def runtime_env(agent_auth_env):
    """The shared agent_auth fixture, with its binding switched to runtime grants."""
    from deerflow.mcp.agent_auth import agent_definition_digest

    data = agent_auth_env.config.model_dump()
    binding = data["mcp_agent_auth"]["research-tickets"]
    binding.update(grants="runtime", owners=[], definition_digests=[])
    config = AppConfig.model_validate(data)
    set_app_config(config)
    store = make_mcp_agent_grant_store(config)
    digest = agent_definition_digest(agent_auth_env.agent, agent_auth_env.soul)

    def approve(binding_id, grant, app_config=None):
        """Store ``grant`` as an administrator approves it for the binding's current identity."""
        from deerflow.mcp.agent_auth import grant_subject

        app_config = app_config or config
        store.put(binding_id, StoredMcpAgentGrant(**grant.model_dump(), approved_for=grant_subject(app_config, app_config.mcp_agent_auth[binding_id])))

    return SimpleNamespace(**{**vars(agent_auth_env), "config": config, "store": store, "digest": digest, "approve": approve})


def _grant(owners=("alice",), digests=()):
    return McpAgentGrant(owners=list(owners), definition_digests=list(digests))


_SUBJECT = McpAgentGrantSubject(agent="research-bot", server="tickets", destination_digest="d" * 64, credential_digest="e" * 64)


def _stored(owners=("alice",), digests=()):
    return StoredMcpAgentGrant(owners=list(owners), definition_digests=list(digests), approved_for=_SUBJECT)


@pytest.mark.parametrize("updates", [{"owners": ["alice"]}, {"definition_digests": ["a" * 64]}])
def test_runtime_bindings_take_no_grants_from_config(agent_auth_env, updates):
    binding = agent_auth_env.config.mcp_agent_auth["research-tickets"].model_dump()
    binding.update(grants="runtime", owners=[], definition_digests=[])
    McpAgentCredentialBinding.model_validate(binding)
    with pytest.raises(ValidationError, match="admin API"):
        McpAgentCredentialBinding.model_validate({**binding, **updates})


@pytest.mark.parametrize("grant", [{"owners": ["*"], "definition_digests": []}, {"owners": ["a", "a"], "definition_digests": []}, {"owners": [], "definition_digests": ["unreviewed"]}, {"owners": []}])
def test_invalid_runtime_grants_are_rejected(grant):
    with pytest.raises(ValidationError):
        McpAgentGrant.model_validate(grant)


def test_runtime_binding_without_a_grant_admits_nobody(runtime_env):
    from deerflow.mcp.agent_auth import capture_agent_authority

    assert capture_agent_authority(runtime_env.config, user_id="alice", agent_config=runtime_env.agent) is None


def test_runtime_grant_applies_to_the_next_admission(runtime_env):
    from deerflow.mcp.agent_auth import McpAgentAuthorizationError, capture_agent_authority

    env = runtime_env
    env.approve("research-tickets", _grant(digests=["0" * 64]))
    with pytest.raises(McpAgentAuthorizationError, match="not approved"):
        capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
    env.approve("research-tickets", _grant(digests=["0" * 64, env.digest]))
    authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)
    assert [ref.binding for ref in authority.references] == ["research-tickets"]
    assert capture_agent_authority(env.config, user_id="bob", agent_config=env.agent) is None
    assert capture_agent_authority(env.config, user_id="alice", agent_config=AgentConfig(name="other")) is None


@pytest.mark.asyncio
async def test_removing_a_runtime_owner_denies_the_next_call_with_a_cached_token(runtime_env, monkeypatch):
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, build_agent_auth_interceptor, capture_agent_authority

    env = runtime_env
    env.approve("research-tickets", _grant(owners=["alice", "bob"], digests=[env.digest]))
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
    # Approving a new digest leaves admitted runs alone.
    env.approve("research-tickets", _grant(owners=["alice", "bob"], digests=["0" * 64]))
    assert await interceptor(request, handler) == "ok"
    env.approve("research-tickets", _grant(owners=["bob"], digests=[env.digest]))
    with pytest.raises(ToolException, match="revoked"):
        await interceptor(request, handler)
    env.store.delete("research-tickets")
    with pytest.raises(ToolException, match="revoked"):
        await interceptor(request, handler)
    assert len(calls) == 2 and len(token_requests) == 1


@pytest.mark.asyncio
async def test_an_unavailable_grant_store_fails_closed(runtime_env, monkeypatch):
    from deerflow.mcp import agent_auth
    from deerflow.mcp.agent_auth import AGENT_AUTH_CONTEXT_KEY, McpAgentAuthorizationError, build_agent_auth_interceptor, capture_agent_authority

    env = runtime_env
    env.approve("research-tickets", _grant(digests=[env.digest]))
    authority = capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)

    class Broken:
        def get(self, binding_id):
            raise OSError("database is down")

    monkeypatch.setattr("deerflow.persistence.mcp_agent_grants.make_mcp_agent_grant_store", lambda config: Broken())
    with pytest.raises(McpAgentAuthorizationError, match="unavailable"):
        capture_agent_authority(env.config, user_id="alice", agent_config=env.agent)

    async def handler(request):
        pytest.fail("A call reached the MCP transport without a readable grant")

    monkeypatch.setattr(agent_auth, "_token_manager", lambda *args: pytest.fail("token requested without a grant"))
    runtime = Runtime(context={"user_id": "alice", AGENT_AUTH_CONTEXT_KEY: authority})
    with pytest.raises(ToolException, match="unavailable"):
        await build_agent_auth_interceptor(env.config.extensions)(MCPToolCallRequest(name="search", args={}, server_name="tickets", runtime=runtime), handler)


def test_overlapping_runtime_grants_fail_admission(runtime_env):
    from deerflow.mcp.agent_auth import McpAgentAuthorizationError, capture_agent_authority

    env = runtime_env
    data = env.config.model_dump()
    data["mcp_agent_auth"]["second-grant"] = data["mcp_agent_auth"]["research-tickets"]
    config = AppConfig.model_validate(data)
    for binding_id in ("research-tickets", "second-grant"):
        env.approve(binding_id, _grant(digests=[env.digest]), config)
    with pytest.raises(McpAgentAuthorizationError, match="overlap"):
        capture_agent_authority(config, user_id="alice", agent_config=env.agent)


def _repoint_agent(config):
    binding = config.mcp_agent_auth["research-tickets"]
    config.mcp_agent_auth["research-tickets"] = binding.model_copy(update={"agent": "other-bot"})
    return "other-bot"


def _repoint_server(config):
    config.extensions.mcp_servers["tickets-2"] = config.extensions.mcp_servers["tickets"].model_copy(deep=True)
    binding = config.mcp_agent_auth["research-tickets"]
    config.mcp_agent_auth["research-tickets"] = binding.model_copy(update={"server": "tickets-2"})


def _move_destination(config):
    config.extensions.mcp_servers["tickets"].url = "https://other-mcp.example"


def _change_oauth(**updates):
    def change(config):
        binding = config.mcp_agent_auth["research-tickets"]
        config.mcp_agent_auth["research-tickets"] = binding.model_copy(update={"oauth": binding.oauth.model_copy(update=updates)})

    return change


@pytest.mark.parametrize(
    ("change", "in_force"),
    [
        pytest.param(_repoint_agent, False, id="agent"),
        pytest.param(_repoint_server, False, id="server"),
        pytest.param(_move_destination, False, id="destination"),
        pytest.param(_change_oauth(client_id="other-client"), False, id="oauth-client"),
        pytest.param(_change_oauth(token_url="https://other-idp.example/token"), False, id="oauth-endpoint"),
        pytest.param(_change_oauth(client_secret="rotated-client-secret"), True, id="secret-rotation"),
    ],
)
def test_a_runtime_grant_admits_only_for_the_identity_it_was_approved_for(runtime_env, change, in_force):
    from deerflow.mcp.agent_auth import agent_definition_digest, capture_agent_authority

    env = runtime_env
    other_digest = agent_definition_digest(AgentConfig(name="other-bot"), "")
    env.approve("research-tickets", _grant(digests=[env.digest, other_digest]))
    config = env.config.model_copy(deep=True)
    renamed = change(config)
    set_app_config(config)
    authority = capture_agent_authority(config, user_id="alice", agent_config=AgentConfig(name=renamed) if renamed else env.agent)
    assert (authority is not None) == in_force
    if in_force:
        assert [ref.binding for ref in authority.references] == ["research-tickets"]


# --- stores ------------------------------------------------------------------


@pytest.fixture(params=["file", "sqlite"])
def store(request, tmp_path, monkeypatch):
    if request.param == "file":
        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
        monkeypatch.setattr("deerflow.config.paths._paths", None)
        yield FileMcpAgentGrantStore()
        return
    store = SqlMcpAgentGrantStore(f"sqlite:///{tmp_path}/grants.db")
    engine = store._Session.kw["bind"]
    try:
        Base.metadata.create_all(engine, tables=[McpAgentGrantRow.__table__])
        yield store
    finally:
        engine.dispose()


def test_store_replaces_lists_and_deletes(store):
    assert store.get("b1") is None and store.list() == {}
    store.put("b1", _stored(owners=["alice"], digests=["a" * 64]))
    store.put("b1", _stored(owners=["bob"], digests=["b" * 64]))
    store.put("b0", _stored(owners=[]))
    assert store.get("b1") == _stored(owners=["bob"], digests=["b" * 64])
    assert list(store.list()) == ["b0", "b1"]
    assert store.delete("b1") is True
    assert store.delete("b1") is False
    assert store.get("b1") is None


def test_file_store_never_applies_a_grant_to_another_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    store = FileMcpAgentGrantStore()
    store.put("Tickets", _stored())
    # Simulate a case-insensitive filesystem resolving "tickets" to the same file.
    (tmp_path / "mcp-agent-grants" / "tickets.json").write_text((tmp_path / "mcp-agent-grants" / "Tickets.json").read_text())
    assert store.get("tickets") is None
    assert store.delete("tickets") is False
    with pytest.raises(ValueError, match="differs only in case"):
        store.put("tickets", _stored())
    with pytest.raises(ValueError):
        store.put("CON", _stored())
    assert json.loads((tmp_path / "mcp-agent-grants" / "Tickets.json").read_text())["binding"] == "Tickets"


def test_file_store_treats_a_grant_removed_during_a_read_as_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    store = FileMcpAgentGrantStore()
    store.put("b1", _stored(owners=["alice"]))
    store.put("b2", _stored(owners=["bob"]))
    root = tmp_path / "mcp-agent-grants"
    real_glob = Path.glob

    def glob_then_revoke(self, pattern):
        paths = list(real_glob(self, pattern))
        (root / "b1.json").unlink(missing_ok=True)  # a concurrent revoke after discovery
        return iter(paths)

    monkeypatch.setattr(Path, "glob", glob_then_revoke)
    assert list(store.list()) == ["b2"]
    assert store.get("b1") is None and store.delete("b1") is False
    (root / "b3.json").write_text("{")
    with pytest.raises(json.JSONDecodeError):
        store.list()


@pytest.mark.asyncio
async def test_migration_creates_and_drops_the_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema="")

    async def tables():
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))

    try:
        await asyncio.to_thread(command.upgrade, cfg, "0061_coordination_coordinator")
        assert "mcp_agent_grants" not in await tables()
        await asyncio.to_thread(command.upgrade, cfg, "0062_mcp_agent_grants")
        assert "mcp_agent_grants" in await tables()
        await asyncio.to_thread(command.downgrade, cfg, "0061_coordination_coordinator")
        assert "mcp_agent_grants" not in await tables()
    finally:
        await engine.dispose()


# --- admin API ---------------------------------------------------------------


def _request(role: str):
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role=role)))


@pytest.fixture
def api_env(runtime_env, monkeypatch):
    from app.gateway.routers import mcp_agent_auth as router

    async def drained(action, func, expected_errors=(), /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(router, "run_drained_write", drained)
    data = runtime_env.config.model_dump()
    data["mcp_agent_auth"]["config-grant"] = {**data["mcp_agent_auth"]["research-tickets"], "agent": "other-bot", "grants": "config", "owners": ["carol"], "definition_digests": ["c" * 64]}
    config = AppConfig.model_validate(data)
    set_app_config(config)
    return SimpleNamespace(router=router, env=runtime_env, config=config)


@pytest.mark.asyncio
async def test_admin_api_requires_an_admin(api_env):
    router = api_env.router
    for call in (
        router.list_bindings(_request("user")),
        router.get_binding("research-tickets", _request("user")),
        router.put_grant("research-tickets", _grant(), _request("user")),
        router.delete_grant("research-tickets", _request("user")),
        router.definition_digest("research-tickets", _request("user"), owner="alice"),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 403
    assert api_env.env.store.get("research-tickets") is None


@pytest.mark.asyncio
async def test_admin_api_maintains_runtime_grants(api_env):
    router, env = api_env.router, api_env.env
    admin = _request("admin")
    listed = (await router.list_bindings(admin)).model_dump()["bindings"]
    assert [(b["binding"], b["grants"], b["approval"], b["owners"]) for b in listed] == [("config-grant", "config", "config", ["carol"]), ("research-tickets", "runtime", "none", [])]
    assert all("oauth" not in b and "client_secret" not in json.dumps(b) for b in listed)

    digest = await router.definition_digest("research-tickets", admin, owner="alice")
    assert digest.definition_digest == env.digest
    response = await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[digest.definition_digest]), admin)
    assert response.owners == ["alice"] and response.definition_digests == [env.digest] and response.approval == "current"
    assert (await router.get_binding("research-tickets", admin)).owners == ["alice"]

    from deerflow.mcp.agent_auth import capture_agent_authority

    assert capture_agent_authority(api_env.config, user_id="alice", agent_config=env.agent) is not None
    assert (await router.delete_grant("research-tickets", admin)).status_code == 204
    assert capture_agent_authority(api_env.config, user_id="alice", agent_config=env.agent) is None


@pytest.mark.asyncio
async def test_admin_api_reports_and_replaces_a_stale_grant(api_env):
    from deerflow.mcp.agent_auth import capture_agent_authority

    router, env = api_env.router, api_env.env
    admin = _request("admin")
    assert (await router.get_binding("research-tickets", admin)).approval == "none"
    assert (await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[env.digest]), admin)).approval == "current"
    moved = api_env.config.model_copy(deep=True)
    _change_oauth(client_id="other-client")(moved)
    set_app_config(moved)
    stale = await router.get_binding("research-tickets", admin)
    assert (stale.approval, stale.owners) == ("stale", ["alice"])
    assert capture_agent_authority(moved, user_id="alice", agent_config=env.agent) is None
    # A stale grant admits nobody but keeps its owners reserved: a rollback makes it current again.
    data = moved.model_dump()
    data["mcp_agent_auth"]["research-tickets-2"] = {**data["mcp_agent_auth"]["research-tickets"]}
    with_second = AppConfig.model_validate(data)
    set_app_config(with_second)
    with pytest.raises(HTTPException) as exc:
        await router.put_grant("research-tickets-2", _grant(owners=["alice"]), admin)
    assert exc.value.status_code == 409 and "research-tickets'" in exc.value.detail
    set_app_config(api_env.config)  # roll the OAuth client back
    assert (await router.get_binding("research-tickets", admin)).approval == "current"
    assert capture_agent_authority(api_env.config, user_id="alice", agent_config=env.agent) is not None
    # Deleting the stale grant releases its owners.
    set_app_config(with_second)
    assert (await router.delete_grant("research-tickets", admin)).status_code == 204
    assert (await router.put_grant("research-tickets-2", _grant(owners=["alice"]), admin)).approval == "current"
    with pytest.raises(HTTPException) as exc:
        await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[env.digest]), admin)
    assert exc.value.status_code == 409
    assert (await router.put_grant("research-tickets", _grant(owners=["bob"], digests=[env.digest]), admin)).approval == "current"


@pytest.mark.asyncio
async def test_admin_api_lists_reserves_and_deletes_a_retired_grant(api_env):
    router, env = api_env.router, api_env.env
    admin = _request("admin")
    await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[env.digest]), admin)
    # GitOps renames the binding: the old grant is retired, not gone.
    data = api_env.config.model_dump()
    data["mcp_agent_auth"]["tickets"] = data["mcp_agent_auth"].pop("research-tickets")
    set_app_config(AppConfig.model_validate(data))
    listed = (await router.list_bindings(admin)).model_dump()["bindings"]
    assert [(b["binding"], b["approval"], b["agent"], b["owners"]) for b in listed][-1] == ("research-tickets", "retired", env.agent.name, ["alice"])
    assert (await router.get_binding("research-tickets", admin)).approval == "retired"
    with pytest.raises(HTTPException) as exc:
        await router.put_grant("tickets", _grant(owners=["alice"], digests=[env.digest]), admin)
    assert exc.value.status_code == 409 and "research-tickets" in exc.value.detail
    assert (await router.delete_grant("research-tickets", admin)).status_code == 204
    assert (await router.put_grant("tickets", _grant(owners=["alice"], digests=[env.digest]), admin)).approval == "current"
    with pytest.raises(HTTPException) as exc:
        await router.get_binding("research-tickets", admin)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await router.delete_grant("research-tickets", admin)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_api_shows_a_stored_grant_after_a_switch_to_config_grants(api_env):
    router, env = api_env.router, api_env.env
    admin = _request("admin")
    await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[env.digest]), admin)
    # GitOps moves the binding to config grants; the runtime grant stays stored and keeps alice reserved.
    data = api_env.config.model_dump()
    data["mcp_agent_auth"]["research-tickets"] |= {"grants": "config", "owners": ["bob"], "definition_digests": [env.digest]}
    data["mcp_agent_auth"]["research-tickets-2"] = {**api_env.config.model_dump()["mcp_agent_auth"]["research-tickets"]}
    set_app_config(AppConfig.model_validate(data))
    expected = {"server": "tickets", "agent": env.agent.name, "owners": ["alice"], "definition_digests": [env.digest]}
    shown = (await router.get_binding("research-tickets", admin)).model_dump()
    assert (shown["approval"], shown["owners"], shown["stored_grant"]) == ("config", ["bob"], expected)
    listed = {b["binding"]: b for b in (await router.list_bindings(admin)).model_dump()["bindings"]}
    assert listed["research-tickets"]["stored_grant"] == expected
    assert listed["config-grant"]["stored_grant"] is None and listed["research-tickets-2"]["stored_grant"] is None
    # The 409 names a binding whose details now show the reserved owner.
    with pytest.raises(HTTPException) as exc:
        await router.put_grant("research-tickets-2", _grant(owners=["alice"]), admin)
    assert exc.value.status_code == 409 and "research-tickets'" in exc.value.detail
    assert (await router.delete_grant("research-tickets", admin)).status_code == 204
    assert (await router.get_binding("research-tickets", admin)).stored_grant is None
    assert (await router.put_grant("research-tickets-2", _grant(owners=["alice"]), admin)).owners == ["alice"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "status"),
    [
        (lambda r, admin: r.put_grant("config-grant", _grant(), admin), 409),
        (lambda r, admin: r.delete_grant("config-grant", admin), 409),
        (lambda r, admin: r.put_grant("missing", _grant(), admin), 404),
        (lambda r, admin: r.get_binding("missing", admin), 404),
        (lambda r, admin: r.delete_grant("research-tickets", admin), 404),
        (lambda r, admin: r.definition_digest("research-tickets", admin, owner="bob"), 404),
    ],
)
async def test_admin_api_refuses_what_it_does_not_own(api_env, call, status):
    with pytest.raises(HTTPException) as exc:
        await call(api_env.router, _request("admin"))
    assert exc.value.status_code == status
    assert api_env.config.mcp_agent_auth["config-grant"].owners == ["carol"]


@pytest.mark.asyncio
async def test_admin_api_rejects_owners_granted_by_another_binding(api_env):
    router, env = api_env.router, api_env.env
    data = api_env.config.model_dump()
    data["mcp_agent_auth"]["research-tickets-2"] = {**data["mcp_agent_auth"]["research-tickets"]}
    data["mcp_agent_auth"]["config-grant"]["agent"] = env.agent.name
    set_app_config(AppConfig.model_validate(data))
    admin = _request("admin")
    await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[env.digest]), admin)
    for binding_id, owners in (("research-tickets-2", ["bob", "alice"]), ("research-tickets", ["carol"])):
        with pytest.raises(HTTPException) as exc:
            await router.put_grant(binding_id, _grant(owners=owners), admin)
        assert exc.value.status_code == 409 and "overlap" in exc.value.detail
    await router.put_grant("research-tickets-2", _grant(owners=["bob"]), admin)


@pytest.mark.asyncio
async def test_admin_api_keeps_owners_reserved_while_a_binding_is_disabled(api_env):
    router, env = api_env.router, api_env.env
    data = api_env.config.model_dump()
    data["mcp_agent_auth"]["research-tickets-2"] = {**data["mcp_agent_auth"]["research-tickets"]}
    data["mcp_agent_auth"]["config-grant"]["agent"] = env.agent.name
    set_app_config(AppConfig.model_validate(data))
    admin = _request("admin")
    await router.put_grant("research-tickets", _grant(owners=["alice"], digests=[env.digest]), admin)

    def disable(*binding_ids):
        changed = AppConfig.model_validate(data).model_dump()
        for binding_id in binding_ids:
            changed["mcp_agent_auth"][binding_id]["enabled"] = False
        set_app_config(AppConfig.model_validate(changed))

    # Disabling the binding that holds the grant keeps its owner reserved.
    disable("research-tickets")
    with pytest.raises(HTTPException) as exc:
        await router.put_grant("research-tickets-2", _grant(owners=["alice"]), admin)
    assert exc.value.status_code == 409 and "research-tickets'" in exc.value.detail
    # A grant written to a disabled binding is checked too, against stored and configured owners.
    disable("research-tickets-2")
    for owners, holder in ((["alice"], "research-tickets'"), (["carol"], "config-grant'")):
        with pytest.raises(HTTPException) as exc:
            await router.put_grant("research-tickets-2", _grant(owners=owners), admin)
        assert exc.value.status_code == 409 and holder in exc.value.detail
    # A disabled config binding keeps its owners reserved as well.
    disable("config-grant")
    with pytest.raises(HTTPException) as exc:
        await router.put_grant("research-tickets-2", _grant(owners=["carol"]), admin)
    assert exc.value.status_code == 409 and "config-grant'" in exc.value.detail
    # Deleting the grant releases its owner.
    assert (await router.delete_grant("research-tickets", admin)).status_code == 204
    assert (await router.put_grant("research-tickets-2", _grant(owners=["alice"]), admin)).owners == ["alice"]


def test_admin_api_routes_validate_over_http(api_env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(api_env.router.router)

    @app.middleware("http")
    async def as_admin(request, call_next):
        request.state.user = SimpleNamespace(system_role="admin")
        return await call_next(request)

    client = TestClient(app)
    digest = api_env.env.digest
    assert client.put("/api/mcp/agent-auth/research-tickets/grants", json={"owners": ["alice"], "definition_digests": [digest]}).status_code == 200
    assert client.get("/api/mcp/agent-auth/research-tickets").json()["owners"] == ["alice"]
    assert client.put("/api/mcp/agent-auth/research-tickets/grants", json={"owners": ["*"], "definition_digests": []}).status_code == 422
    assert client.put("/api/mcp/agent-auth/research-tickets/grants", json={"owners": [], "definition_digests": [], "extra": 1}).status_code == 422
    assert client.get("/api/mcp/agent-auth/-bad").status_code == 422
    assert client.get("/api/mcp/agent-auth/research-tickets/definition-digest", params={"owner": "alice"}).json()["definition_digest"] == digest
    for owner in ("alice@example.com", "../alice"):  # file-backed storage cannot hold these owners
        assert client.get("/api/mcp/agent-auth/research-tickets/definition-digest", params={"owner": owner}).status_code == 422
    assert client.get("/api/mcp/agent-auth/research-tickets/definition-digest", params={"owner": "nobody"}).status_code == 404
    assert client.delete("/api/mcp/agent-auth/research-tickets/grants").status_code == 204

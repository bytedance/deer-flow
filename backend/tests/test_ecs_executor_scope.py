"""Trusted submission scope through DeerFlow's native MCP task path."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException, tool
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp.tasks import TaskSubmitRequest
from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver

SECRET = b"operator-secret-at-least-32-bytes-long"
CONTEXT = {"user_id": "alice", "thread_id": "thread-1", "thread_incarnation": "generation-1", "run_id": "run-1"}
ARGS = {"command": "echo hello", "user_id": "model-spoof"}


@pytest.fixture(autouse=True)
def _optional_package_source(monkeypatch):
    """Test the optional package from this checkout without a runtime dependency."""
    source = Path(__file__).resolve().parents[1] / "packages" / "ecs-executor"
    monkeypatch.syspath_prepend(str(source))
    import ecs_executor.scope

    assert Path(ecs_executor.scope.__file__).resolve() == source / "ecs_executor" / "scope.py"


def _builder(monkeypatch, *, transport="http", headers=None):
    from ecs_executor.interceptor import build_execution_scope_interceptor

    for name, value in {"ECS_EXECUTOR_SCOPE_SECRET": SECRET.decode(), "ECS_EXECUTOR_SCOPE_SERVER": "ecs", "ECS_EXECUTOR_SCOPE_SUBMIT_TOOL": "submit", "ECS_EXECUTOR_SCOPE_AUDIENCE": "ecs-worker"}.items():
        monkeypatch.setenv(name, value)
    server = {"type": transport, "url": "https://ecs.invalid/mcp"} if transport != "stdio" else {"type": "stdio", "command": "uvx"}
    server["headers"] = headers or {}
    config = ExtensionsConfig.model_validate({"mcpServers": {"ecs": server}, "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"]})
    monkeypatch.setattr("ecs_executor.interceptor.get_extensions_config", lambda: config)
    return build_execution_scope_interceptor(), config


def _verify(token, **kwargs):
    from ecs_executor.scope import verify_execution_scope

    return verify_execution_scope(token, secret=SECRET, authenticated_user_id="alice", arguments=ARGS, expected_audience="ecs-worker", expected_operation="submit", **kwargs)


def test_native_tool_node_durable_submit_uses_ambient_trusted_context(monkeypatch):
    from ecs_executor.scope import SCOPE_HEADER

    _, config = _builder(monkeypatch)
    opened = {}
    seen_args = {}

    @asynccontextmanager
    async def session_context(connection):
        opened.update(connection.get("headers", {}))

        async def call_tool(name, args, **kwargs):
            seen_args.update(args)
            return SimpleNamespace(structuredContent={"task_id": "remote-1", "status": "running"}, isError=False)

        yield SimpleNamespace(initialize=AsyncMock(), call_tool=call_tool)

    caller = McpTaskToolCaller(config, oauth_token_manager=SimpleNamespace(has_oauth_servers=lambda: False, get_authorization_header=AsyncMock(return_value=None)))
    driver = OrdinaryMcpTaskDriver(caller)

    @tool
    async def submit_work() -> str:
        """Submit execution work."""
        await driver.submit(
            TaskSubmitRequest(
                user_id="alice",
                thread_id="thread-1",
                thread_incarnation="generation-1",
                run_id="run-1",
                tool_call_id="call-1",
                server_name="ecs",
                task_name="work",
                arguments=ARGS,
                driver_data={"submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"},
            )
        )
        return "submitted"

    graph = StateGraph(MessagesState, context_schema=dict)
    graph.add_node("tools", ToolNode([submit_work]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    with patch("langchain_mcp_adapters.sessions.create_session", session_context):
        asyncio.run(graph.compile().ainvoke({"messages": [AIMessage(content="", tool_calls=[{"name": "submit_work", "args": {}, "id": "call-1", "type": "tool_call"}])]}, context=CONTEXT))
    claims = _verify(opened[SCOPE_HEADER])
    assert {key: claims[key] for key in CONTEXT if key != "thread_incarnation"} == {key: value for key, value in CONTEXT.items() if key != "thread_incarnation"}
    assert claims["incarnation"] == CONTEXT["thread_incarnation"]
    assert seen_args == ARGS  # scope/signature is transport-only, even with model owner spoofing


@pytest.mark.asyncio
async def test_submit_replaces_all_reserved_header_copies(monkeypatch):
    from ecs_executor.scope import SCOPE_HEADER

    interceptor, _ = _builder(monkeypatch)
    handler = AsyncMock(return_value="ok")
    request = MCPToolCallRequest(name="submit", args=ARGS, server_name="ecs", runtime=SimpleNamespace(context=CONTEXT), headers={SCOPE_HEADER.lower(): "spoof", SCOPE_HEADER.upper(): "spoof2", "Other": "kept"})
    assert await interceptor(request, handler) == "ok"
    headers = handler.call_args.args[0].headers
    assert set(headers) == {SCOPE_HEADER, "Other"}
    assert _verify(headers[SCOPE_HEADER])["user_id"] == "alice"


@pytest.mark.asyncio
async def test_missing_runtime_or_identity_fails_closed(monkeypatch):
    interceptor, _ = _builder(monkeypatch)
    monkeypatch.setattr("ecs_executor.interceptor._current_runtime", lambda: None)
    handler = AsyncMock()
    for context in (None, {key: value for key, value in CONTEXT.items() if key != "user_id"}, {key: value for key, value in CONTEXT.items() if key != "thread_incarnation"}, {**CONTEXT, "run_id": ""}):
        with pytest.raises(ToolException, match="trusted execution scope"):
            await interceptor(MCPToolCallRequest(name="submit", args=ARGS, server_name="ecs", runtime=SimpleNamespace(context=context)), handler)
    handler.assert_not_called()


def test_verifier_rejects_tampering_expiry_wrong_owner_and_argument_changes():
    from ecs_executor.scope import mint_execution_scope, verify_execution_scope

    token = mint_execution_scope(secret=SECRET, audience="ecs-worker", user_id="alice", thread_id="thread-1", incarnation="generation-1", run_id="run-1", operation="submit", arguments=ARGS, now=100, ttl_seconds=60)
    assert _verify(token, now=120)["exp"] == 160
    with pytest.raises(ValueError):
        _verify(token[:-1] + ("A" if token[-1] != "A" else "B"), now=120)
    with pytest.raises(ValueError):
        _verify(token, now=160)
    for overrides in ({"authenticated_user_id": "mallory"}, {"arguments": {"command": "changed"}}, {"expected_audience": "other"}, {"expected_operation": "cancel"}):
        params = {"secret": SECRET, "authenticated_user_id": "alice", "arguments": ARGS, "expected_audience": "ecs-worker", "expected_operation": "submit", "now": 120, **overrides}
        with pytest.raises(ValueError):
            verify_execution_scope(token, **params)


@pytest.mark.asyncio
async def test_background_status_cancel_and_other_servers_passthrough(monkeypatch):
    interceptor, _ = _builder(monkeypatch)
    for server, name in (("ecs", "status"), ("ecs", "cancel"), ("other", "submit")):
        request = MCPToolCallRequest(name=name, args={"task_id": "remote-1"}, server_name=server, runtime=None)
        handler = AsyncMock(return_value="unchanged")
        assert await interceptor(request, handler) == "unchanged"
        assert handler.call_args.args[0] is request


def test_strict_bounds_secret_and_transport_configuration(monkeypatch):
    from ecs_executor.scope import mint_execution_scope

    for overrides in ({"secret": b"short"}, {"ttl_seconds": 301}, {"ttl_seconds": True}, {"user_id": "x" * 256}, {"arguments": {"bad": float("nan")}}):
        with pytest.raises(ValueError):
            mint_execution_scope(**{"secret": SECRET, "audience": "ecs-worker", "user_id": "alice", "thread_id": "thread-1", "incarnation": None, "run_id": "run-1", "operation": "submit", "arguments": ARGS, "now": 100, **overrides})
    with pytest.raises(ValueError, match="HTTP"):
        _builder(monkeypatch, transport="stdio")

    with pytest.raises(ValueError, match="statically"):
        _builder(monkeypatch, headers={"x-deerflow-execution-scope": "unsafe-static"})


def test_ambient_runtime_retains_native_incarnation_metadata_guard(monkeypatch):
    """Standalone LangGraph Runtime lacks config; its guard still needs metadata."""
    from ecs_executor.scope import SCOPE_HEADER

    from deerflow.mcp_scope import THREAD_INCARNATION_METADATA_GUARD_KEY

    interceptor, _ = _builder(monkeypatch)
    handler = AsyncMock(return_value="submitted")

    @tool
    async def guarded_submit() -> str:
        """Submit with the current native runtime lifecycle guard."""
        return await interceptor(MCPToolCallRequest(name="submit", args=ARGS, server_name="ecs", runtime=None), handler)

    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([guarded_submit], handle_tool_errors=False))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    state = {"messages": [AIMessage(content="", tool_calls=[{"name": "guarded_submit", "args": {}, "id": "guard-1", "type": "tool_call"}])]}
    context = {**CONTEXT, THREAD_INCARNATION_METADATA_GUARD_KEY: True}
    asyncio.run(graph.ainvoke(state, config={"metadata": {"thread_incarnation": "generation-1"}}, context=context))
    assert _verify(handler.call_args.args[0].headers[SCOPE_HEADER])["incarnation"] == "generation-1"
    handler.reset_mock()
    with pytest.raises(ToolException, match="trusted execution scope"):
        asyncio.run(graph.ainvoke(state, config={"metadata": {"thread_incarnation": "stale-generation"}}, context=context))
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_scoped_submit_uses_original_runtime_identity_and_cannot_downgrade(monkeypatch):
    from dataclasses import asdict

    from ecs_executor.scope import SCOPE_HEADER

    from deerflow.authz.workspace import WorkspaceContext, reset_current_workspace, set_current_workspace

    original = WorkspaceContext("22222222-2222-2222-2222-222222222222", "alice", 2, 3)
    other = WorkspaceContext("33333333-3333-3333-3333-333333333333", "alice", 4, 5)
    interceptor, _ = _builder(monkeypatch)
    handler = AsyncMock(return_value="ok")
    token = set_current_workspace(other)
    try:
        context = {**CONTEXT, **asdict(original), "workspace_context": original}
        await interceptor(MCPToolCallRequest(name="submit", args=ARGS, server_name="ecs", runtime=SimpleNamespace(context=context)), handler)
        signed = handler.call_args.args[0].headers[SCOPE_HEADER]
        claims = _verify(signed, expected_workspace_context=original)
        assert claims["version"] == 2 and claims["workspace_context"] == asdict(original)
        with pytest.raises(ValueError, match="workspace"):
            _verify(signed)  # a receiver without tenant authorization cannot accept it
        for invalid in ({**CONTEXT}, {**context, "workspace_context": asdict(original)}, {**context, "workspace_context": None}):
            denied = AsyncMock()
            with pytest.raises(ToolException, match="trusted execution scope"):
                await interceptor(MCPToolCallRequest(name="submit", args=ARGS, server_name="ecs", runtime=SimpleNamespace(context=invalid)), denied)
            denied.assert_not_called()
    finally:
        reset_current_workspace(token)

"""Tests for request-scoped secret injection into MCP HTTP/SSE headers."""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain.agents import AgentState as _AgentState
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    McpContextHeadersConfig,
    McpServerConfig,
    McpTaskToolsetConfig,
    McpUserScopedAuthConfig,
)
from deerflow.mcp.context_headers import build_context_headers_interceptor
from deerflow.mcp.interceptors import build_mcp_tool_interceptors

TENANT_TOKEN = "Bearer tenant-scoped-token"


def _config(**context_headers_kwargs) -> ExtensionsConfig:
    return ExtensionsConfig(
        mcp_servers={
            "shared-http": McpServerConfig(
                enabled=True,
                type="http",
                url="https://mcp.example.com/mcp",
                headers={"Authorization": "Bearer discovery-token"},
                headers_from_context=McpContextHeadersConfig(**context_headers_kwargs),
            ),
            "other": McpServerConfig(enabled=True, type="http", url="https://other.example.com/mcp"),
        },
        skills={},
    )


def _request(server_name: str = "shared-http", headers: dict | None = None, runtime: object | None = None) -> MCPToolCallRequest:
    return MCPToolCallRequest(
        name="act",
        args={},
        server_name=server_name,
        headers=headers,
        runtime=runtime,
    )


def _runtime_with_secrets(**secrets: str) -> object:
    return SimpleNamespace(context={"secrets": dict(secrets), "thread_id": "th-1"})


async def _echo_handler(request: MCPToolCallRequest) -> MCPToolCallRequest:
    return request


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_no_declaring_server_returns_none():
    config = ExtensionsConfig(
        mcp_servers={"plain": McpServerConfig(enabled=True, type="http", url="https://x.example.com")},
        skills={},
    )
    assert build_context_headers_interceptor(config) is None


def test_disabled_block_returns_none():
    config = _config(headers={"X-Tenant-Token": "tenant_token"}, enabled=False)
    assert build_context_headers_interceptor(config) is None


def test_empty_mapping_returns_none():
    """An enabled block with no mappings has nothing to inject."""
    assert build_context_headers_interceptor(_config(headers={})) is None


def test_disabled_server_is_ignored():
    config = _config(headers={"X-Tenant-Token": "tenant_token"})
    config.mcp_servers["shared-http"].enabled = False
    assert build_context_headers_interceptor(config) is None


def test_stdio_server_is_skipped_with_warning(caplog):
    """A stdio server has no HTTP headers; warn and skip rather than deny its calls."""
    config = ExtensionsConfig(
        mcp_servers={
            "local": McpServerConfig(
                enabled=True,
                type="stdio",
                command="npx",
                headers_from_context=McpContextHeadersConfig(headers={"X-Tenant-Token": "tenant_token"}),
            )
        },
        skills={},
    )
    with caplog.at_level(logging.WARNING, logger="deerflow.mcp.context_headers"):
        assert build_context_headers_interceptor(config) is None
    assert "stdio" in caplog.text


# ---------------------------------------------------------------------------
# Header injection
# ---------------------------------------------------------------------------


def test_request_secret_is_injected_as_header():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    result = asyncio.run(interceptor(_request(runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN)), _echo_handler))
    assert result.headers["X-Tenant-Token"] == TENANT_TOKEN


def test_static_headers_are_preserved():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    request = _request(headers={"Accept": "application/json"}, runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result.headers == {"Accept": "application/json", "X-Tenant-Token": TENANT_TOKEN}


def test_context_mapping_overrides_a_static_header():
    """The per-request credential must win over the discovery credential."""
    interceptor = build_context_headers_interceptor(_config(headers={"Authorization": "tenant_token"}))
    request = _request(headers={"Authorization": "Bearer discovery-token"}, runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result.headers["Authorization"] == TENANT_TOKEN


def test_multiple_headers_are_mapped():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Id": "tenant_id", "X-Org": "org"}))
    runtime = _runtime_with_secrets(tenant_id="acme", org="engineering")
    result = asyncio.run(interceptor(_request(runtime=runtime), _echo_handler))
    assert result.headers == {"X-Tenant-Id": "acme", "X-Org": "engineering"}


def test_request_headers_are_not_mutated_in_place():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    original = {"Accept": "application/json"}
    asyncio.run(interceptor(_request(headers=original, runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN)), _echo_handler))
    assert original == {"Accept": "application/json"}


def test_other_server_passes_through_untouched():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    request = _request(server_name="other", headers={"Authorization": "Bearer static"}, runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result is request


def test_falls_back_to_ambient_runtime_when_request_runtime_is_missing():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    with patch(
        "deerflow.mcp.context_headers._current_runtime",
        return_value=_runtime_with_secrets(tenant_token=TENANT_TOKEN),
    ):
        result = asyncio.run(interceptor(_request(runtime=None), _echo_handler))
    assert result.headers["X-Tenant-Token"] == TENANT_TOKEN


# ---------------------------------------------------------------------------
# Header-name casing
#
# HTTP field names are case-insensitive, but every dict on the path to the wire
# is case-sensitive — including the adapter's ``{**connection_headers,
# **override_headers}`` merge. A mapped name spelled differently from the static
# one would therefore travel *alongside* it rather than replacing it, and a
# server reading the field with a single-value accessor would see the static
# discovery credential first.
# ---------------------------------------------------------------------------


def _config_with_static_headers(static: dict[str, str], **context_headers_kwargs) -> ExtensionsConfig:
    config = _config(**context_headers_kwargs)
    config.mcp_servers["shared-http"].headers = static
    return config


def test_mapped_name_is_emitted_in_the_servers_static_spelling():
    config = _config_with_static_headers({"authorization": "Bearer discovery-token"}, headers={"Authorization": "tenant_token"})
    interceptor = build_context_headers_interceptor(config)
    result = asyncio.run(interceptor(_request(runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN)), _echo_handler))
    assert result.headers == {"authorization": TENANT_TOKEN}


def test_mapped_name_replaces_a_differently_cased_header_from_an_earlier_interceptor():
    """OAuth and user_auth write before this interceptor; their value must not survive.

    The surviving spelling is whichever one is already on the request, so the
    write lands on the existing field rather than adding a second one.
    """
    config = _config_with_static_headers({}, headers={"authorization": "tenant_token"})
    interceptor = build_context_headers_interceptor(config)
    request = _request(headers={"Authorization": "Bearer per-user"}, runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert list(result.headers.values()) == [TENANT_TOKEN]


def test_unrelated_headers_keep_their_own_spelling():
    config = _config_with_static_headers({"Authorization": "Bearer discovery-token"}, headers={"X-Tenant-Token": "tenant_token"})
    interceptor = build_context_headers_interceptor(config)
    request = _request(headers={"Accept": "application/json"}, runtime=_runtime_with_secrets(tenant_token=TENANT_TOKEN))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result.headers == {"Accept": "application/json", "X-Tenant-Token": TENANT_TOKEN}


def _connection_headers_for_adapter_call(config: ExtensionsConfig) -> dict[str, str]:
    """Return the headers the adapter would open the remote session with.

    Goes through the real connection merge rather than seeding static headers
    onto ``request.headers``: the adapter builds the request with
    ``headers=None``, so an interceptor never sees the connection's static
    headers and the collision can only be observed here.
    """
    from langchain_core.messages import AIMessage
    from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode
    from mcp.types import CallToolResult, TextContent
    from mcp.types import Tool as MCPTool

    from deerflow.mcp.client import build_server_params

    opened: dict[str, str] = {}

    class _Session:
        async def initialize(self) -> None:
            return None

        async def call_tool(self, *_args, **_kwargs):
            return CallToolResult(content=[TextContent(type="text", text="done")], isError=False)

    class _SessionContext:
        def __init__(self, connection, **_kwargs):
            opened.update(connection.get("headers") or {})

        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *_exc):
            return False

    tool = convert_mcp_tool_to_langchain_tool(
        None,
        MCPTool(name="act", description="act", inputSchema={"type": "object", "properties": {}}),
        connection=build_server_params("shared-http", config.mcp_servers["shared-http"]),
        server_name="shared-http",
        tool_interceptors=build_mcp_tool_interceptors(config, oauth_builder=lambda _cfg: None),
    )

    builder = StateGraph(_AgentState, context_schema=dict)
    builder.add_node("tools", ToolNode([tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()

    with patch("langchain_mcp_adapters.tools.create_session", _SessionContext):
        asyncio.run(
            graph.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"name": "act", "args": {}, "id": "call_1", "type": "tool_call"}])]},
                context={"secrets": {"tenant_token": TENANT_TOKEN}, "thread_id": "th-1"},
            )
        )
    return opened


def test_connection_carries_one_authorization_header_despite_a_casing_mismatch():
    """The reviewed failure: two spellings both reach httpx, static one first."""
    config = _config_with_static_headers({"authorization": "Bearer discovery-token"}, headers={"Authorization": "tenant_token"})
    opened = _connection_headers_for_adapter_call(config)
    assert [name for name in opened if name.lower() == "authorization"] == ["authorization"]
    assert opened["authorization"] == TENANT_TOKEN


def test_connection_keeps_static_headers_the_mapping_does_not_touch():
    config = _config_with_static_headers({"Authorization": "Bearer discovery-token", "X-Api-Version": "2"}, headers={"X-Tenant-Token": "tenant_token"})
    opened = _connection_headers_for_adapter_call(config)
    assert opened == {"Authorization": "Bearer discovery-token", "X-Api-Version": "2", "X-Tenant-Token": TENANT_TOKEN}


def test_mapping_the_same_header_under_two_spellings_is_rejected():
    with pytest.raises(ValueError, match="two spellings"):
        McpContextHeadersConfig(headers={"Authorization": "tenant_token", "authorization": "other_token"})


def test_gateway_rejects_the_same_header_under_two_spellings():
    from pydantic import ValidationError

    from app.gateway.routers.mcp import McpContextHeadersConfigResponse

    with pytest.raises(ValidationError, match="two spellings"):
        McpContextHeadersConfigResponse(headers={"Authorization": "tenant_token", "AUTHORIZATION": "other_token"})


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_missing_secret_denies_without_calling_handler():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    handler = AsyncMock()
    with pytest.raises(ToolException, match="tenant_token"):
        asyncio.run(interceptor(_request(runtime=_runtime_with_secrets(unrelated="x")), handler))
    handler.assert_not_awaited()


def test_empty_secret_value_is_denied():
    """An unset $ENV_VAR on the caller side arrives as "" and must fail closed."""
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    with pytest.raises(ToolException):
        asyncio.run(interceptor(_request(runtime=_runtime_with_secrets(tenant_token="")), AsyncMock()))


def test_absent_run_context_is_denied():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    with patch("deerflow.mcp.context_headers._current_runtime", return_value=None), pytest.raises(ToolException):
        asyncio.run(interceptor(_request(runtime=None), AsyncMock()))


def test_deny_message_does_not_leak_other_secret_values():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"}))
    runtime = _runtime_with_secrets(other_secret="super-secret-value")
    with pytest.raises(ToolException) as excinfo:
        asyncio.run(interceptor(_request(runtime=runtime), AsyncMock()))
    assert "super-secret-value" not in str(excinfo.value)


def test_on_missing_passthrough_keeps_static_headers():
    interceptor = build_context_headers_interceptor(_config(headers={"Authorization": "tenant_token"}, on_missing="passthrough"))
    request = _request(headers={"Authorization": "Bearer discovery-token"}, runtime=_runtime_with_secrets())
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result.headers["Authorization"] == "Bearer discovery-token"


def test_passthrough_still_injects_the_secrets_that_are_present():
    interceptor = build_context_headers_interceptor(_config(headers={"X-Tenant-Id": "tenant_id", "X-Org": "org"}, on_missing="passthrough"))
    result = asyncio.run(interceptor(_request(runtime=_runtime_with_secrets(tenant_id="acme")), _echo_handler))
    assert result.headers == {"X-Tenant-Id": "acme"}


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


def test_blank_header_name_is_rejected():
    with pytest.raises(ValueError, match="header name"):
        McpContextHeadersConfig(headers={"  ": "tenant_token"})


def test_blank_secret_key_is_rejected():
    with pytest.raises(ValueError, match="secret key"):
        McpContextHeadersConfig(headers={"X-Tenant-Token": ""})


def test_config_round_trips_from_file(tmp_path):
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        """
        {
          "mcpServers": {
            "shared-http": {
              "enabled": true,
              "transport": "http",
              "url": "https://mcp.example.com/mcp",
              "headers_from_context": {"headers": {"X-Tenant-Token": "tenant_token"}}
            }
          }
        }
        """
    )
    config = ExtensionsConfig.from_file(str(config_file))
    block = config.mcp_servers["shared-http"].headers_from_context
    assert block is not None
    assert block.enabled is True
    assert block.on_missing == "deny"
    assert block.headers == {"X-Tenant-Token": "tenant_token"}


def test_mapping_values_are_not_env_resolved(tmp_path, monkeypatch):
    """The right-hand side names a run-context key, not an environment variable."""
    monkeypatch.setenv("tenant_token", "must-not-be-substituted")
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        """
        {
          "mcpServers": {
            "shared-http": {
              "enabled": true,
              "transport": "http",
              "url": "https://mcp.example.com/mcp",
              "headers_from_context": {"headers": {"X-Tenant-Token": "tenant_token"}}
            }
          }
        }
        """
    )
    config = ExtensionsConfig.from_file(str(config_file))
    assert config.mcp_servers["shared-http"].headers_from_context.headers == {"X-Tenant-Token": "tenant_token"}


# ---------------------------------------------------------------------------
# Interceptor chain assembly
# ---------------------------------------------------------------------------


def test_registered_last_so_request_secrets_win():
    """Later interceptors run closer to the transport, so per-request values win."""
    config = _config(headers={"Authorization": "tenant_token"})
    config.mcp_servers["shared-http"].user_auth = McpUserScopedAuthConfig(users={"u1": "Bearer per-user"})

    async def oauth(request, handler):  # pragma: no cover - identity only
        return await handler(request)

    interceptors = build_mcp_tool_interceptors(config, oauth_builder=lambda _cfg: oauth)
    assert [getattr(i, "__name__", type(i).__name__) for i in interceptors] == [
        "oauth",
        "user_scoped_auth_interceptor",
        "context_headers_interceptor",
    ]


def test_shared_assembly_skips_when_not_configured():
    config = ExtensionsConfig(
        mcp_servers={"plain": McpServerConfig(enabled=True, type="http", url="https://x.example.com")},
        skills={},
    )
    assert build_mcp_tool_interceptors(config, oauth_builder=lambda _cfg: None) == []


# ---------------------------------------------------------------------------
# End-to-end contract with LangGraph + langchain-mcp-adapters
# ---------------------------------------------------------------------------


def _run_adapter_tool_in_graph(*, isolate_request_runtime: bool = False) -> dict[str, Any]:
    """Drive a real adapter tool through a real graph; return the headers it sent.

    DeerFlow does not wrap HTTP/SSE MCP tools, so the tool under test here is the
    one ``langchain_mcp_adapters`` builds, invoked by LangGraph's own tool node.

    With *isolate_request_runtime* the ambient-runtime fallback is disabled, so
    the secrets can only arrive through the runtime LangGraph injected into the
    adapter tool's ``runtime`` parameter.
    """
    from langchain_core.messages import AIMessage
    from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode
    from mcp.types import CallToolResult, TextContent
    from mcp.types import Tool as MCPTool

    seen_headers: dict[str, Any] = {}

    class _FakeSession:
        async def call_tool(self, name, args, **kwargs):
            return CallToolResult(content=[TextContent(type="text", text="done")], isError=False)

    async def _capture_headers(request, handler):
        seen_headers.update(request.headers or {})
        return await handler(request)

    tool = convert_mcp_tool_to_langchain_tool(
        _FakeSession(),
        MCPTool(name="act", description="act", inputSchema={"type": "object", "properties": {}}),
        server_name="shared-http",
        tool_interceptors=[
            build_context_headers_interceptor(_config(headers={"X-Tenant-Token": "tenant_token"})),
            _capture_headers,
        ],
    )

    builder = StateGraph(_AgentState, context_schema=dict)
    builder.add_node("tools", ToolNode([tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()

    def _invoke() -> None:
        asyncio.run(
            graph.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"name": "act", "args": {}, "id": "call_1", "type": "tool_call"}])]},
                context={"secrets": {"tenant_token": TENANT_TOKEN}, "thread_id": "th-1"},
            )
        )

    if isolate_request_runtime:
        with patch("deerflow.mcp.context_headers._current_runtime", return_value=None):
            _invoke()
    else:
        _invoke()
    return seen_headers


def test_request_secret_reaches_a_real_adapter_tool_call():
    """The user-facing contract: a per-request secret lands on the outgoing call."""
    assert _run_adapter_tool_in_graph().get("X-Tenant-Token") == TENANT_TOKEN


def test_adapter_tool_receives_the_runtime_langgraph_injects():
    """Pin the injection rule the HTTP/SSE path depends on.

    ``langchain_mcp_adapters`` names its tool parameter ``runtime``, and
    LangGraph's tool node injects a ``ToolRuntime`` into any parameter with that
    name. With the ambient-runtime fallback disabled, that channel is the only
    way the secrets can arrive — so an upstream rename or a change to the
    injection rule fails here instead of silently dropping every header.
    """
    assert _run_adapter_tool_in_graph(isolate_request_runtime=True).get("X-Tenant-Token") == TENANT_TOKEN


# ---------------------------------------------------------------------------
# Durable background tasks
# ---------------------------------------------------------------------------


def _task_config() -> ExtensionsConfig:
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "http",
                    "url": "https://reports.example.com/mcp",
                    "headers": {"Authorization": "Bearer discovery-token"},
                    "headers_from_context": {"headers": {"Authorization": "tenant_token"}},
                    "task_toolsets": [{"name": "reports", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                }
            }
        }
    )


def _task_caller(config: ExtensionsConfig) -> tuple[Any, dict[str, str], Any]:
    """Build a task caller whose remote session records the headers it opened with."""
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    opened: dict[str, str] = {}
    result = SimpleNamespace(structuredContent={"task_id": "remote-1", "status": "running"}, isError=False)

    class _SessionContext:
        def __init__(self, connection, **_kwargs):
            opened.clear()
            opened.update(connection.get("headers") or {})

        async def __aenter__(self):
            return SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value=result))

        async def __aexit__(self, *_exc):
            return False

    caller = McpTaskToolCaller(
        config,
        oauth_token_manager=SimpleNamespace(has_oauth_servers=lambda: False, get_authorization_header=AsyncMock(return_value=None)),
    )
    return caller, opened, _SessionContext


_DRIVER_DATA = {"submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}


def test_durable_submit_carries_the_request_scoped_headers():
    """Submit is awaited inside the Agent run, so it can — and must — carry them.

    Driven through a real tool node with no ambient-runtime patching: the run
    context reaches the driver through the contextvar LangGraph sets around the
    tool coroutine, several awaits below it.
    """
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool as make_tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.mcp.tasks import TaskSubmitRequest
    from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver

    caller, opened, session_context = _task_caller(_task_config())
    driver = OrdinaryMcpTaskDriver(caller)

    @make_tool
    async def submit_report() -> str:
        """Submit a durable report task."""
        await driver.submit(
            TaskSubmitRequest(
                user_id="user-1",
                thread_id="thread-1",
                run_id=None,
                tool_call_id=None,
                server_name="reports",
                task_name="reports",
                arguments={},
                driver_data=dict(_DRIVER_DATA),
            )
        )
        return "submitted"

    builder = StateGraph(_AgentState, context_schema=dict)
    builder.add_node("tools", ToolNode([submit_report]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()

    with patch("langchain_mcp_adapters.sessions.create_session", session_context):
        asyncio.run(
            graph.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"name": "submit_report", "args": {}, "id": "call_1", "type": "tool_call"}])]},
                context={"secrets": {"tenant_token": TENANT_TOKEN}, "thread_id": "thread-1"},
            )
        )

    assert opened == {"Authorization": TENANT_TOKEN}


@pytest.mark.asyncio
async def test_durable_status_poll_keeps_the_server_credential():
    """The poller runs after the Agent run ended: no run context, no deny."""
    from deerflow.mcp.tasks.models import TaskReference
    from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver

    caller, opened, session_context = _task_caller(_task_config())
    driver = OrdinaryMcpTaskDriver(caller)

    with patch("langchain_mcp_adapters.sessions.create_session", session_context):
        snapshot = await driver.get_status(
            TaskReference(
                local_task_id="local-1",
                user_id="user-1",
                thread_id="thread-1",
                server_name="reports",
                remote_task_id="remote-1",
                driver_data=dict(_DRIVER_DATA),
            )
        )

    assert snapshot is not None
    assert opened == {"Authorization": "Bearer discovery-token"}


def test_declaring_both_request_headers_and_task_toolsets_warns(caplog):
    """Background polls run outside the Agent run that carried the secrets."""
    config = _config(headers={"X-Tenant-Token": "tenant_token"})
    config.mcp_servers["shared-http"].task_toolsets = [McpTaskToolsetConfig(name="reports", submit_tool="submit", status_tool="status", cancel_tool="cancel")]
    with caplog.at_level(logging.WARNING, logger="deerflow.mcp.context_headers"):
        assert build_context_headers_interceptor(config) is not None
    assert "task_toolsets" in caplog.text


@pytest.mark.asyncio
async def test_durable_task_calls_are_not_denied_for_a_missing_run_context():
    """The task runtime must keep polling on server-level auth, not fail closed."""
    from unittest.mock import MagicMock

    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "http",
                    "url": "https://reports.example.com/mcp",
                    "headers": {"X-Static": "configured"},
                    "headers_from_context": {"headers": {"X-Tenant-Token": "tenant_token"}},
                }
            }
        }
    )
    result = SimpleNamespace(structuredContent={"task_id": "remote-1", "status": "running"}, isError=False)
    session = SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value=result))

    class _SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_exc):
            return False

    caller = McpTaskToolCaller(
        config,
        oauth_token_manager=SimpleNamespace(has_oauth_servers=lambda: False, get_authorization_header=AsyncMock(return_value=None)),
    )

    with patch("langchain_mcp_adapters.sessions.create_session", MagicMock(return_value=_SessionContext())):
        actual = await caller.call_tool(
            server_name="reports",
            tool_name="status",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    assert actual is result


# ---------------------------------------------------------------------------
# Gateway API surface
# ---------------------------------------------------------------------------


def test_gateway_exposes_mapping_without_masking():
    """The block holds header names and run-context key names, never a credential."""
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _mask_server_config,
    )

    server = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}),
    )
    masked = _mask_server_config(server)
    assert masked.headers_from_context.headers == {"X-Tenant-Token": "tenant_token"}


def test_gateway_masks_sensitive_extras_inside_the_block():
    """``extra="allow"`` means an operator can still store a secret-bearing key here."""
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _mask_server_config,
    )

    server = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}, api_key="real-secret"),
    )
    masked = _mask_server_config(server)
    assert masked.headers_from_context.model_extra["api_key"] == "***"
    assert masked.headers_from_context.headers == {"X-Tenant-Token": "tenant_token"}


def test_gateway_merge_preserves_block_when_field_omitted():
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}),
    )
    incoming = McpServerConfigResponse(type="http", url="https://mcp.example.com/mcp")
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.headers_from_context is not None
    assert merged.headers_from_context.headers == {"X-Tenant-Token": "tenant_token"}


def test_gateway_put_can_replace_the_mapping():
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Org": "org"}, on_missing="passthrough"),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.headers_from_context.headers == {"X-Org": "org"}
    assert merged.headers_from_context.on_missing == "passthrough"


def test_gateway_partial_block_preserves_stored_mapping_and_policy():
    """A partial headers_from_context PUT must not wipe omitted declared fields."""
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(
            headers={"X-Tenant-Token": "tenant_token"},
            on_missing="passthrough",
        ),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(enabled=False),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.headers_from_context is not None
    assert merged.headers_from_context.enabled is False
    assert merged.headers_from_context.headers == {"X-Tenant-Token": "tenant_token"}
    assert merged.headers_from_context.on_missing == "passthrough"


def test_gateway_partial_block_explicit_empty_mapping_still_clears():
    """An explicitly supplied empty mapping must clear the stored mapping, not preserve it."""
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(
            headers={"X-Tenant-Token": "tenant_token"},
            on_missing="passthrough",
        ),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={}),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.headers_from_context is not None
    assert merged.headers_from_context.headers == {}
    assert merged.headers_from_context.on_missing == "passthrough"


def test_gateway_round_trip_restores_masked_extras_inside_the_block():
    """GET masks the block's extras, so PUT must swap the sentinel back."""
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _mask_server_config,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}, api_key="real-secret", note="kept"),
    )
    merged = _merge_preserving_secrets(_mask_server_config(existing), existing)
    assert merged.headers_from_context.model_extra["api_key"] == "real-secret"
    assert merged.headers_from_context.model_extra["note"] == "kept"


def test_gateway_keeps_block_extras_a_put_does_not_mention():
    """Matches how user_auth and server-level extras survive a partial PUT."""
    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}, vendor_note="keep-me"),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Org": "org"}),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.headers_from_context.headers == {"X-Org": "org"}
    assert merged.headers_from_context.model_extra["vendor_note"] == "keep-me"


def test_gateway_rejects_a_masked_value_for_an_unknown_block_extra():
    """A sentinel with nothing stored behind it must not be written to disk."""
    from fastapi import HTTPException

    from app.gateway.routers.mcp import (
        McpContextHeadersConfigResponse,
        McpServerConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        headers_from_context=McpContextHeadersConfigResponse(headers={"X-Tenant-Token": "tenant_token"}, api_key="***"),
    )
    with pytest.raises(HTTPException):
        _merge_preserving_secrets(incoming, existing)

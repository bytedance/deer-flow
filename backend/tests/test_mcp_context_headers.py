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

"""Regression tests for request-scoped MCP credential header validation."""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from deerflow.config.extensions_config import ExtensionsConfig, McpContextHeadersConfig, McpServerConfig
from deerflow.mcp.context_headers import _is_safe_header_value, build_context_headers_interceptor


def _config() -> ExtensionsConfig:
    return ExtensionsConfig(
        mcp_servers={
            "shared-http": McpServerConfig(
                enabled=True,
                type="http",
                url="https://mcp.example.com/mcp",
                headers_from_context=McpContextHeadersConfig(headers={"Authorization": "tenant_token"}),
            )
        },
        skills={},
    )


def _request(secret: str) -> MCPToolCallRequest:
    runtime = SimpleNamespace(context={"secrets": {"tenant_token": secret}, "thread_id": "th-1"})
    return MCPToolCallRequest(name="act", args={}, server_name="shared-http", headers=None, runtime=runtime)


async def _echo_handler(request: MCPToolCallRequest) -> MCPToolCallRequest:
    return request


@pytest.mark.parametrize(
    "value",
    [
        "Bearer secret\n",
        "Bearer secret\r",
        "Bearer secret\x00",
        " Bearer secret",
        "Bearer secret ",
        "Bearer secret\tvalue",
        "Bearer secret-€",
    ],
)
def test_unsafe_header_values_are_rejected(value: str):
    assert _is_safe_header_value(value) is False


def test_normal_credential_header_value_is_allowed():
    assert _is_safe_header_value("Bearer tenant-scoped-token") is True


def test_invalid_secret_fails_closed_without_echoing_value():
    secret = "Bearer sk-tenant-secret-abc123\n"
    interceptor = build_context_headers_interceptor(_config())

    with pytest.raises(ToolException) as exc_info:
        asyncio.run(interceptor(_request(secret), _echo_handler))

    message = str(exc_info.value)
    assert "tenant_token" in message
    assert secret not in message
    assert "sk-tenant-secret-abc123" not in message

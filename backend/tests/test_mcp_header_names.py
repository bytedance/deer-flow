"""Tests for case-insensitive header writes shared by the MCP interceptors.

HTTP field names are case-insensitive, but the dicts carrying them are not: a
static ``authorization`` and an injected ``Authorization`` are two keys, both
reach httpx, and a server reading the field with a single-value accessor gets
the *static* one — the credential the injection was meant to replace.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from pydantic import ValidationError

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, McpUserScopedAuthConfig
from deerflow.mcp.headers import apply_header_overrides, header_spellings
from deerflow.mcp.oauth import build_oauth_tool_interceptor
from deerflow.mcp.user_scoped_auth import build_user_scoped_auth_interceptor

DISCOVERY = "Bearer discovery-token"


def _request(headers: dict | None = None, runtime: object | None = None, server_name: str = "shared-http") -> MCPToolCallRequest:
    return MCPToolCallRequest(name="act", args={}, server_name=server_name, headers=headers, runtime=runtime)


async def _echo_handler(request: MCPToolCallRequest) -> MCPToolCallRequest:
    return request


# ---------------------------------------------------------------------------
# apply_header_overrides
# ---------------------------------------------------------------------------


def test_override_replaces_a_differently_cased_key():
    assert apply_header_overrides({"Authorization": DISCOVERY}, {"authorization": "Bearer new"}) == {"Authorization": "Bearer new"}


def test_override_prefers_the_connection_spelling():
    """The emitted name must match the connection's, since the adapter merges by key."""
    merged = apply_header_overrides(
        {"Authorization": "Bearer from-an-earlier-interceptor"},
        {"AUTHORIZATION": "Bearer new"},
        spellings=header_spellings(["authorization"]),
    )
    assert merged == {"authorization": "Bearer new"}


def test_override_keeps_unrelated_headers():
    merged = apply_header_overrides({"Accept": "application/json"}, {"X-Tenant-Id": "acme"})
    assert merged == {"Accept": "application/json", "X-Tenant-Id": "acme"}


def test_override_accepts_no_base():
    assert apply_header_overrides(None, {"X-Tenant-Id": "acme"}) == {"X-Tenant-Id": "acme"}


def test_override_does_not_mutate_the_base():
    base = {"Authorization": DISCOVERY}
    apply_header_overrides(base, {"authorization": "Bearer new"})
    assert base == {"Authorization": DISCOVERY}


# ---------------------------------------------------------------------------
# Static header spelling validation
# ---------------------------------------------------------------------------


def test_static_headers_reject_case_insensitive_duplicates():
    """Two spellings of one header in the static map must be rejected at config time."""
    with pytest.raises(ValueError, match="two spellings"):
        McpServerConfig(
            type="http",
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer a", "authorization": "Bearer b"},
        )


def test_static_headers_allow_distinct_names():
    config = McpServerConfig(
        type="http",
        url="https://mcp.example.com/mcp",
        headers={"X-Tenant": "acme", "X-Org": "engineering"},
    )
    assert config.headers == {"X-Tenant": "acme", "X-Org": "engineering"}


def test_extensions_config_rejects_static_header_duplicates():
    with pytest.raises(ValidationError, match="two spellings"):
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "shared-http": {
                        "type": "http",
                        "url": "https://mcp.example.com/mcp",
                        "headers": {"Authorization": "Bearer a", "authorization": "Bearer b"},
                    }
                }
            }
        )


def test_gateway_rejects_static_header_case_insensitive_duplicates():
    from app.gateway.routers.mcp import McpServerConfigResponse

    with pytest.raises(ValidationError, match="two spellings"):
        McpServerConfigResponse(headers={"Authorization": "Bearer a", "AUTHORIZATION": "Bearer b"})


# ---------------------------------------------------------------------------
# The credential interceptors
# ---------------------------------------------------------------------------


def _server(**overrides) -> ExtensionsConfig:
    return ExtensionsConfig(
        mcp_servers={
            "shared-http": McpServerConfig(
                enabled=True,
                type="http",
                url="https://mcp.example.com/mcp",
                headers={"authorization": DISCOVERY},
                **overrides,
            )
        },
        skills={},
    )


def test_user_auth_credential_replaces_a_differently_cased_static_header():
    config = _server(user_auth=McpUserScopedAuthConfig(header="Authorization", users={"u1": "Bearer per-user"}))
    interceptor = build_user_scoped_auth_interceptor(config)
    runtime = SimpleNamespace(server_info=None, context={"user_id": "u1"})
    result = asyncio.run(interceptor(_request(runtime=runtime), _echo_handler))
    assert result.headers == {"authorization": "Bearer per-user"}


def test_oauth_token_replaces_a_differently_cased_static_header():
    config = _server(
        oauth={
            "enabled": True,
            "token_url": "https://auth.example.com/oauth/token",
            "client_id": "id",
            "client_secret": "secret",
        }
    )
    token_manager = SimpleNamespace(
        has_oauth_servers=lambda: True,
        get_authorization_header=AsyncMock(return_value="Bearer oauth-token"),
    )
    interceptor = build_oauth_tool_interceptor(config, token_manager=token_manager)
    result = asyncio.run(interceptor(_request(), _echo_handler))
    assert result.headers == {"authorization": "Bearer oauth-token"}


@pytest.mark.asyncio
async def test_durable_task_call_sends_one_authorization_header():
    """The task caller merges OAuth and interceptor headers into the connection itself."""
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "http",
                    "url": "https://reports.example.com/mcp",
                    "headers": {"authorization": DISCOVERY},
                }
            }
        }
    )
    opened: dict[str, str] = {}
    result = SimpleNamespace(structuredContent={"task_id": "remote-1", "status": "running"}, isError=False)

    class _SessionContext:
        def __init__(self, connection, **_kwargs):
            opened.update(connection.get("headers") or {})

        async def __aenter__(self):
            return SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value=result))

        async def __aexit__(self, *_exc):
            return False

    caller = McpTaskToolCaller(
        config,
        oauth_token_manager=SimpleNamespace(has_oauth_servers=lambda: False, get_authorization_header=AsyncMock(return_value="Bearer oauth-token")),
    )

    with patch("langchain_mcp_adapters.sessions.create_session", _SessionContext):
        await caller.call_tool(
            server_name="reports",
            tool_name="status",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    assert opened == {"authorization": "Bearer oauth-token"}

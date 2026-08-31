"""Tests for per-user credential injection on shared MCP servers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    McpServerConfig,
    McpUserScopedAuthConfig,
)
from deerflow.mcp.interceptors import build_mcp_tool_interceptors
from deerflow.mcp.user_scoped_auth import build_user_scoped_auth_interceptor


def _config(**user_auth_kwargs) -> ExtensionsConfig:
    return ExtensionsConfig(
        mcp_servers={
            "shared-http": McpServerConfig(
                enabled=True,
                type="http",
                url="https://mcp.example.com/mcp",
                headers={"Authorization": "Bearer discovery-token"},
                user_auth=McpUserScopedAuthConfig(**user_auth_kwargs),
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


def _runtime_for_user(user_id: str) -> object:
    return SimpleNamespace(server_info=None, context={"user_id": user_id})


async def _echo_handler(request: MCPToolCallRequest) -> MCPToolCallRequest:
    return request


def test_no_user_auth_servers_returns_none():
    config = ExtensionsConfig(
        mcp_servers={"plain": McpServerConfig(enabled=True, type="http", url="https://x.example.com")},
        skills={},
    )
    assert build_user_scoped_auth_interceptor(config) is None


def test_disabled_user_auth_returns_none():
    config = _config(users={"u1": "Bearer t1"}, enabled=False)
    assert build_user_scoped_auth_interceptor(config) is None


def test_disabled_server_is_ignored():
    config = _config(users={"u1": "Bearer t1"})
    config.mcp_servers["shared-http"].enabled = False
    assert build_user_scoped_auth_interceptor(config) is None


def test_mapped_user_gets_own_credential():
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1", "u2": "Bearer t2"}))
    result = asyncio.run(interceptor(_request(headers={"Authorization": "Bearer discovery-token"}, runtime=_runtime_for_user("u2")), _echo_handler))
    assert result.headers["Authorization"] == "Bearer t2"


def test_custom_header_and_other_headers_preserved():
    interceptor = build_user_scoped_auth_interceptor(_config(header="X-Api-Key", users={"u1": "k1"}))
    result = asyncio.run(interceptor(_request(headers={"Accept": "application/json"}, runtime=_runtime_for_user("u1")), _echo_handler))
    assert result.headers == {"Accept": "application/json", "X-Api-Key": "k1"}


def test_other_server_passes_through_untouched():
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1"}))
    request = _request(server_name="other", headers={"Authorization": "Bearer static"}, runtime=_runtime_for_user("u1"))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result is request


def test_unmapped_user_denied_without_calling_handler():
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1"}))
    handler = AsyncMock()
    with pytest.raises(ToolException, match="No credential is configured"):
        asyncio.run(interceptor(_request(runtime=_runtime_for_user("stranger")), handler))
    handler.assert_not_awaited()


def test_empty_resolved_credential_is_denied():
    """An unset $ENV_VAR reference resolves to "" and must fail closed."""
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": ""}))
    with pytest.raises(ToolException, match="No credential is configured"):
        asyncio.run(interceptor(_request(runtime=_runtime_for_user("u1")), AsyncMock()))


def test_on_missing_passthrough_keeps_static_headers():
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1"}, on_missing="passthrough"))
    request = _request(headers={"Authorization": "Bearer discovery-token"}, runtime=_runtime_for_user("stranger"))
    result = asyncio.run(interceptor(request, _echo_handler))
    assert result.headers["Authorization"] == "Bearer discovery-token"


def test_default_user_fallback_is_denied_when_unmapped():
    """Without any resolvable identity the DEFAULT_USER_ID fallback must not inherit a credential."""
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1"}))
    with patch("deerflow.mcp.user_scoped_auth._current_runtime", return_value=None), pytest.raises(ToolException):
        asyncio.run(interceptor(_request(runtime=None), AsyncMock()))


def test_credential_with_trailing_newline_is_denied_without_leaking_it():
    """A credential that cannot travel as a header value (docker env-file with
    CRLF line endings, `$ENV_VAR` set from a token file) must be rejected here:
    h11 renders the full value into its LocalProtocolError message, which
    ToolErrorHandlingMiddleware then copies into a model-visible ToolMessage."""
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer sk-secret-value\n"}))
    handler = AsyncMock()
    with pytest.raises(ToolException) as excinfo:
        asyncio.run(interceptor(_request(runtime=_runtime_for_user("u1")), handler))
    handler.assert_not_awaited()
    assert "sk-secret-value" not in str(excinfo.value)
    assert "u1" in str(excinfo.value)


def test_credential_with_carriage_return_is_denied_even_with_passthrough():
    """passthrough covers an *unmapped user*; a mapped-but-broken credential
    must not silently fall back to the shared discovery credential."""
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1\r"}, on_missing="passthrough"))
    with pytest.raises(ToolException):
        asyncio.run(interceptor(_request(runtime=_runtime_for_user("u1")), AsyncMock()))


def test_credential_with_embedded_space_is_not_rejected():
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1"}))
    result = asyncio.run(interceptor(_request(runtime=_runtime_for_user("u1")), _echo_handler))
    assert result.headers["Authorization"] == "Bearer t1"


def test_env_var_reference_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_USER_CRED", "Bearer from-env")
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        """
        {
          "mcpServers": {
            "shared-http": {
              "enabled": true,
              "type": "http",
              "url": "https://mcp.example.com/mcp",
              "user_auth": {"users": {"u1": "$TEST_USER_CRED", "u2": "$TEST_USER_CRED_UNSET"}}
            }
          }
        }
        """
    )
    config = ExtensionsConfig.from_file(str(config_file))
    user_auth = config.mcp_servers["shared-http"].user_auth
    assert user_auth.users["u1"] == "Bearer from-env"
    assert user_auth.users["u2"] == ""


def test_registered_after_oauth_in_shared_assembly():
    config = _config(users={"u1": "Bearer t1"})

    async def oauth(request, handler):  # pragma: no cover - identity only
        return await handler(request)

    interceptors = build_mcp_tool_interceptors(config, oauth_builder=lambda _cfg: oauth)
    assert len(interceptors) == 2
    assert interceptors[0] is oauth
    assert interceptors[1].__name__ == "user_scoped_auth_interceptor"


def test_shared_assembly_skips_when_no_user_auth():
    config = ExtensionsConfig(
        mcp_servers={"plain": McpServerConfig(enabled=True, type="http", url="https://x.example.com")},
        skills={},
    )
    interceptors = build_mcp_tool_interceptors(config, oauth_builder=lambda _cfg: None)
    assert interceptors == []


def test_gateway_masks_user_auth_credentials():
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _mask_server_config,
    )

    server = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "Bearer real-secret"}),
    )
    masked = _mask_server_config(server)
    assert masked.user_auth.users == {"u1": "***"}
    assert masked.user_auth.header == "Authorization"


def test_gateway_merge_preserves_masked_user_auth_values():
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "Bearer real-secret"}),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "***", "u2": "Bearer new-secret"}),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.user_auth.users == {"u1": "Bearer real-secret", "u2": "Bearer new-secret"}


def test_gateway_merge_rejects_masked_value_for_new_user():
    from fastapi import HTTPException

    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(type="http", url="https://mcp.example.com/mcp")
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"new-user": "***"}),
    )
    with pytest.raises(HTTPException):
        _merge_preserving_secrets(incoming, existing)


def test_gateway_merge_preserves_user_auth_when_field_omitted():
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "Bearer real-secret"}),
    )
    incoming = McpServerConfigResponse(type="http", url="https://mcp.example.com/mcp")
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.user_auth is not None
    assert merged.user_auth.users == {"u1": "Bearer real-secret"}


def test_partial_user_auth_put_preserves_stored_subfields():
    """A payload like {"enabled": false} must not wipe users or reset on_missing."""
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "Bearer real-secret"}, on_missing="passthrough", header="X-Api-Key"),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(enabled=False),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.user_auth.enabled is False
    assert merged.user_auth.users == {"u1": "Bearer real-secret"}
    assert merged.user_auth.on_missing == "passthrough"
    assert merged.user_auth.header == "X-Api-Key"


def test_explicit_users_map_still_replaces_and_can_remove():
    """An explicitly sent map replaces the stored one, so removal via full round-trip works."""
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _merge_preserving_secrets,
    )

    existing = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "Bearer s1", "u2": "Bearer s2"}),
    )
    incoming = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "***"}),
    )
    merged = _merge_preserving_secrets(incoming, existing)
    assert merged.user_auth.users == {"u1": "Bearer s1"}  # u2 removed, u1 preserved through mask


def test_user_auth_extra_keys_survive_parse_mask_and_merge():
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _mask_server_config,
        _merge_preserving_secrets,
    )

    ua = McpUserScopedAuthConfigResponse(**{"users": {"u1": "Bearer s"}, "custom_note": "keep-me"})
    assert (ua.model_extra or {}).get("custom_note") == "keep-me"
    server = McpServerConfigResponse(type="http", url="https://x", user_auth=ua)
    masked = _mask_server_config(server)
    assert (masked.user_auth.model_extra or {}).get("custom_note") == "keep-me"
    merged = _merge_preserving_secrets(
        McpServerConfigResponse(type="http", url="https://x", user_auth=McpUserScopedAuthConfigResponse(enabled=False)),
        server,
    )
    assert (merged.user_auth.model_extra or {}).get("custom_note") == "keep-me"


def test_stdio_server_user_auth_is_skipped_with_warning(caplog):
    import logging

    config = ExtensionsConfig(
        mcp_servers={
            "local-stdio": McpServerConfig(
                enabled=True,
                type="stdio",
                command="npx",
                args=["-y", "some-server"],
                user_auth=McpUserScopedAuthConfig(users={"u1": "Bearer t1"}),
            ),
        },
        skills={},
    )
    with caplog.at_level(logging.WARNING, logger="deerflow.mcp.user_scoped_auth"):
        interceptor = build_user_scoped_auth_interceptor(config)
    assert interceptor is None  # no eligible servers -> nothing registered, no deny errors
    assert any("user_auth" in r.message and "stdio" in r.message for r in caplog.records)


def test_gateway_rejects_blank_user_auth_header():
    """A blank header must be rejected at the gateway, not persisted and left to
    wedge extensions_config.json on reload (harness-side validator would raise)."""
    import pydantic
    import pytest

    from app.gateway.routers.mcp import McpUserScopedAuthConfigResponse

    for blank in ("", "   ", "\t"):
        with pytest.raises(pydantic.ValidationError, match="must not be empty"):
            McpUserScopedAuthConfigResponse(header=blank)
    # Non-blank still fine, and default untouched.
    assert McpUserScopedAuthConfigResponse(header="X-Api-Key").header == "X-Api-Key"
    assert McpUserScopedAuthConfigResponse().header == "Authorization"


def test_deny_error_includes_the_callers_resolved_user_id():
    """The users key format differs by deployment path; the fail-closed error
    must show the caller's own resolved id so the operator can copy the exact key."""
    interceptor = build_user_scoped_auth_interceptor(_config(users={"u1": "Bearer t1"}))
    with pytest.raises(ToolException, match="user id 'stranger-uuid'"):
        asyncio.run(interceptor(_request(runtime=_runtime_for_user("stranger-uuid")), AsyncMock()))


def test_user_credential_wins_over_oauth_set_header_through_real_composition():
    """Pin the wrap-order property functionally, not just list order: an OAuth
    interceptor that actually sets Authorization must lose the final header to
    the per-user credential, through the same composition the session-pool
    tool path uses."""
    from deerflow.mcp.interceptors import compose_tool_interceptors

    config = _config(users={"u1": "Bearer user-cred"})

    async def oauth(request, handler):
        headers = dict(request.headers or {})
        headers["Authorization"] = "Bearer oauth-token"
        return await handler(request.override(headers=headers))

    interceptors = build_mcp_tool_interceptors(config, oauth_builder=lambda _cfg: oauth)
    handler = compose_tool_interceptors(interceptors, _echo_handler)
    final = asyncio.run(handler(_request(runtime=_runtime_for_user("u1"))))
    assert final.headers["Authorization"] == "Bearer user-cred"
    # And on a server without user_auth the OAuth header must survive untouched.
    final_other = asyncio.run(handler(_request(server_name="other", runtime=_runtime_for_user("u1"))))
    assert final_other.headers["Authorization"] == "Bearer oauth-token"


def test_gateway_masks_sensitive_user_auth_extra_keys():
    """Secret-bearing extras inside user_auth must be masked by GET like the
    identical keys at server level, and a masked round-trip must preserve them."""
    from app.gateway.routers.mcp import (
        McpServerConfigResponse,
        McpUserScopedAuthConfigResponse,
        _mask_server_config,
        _merge_preserving_secrets,
    )

    server = McpServerConfigResponse(
        type="http",
        url="https://mcp.example.com/mcp",
        user_auth=McpUserScopedAuthConfigResponse(users={"u1": "Bearer s1"}, client_secret="super-secret", custom_note="keep-me"),
    )
    masked = _mask_server_config(server)
    assert masked.user_auth.model_extra["client_secret"] == "***"
    assert masked.user_auth.model_extra["custom_note"] == "keep-me"

    # Round-trip: PUT of the masked GET payload keeps the stored secret.
    merged = _merge_preserving_secrets(masked, server)
    assert merged.user_auth.model_extra["client_secret"] == "super-secret"
    assert merged.user_auth.users == {"u1": "Bearer s1"}

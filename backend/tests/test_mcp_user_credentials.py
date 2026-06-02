"""Regression tests for per-user MCP credential isolation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import ExtensionsConfig, McpOAuthConfig
from deerflow.mcp.credentials import (
    InMemoryMcpUserCredentialStore,
    push_mcp_credential_store,
    reset_mcp_credential_store,
    reset_mcp_credential_store_context,
)
from deerflow.mcp.oauth import OAuthTokenManager
from deerflow.mcp.session_pool import get_session_pool, reset_session_pool
from deerflow.mcp.tools import _make_session_pool_tool, build_user_headers_tool_interceptor
from deerflow.runtime.user_context import reset_current_user, set_current_user


class _Args(BaseModel):
    query: str = Field(..., description="query")


def _runtime(user_id: str, thread_id: str = "shared-thread") -> SimpleNamespace:
    return SimpleNamespace(
        context={"user_id": user_id, "thread_id": thread_id},
        config={},
    )


class _Request:
    def __init__(self, server_name: str, runtime, headers: dict[str, str] | None = None):
        self.server_name = server_name
        self.runtime = runtime
        self.headers = headers or {}

    def override(self, **kwargs):
        return _Request(
            self.server_name,
            self.runtime,
            headers=kwargs.get("headers", self.headers),
        )


@pytest.fixture(autouse=True)
def _reset_mcp_state():
    reset_session_pool()
    reset_mcp_credential_store()
    yield
    reset_session_pool()
    reset_mcp_credential_store()


@pytest.mark.asyncio
async def test_stdio_session_pool_scopes_by_user_and_uses_user_env():
    store = InMemoryMcpUserCredentialStore()
    await store.upsert(
        "user-a",
        "github",
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "token-a"},
    )
    await store.upsert(
        "user-b",
        "github",
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "token-b"},
    )
    token = push_mcp_credential_store(store)
    try:
        original_tool = StructuredTool(
            name="github_search",
            description="Search",
            args_schema=_Args,
            coroutine=AsyncMock(),
            response_format="content_and_artifact",
        )

        sessions = [AsyncMock(), AsyncMock()]
        for session in sessions:
            session.call_tool = AsyncMock(
                return_value=MagicMock(content=[], isError=False, structuredContent=None)
            )

        class _CM:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        cms = [_CM(sessions[0]), _CM(sessions[1])]

        extensions_config = ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "github": {
                        "enabled": True,
                        "type": "stdio",
                        "command": "github-mcp-server",
                        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "global-token"},
                    }
                }
            }
        )
        connection = {
            "transport": "stdio",
            "command": "github-mcp-server",
            "args": [],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "global-token"},
        }

        with patch("langchain_mcp_adapters.sessions.create_session", side_effect=cms) as create_session:
            wrapped = _make_session_pool_tool(
                original_tool,
                "github",
                connection,
                extensions_config,
            )

            await wrapped.coroutine(runtime=_runtime("user-a"), query="repos for user a")
            await wrapped.coroutine(runtime=_runtime("user-b"), query="repos for user b")

        assert create_session.call_count == 2
        assert create_session.call_args_list[0].args[0]["env"] == {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "token-a"
        }
        assert create_session.call_args_list[1].args[0]["env"] == {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "token-b"
        }
        pool_keys = set(get_session_pool()._entries)
        assert ("github", "user-a:shared-thread:v1") in pool_keys
        assert ("github", "user-b:shared-thread:v1") in pool_keys
    finally:
        reset_mcp_credential_store_context(token)


@pytest.mark.asyncio
async def test_user_headers_interceptor_injects_current_users_headers():
    store = InMemoryMcpUserCredentialStore()
    await store.upsert("user-a", "secure-http", headers={"Authorization": "Bearer user-a"})
    await store.upsert("user-b", "secure-http", headers={"Authorization": "Bearer user-b"})
    token = push_mcp_credential_store(store)
    try:
        config = ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "secure-http": {
                        "enabled": True,
                        "type": "http",
                        "url": "https://api.example.com/mcp",
                        "headers": {"Authorization": "Bearer global"},
                    }
                }
            }
        )
        interceptor = build_user_headers_tool_interceptor(config)
        assert interceptor is not None

        captured: list[dict[str, str]] = []

        async def handler(request):
            captured.append(request.headers)
            return "ok"

        await interceptor(_Request("secure-http", _runtime("user-a")), handler)
        await interceptor(_Request("secure-http", _runtime("user-b")), handler)

        assert captured == [
            {"Authorization": "Bearer user-a"},
            {"Authorization": "Bearer user-b"},
        ]
    finally:
        reset_mcp_credential_store_context(token)


class _MockResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _MockAsyncClient:
    def __init__(self, post_calls, **kwargs):
        self._post_calls = post_calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, data):
        self._post_calls.append({"url": url, "data": data})
        return _MockResponse(
            {
                "access_token": f"token-{len(self._post_calls)}",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )


def test_oauth_token_cache_is_scoped_by_user_and_credential_version(monkeypatch):
    post_calls = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(post_calls=post_calls, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    manager = OAuthTokenManager({"secure-http": McpOAuthConfig(
        enabled=True,
        token_url="https://auth.example.com/oauth/token",
        grant_type="client_credentials",
        client_id="global-client",
        client_secret="global-secret",
    )})

    from deerflow.mcp.credentials import McpUserCredentials

    first = asyncio.run(
        manager.get_authorization_header(
            "secure-http",
            user_id="user-a",
            credentials=McpUserCredentials(
                user_id="user-a",
                server_name="secure-http",
                oauth=McpOAuthConfig(
                    enabled=True,
                    token_url="https://auth.example.com/oauth/token",
                    grant_type="client_credentials",
                    client_id="client-a",
                    client_secret="secret-a",
                ),
                version=1,
            ),
        )
    )
    second = asyncio.run(
        manager.get_authorization_header(
            "secure-http",
            user_id="user-b",
            credentials=McpUserCredentials(
                user_id="user-b",
                server_name="secure-http",
                oauth=McpOAuthConfig(
                    enabled=True,
                    token_url="https://auth.example.com/oauth/token",
                    grant_type="client_credentials",
                    client_id="client-b",
                    client_secret="secret-b",
                ),
                version=1,
            ),
        )
    )
    refreshed = asyncio.run(
        manager.get_authorization_header(
            "secure-http",
            user_id="user-a",
            credentials=McpUserCredentials(
                user_id="user-a",
                server_name="secure-http",
                oauth=McpOAuthConfig(
                    enabled=True,
                    token_url="https://auth.example.com/oauth/token",
                    grant_type="client_credentials",
                    client_id="client-a",
                    client_secret="secret-a-new",
                ),
                version=2,
            ),
        )
    )

    assert first == "Bearer token-1"
    assert second == "Bearer token-2"
    assert refreshed == "Bearer token-3"
    assert [call["data"]["client_id"] for call in post_calls] == [
        "client-a",
        "client-b",
        "client-a",
    ]


def test_contextvar_user_still_isolates_oauth_cache(monkeypatch):
    post_calls = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(post_calls=post_calls, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    manager = OAuthTokenManager({"secure-http": McpOAuthConfig(
        enabled=True,
        token_url="https://auth.example.com/oauth/token",
        grant_type="client_credentials",
        client_id="global-client",
        client_secret="global-secret",
    )})

    token_a = set_current_user(SimpleNamespace(id="user-a"))
    try:
        first = asyncio.run(manager.get_authorization_header("secure-http", user_id="user-a"))
    finally:
        reset_current_user(token_a)

    token_b = set_current_user(SimpleNamespace(id="user-b"))
    try:
        second = asyncio.run(manager.get_authorization_header("secure-http", user_id="user-b"))
    finally:
        reset_current_user(token_b)

    assert first == "Bearer token-1"
    assert second == "Bearer token-2"
    assert len(post_calls) == 2


def test_initial_oauth_headers_use_user_credentials_for_discovery(monkeypatch):
    from deerflow.mcp.oauth import get_initial_oauth_headers

    post_calls = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(post_calls=post_calls, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    store = InMemoryMcpUserCredentialStore()
    asyncio.run(
        store.upsert(
            "user-a",
            "secure-http",
            oauth=McpOAuthConfig(
                enabled=True,
                token_url="https://auth.example.com/oauth/token",
                grant_type="client_credentials",
                client_id="client-a",
                client_secret="secret-a",
            ),
        )
    )
    token = push_mcp_credential_store(store)
    try:
        config = ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "secure-http": {
                        "enabled": True,
                        "type": "http",
                        "url": "https://api.example.com/mcp",
                        "oauth": {
                            "enabled": True,
                            "token_url": "https://auth.example.com/oauth/token",
                            "grant_type": "client_credentials",
                            "client_id": "global-client",
                            "client_secret": "global-secret",
                        },
                    }
                }
            }
        )

        headers = asyncio.run(get_initial_oauth_headers(config, user_id="user-a"))

        assert headers == {"secure-http": "Bearer token-1"}
        assert post_calls[0]["data"]["client_id"] == "client-a"
    finally:
        reset_mcp_credential_store_context(token)


def test_build_servers_config_uses_user_credentials_for_discovery_connections():
    from deerflow.mcp.client import build_servers_config

    store = InMemoryMcpUserCredentialStore()
    asyncio.run(
        store.upsert(
            "user-a",
            "github",
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "token-a"},
        )
    )
    asyncio.run(
        store.upsert(
            "user-b",
            "github",
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "token-b"},
        )
    )
    asyncio.run(
        store.upsert(
            "user-a",
            "secure-http",
            headers={"Authorization": "Bearer user-a"},
        )
    )
    asyncio.run(
        store.upsert(
            "user-b",
            "secure-http",
            headers={"Authorization": "Bearer user-b"},
        )
    )
    token = push_mcp_credential_store(store)
    try:
        config = ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "github": {
                        "enabled": True,
                        "type": "stdio",
                        "command": "github-mcp-server",
                        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "global-token"},
                    },
                    "secure-http": {
                        "enabled": True,
                        "type": "http",
                        "url": "https://api.example.com/mcp",
                        "headers": {"Authorization": "Bearer global"},
                    },
                }
            }
        )

        user_a = build_servers_config(config, user_id="user-a")
        user_b = build_servers_config(config, user_id="user-b")

        assert user_a["github"]["env"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "token-a"}
        assert user_b["github"]["env"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "token-b"}
        assert user_a["secure-http"]["headers"] == {"Authorization": "Bearer user-a"}
        assert user_b["secure-http"]["headers"] == {"Authorization": "Bearer user-b"}
    finally:
        reset_mcp_credential_store_context(token)


@pytest.mark.asyncio
async def test_mcp_credentials_api_masks_preserves_secrets_and_isolates_users():
    from app.gateway.routers.mcp import (
        McpOAuthConfigResponse,
        McpUserCredentialsUpdateRequest,
        delete_mcp_user_credentials,
        get_mcp_user_credentials,
        list_mcp_user_credentials,
        update_mcp_user_credentials,
    )
    from deerflow.config.extensions_config import reset_extensions_config, set_extensions_config

    store = InMemoryMcpUserCredentialStore()
    set_extensions_config(
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "github": {
                        "enabled": True,
                        "type": "stdio",
                        "command": "github-mcp-server",
                    }
                }
            }
        )
    )

    user_a_token = set_current_user(SimpleNamespace(id="user-a"))
    try:
        created = await update_mcp_user_credentials(
            "github",
            McpUserCredentialsUpdateRequest(
                env={"GITHUB_TOKEN": "token-a"},
                headers={"Authorization": "Bearer a"},
                oauth=McpOAuthConfigResponse(
                    token_url="https://auth.example.com/token",
                    client_id="client-a",
                    client_secret="secret-a",
                    refresh_token="refresh-a",
                ),
            ),
            store=store,
        )
        assert created.env == {"GITHUB_TOKEN": "***"}
        assert created.headers == {"Authorization": "***"}
        assert created.oauth is not None
        assert created.oauth.client_secret is None
        assert created.oauth.refresh_token is None

        roundtrip = await update_mcp_user_credentials(
            "github",
            McpUserCredentialsUpdateRequest(
                env={"GITHUB_TOKEN": "***"},
                headers={"Authorization": "***"},
                oauth=McpOAuthConfigResponse(
                    token_url="https://auth.example.com/token",
                    client_id="client-a",
                    client_secret=None,
                    refresh_token=None,
                ),
            ),
            store=store,
        )
        assert roundtrip.version == 2

        stored = await store.get("user-a", "github")
        assert stored is not None
        assert stored.env == {"GITHUB_TOKEN": "token-a"}
        assert stored.headers == {"Authorization": "Bearer a"}
        assert stored.oauth is not None
        assert stored.oauth.client_secret == "secret-a"
        assert stored.oauth.refresh_token == "refresh-a"

        listed = await list_mcp_user_credentials(store=store)
        assert list(listed.credentials) == ["github"]
        fetched = await get_mcp_user_credentials("github", store=store)
        assert fetched.env == {"GITHUB_TOKEN": "***"}
    finally:
        reset_current_user(user_a_token)

    user_b_token = set_current_user(SimpleNamespace(id="user-b"))
    try:
        listed = await list_mcp_user_credentials(store=store)
        assert listed.credentials == {}
        await update_mcp_user_credentials(
            "github",
            McpUserCredentialsUpdateRequest(env={"GITHUB_TOKEN": "token-b"}),
            store=store,
        )
        assert (await store.get("user-a", "github")).env == {"GITHUB_TOKEN": "token-a"}  # type: ignore[union-attr]
        assert (await store.get("user-b", "github")).env == {"GITHUB_TOKEN": "token-b"}  # type: ignore[union-attr]
        assert await delete_mcp_user_credentials("github", store=store) == {"deleted": True}
        assert await store.get("user-b", "github") is None
        assert await store.get("user-a", "github") is not None
    finally:
        reset_current_user(user_b_token)
        reset_extensions_config()


@pytest.mark.asyncio
async def test_sql_mcp_user_credential_store_round_trips_and_versions(tmp_path):
    from deerflow.mcp.credentials import SQLMcpUserCredentialStore
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await close_engine()
    try:
        db_path = tmp_path / "deerflow.db"
        await init_engine(
            "sqlite",
            url=f"sqlite+aiosqlite:///{db_path}",
            sqlite_dir=str(tmp_path),
        )
        sf = get_session_factory()
        assert sf is not None
        store = SQLMcpUserCredentialStore(sf)

        first = await store.upsert(
            "user-a",
            "github",
            env={"GITHUB_TOKEN": "token-a"},
            oauth=McpOAuthConfig(
                enabled=True,
                token_url="https://auth.example.com/token",
                client_id="client-a",
                client_secret="secret-a",
            ),
        )
        second = await store.upsert(
            "user-a",
            "github",
            env={"GITHUB_TOKEN": "token-a2"},
        )

        loaded = await store.get("user-a", "github")
        assert first.version == 1
        assert second.version == 2
        assert loaded is not None
        assert loaded.env == {"GITHUB_TOKEN": "token-a2"}
        assert loaded.oauth is None
        assert [entry.server_name for entry in await store.list_for_user("user-a")] == ["github"]
        assert await store.delete("user-a", "github") is True
        assert await store.get("user-a", "github") is None
    finally:
        await close_engine()

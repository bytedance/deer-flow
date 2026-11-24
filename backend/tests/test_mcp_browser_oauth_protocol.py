"""Exercise the split protocol over HTTPX's transport boundary, without live credentials."""

import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from deerflow.config.extensions_config import McpServerConfig
from deerflow.mcp import browser_oauth as oauth


@pytest.fixture
def server():
    return McpServerConfig.model_validate(
        {
            "type": "http",
            "url": "https://observability.example/mcp",
            "user_oauth": {"client_id": "monitor", "issuer": "https://login.example", "redirect_uri": "https://gateway.example/api/mcp/user-oauth/callback", "scope": "logs:read"},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("pkce", [True, False])
async def test_metadata_challenge_and_preregistered_client(monkeypatch, server, pkce):
    from base64 import urlsafe_b64encode
    from unittest.mock import Mock

    seen = []
    issuer = server.user_oauth.issuer
    resource = server.url

    def responder(request):
        seen.append(request.url.path)
        if request.url.path == "/mcp":
            return httpx.Response(401, headers={"www-authenticate": 'Bearer resource_metadata="https://observability.example/mcp-metadata", scope="logs:read"'})
        if request.url.path == "/mcp-metadata":
            return httpx.Response(200, json={"resource": resource, "authorization_servers": [issuer]})
        assert request.url.path == "/.well-known/oauth-authorization-server"
        return httpx.Response(200, json={"issuer": issuer, "authorization_endpoint": issuer + "/authorize", "token_endpoint": issuer + "/token", "code_challenge_methods_supported": ["S256"] if pkce else []})

    store = Mock()
    monkeypatch.setattr(oauth, "_transport", lambda *_a, **_kw: httpx.MockTransport(responder))
    monkeypatch.setattr(oauth, "resolve_public_addresses", lambda *a, **k: ["192.0.2.1"])
    monkeypatch.setattr(oauth, "_store", lambda: store)
    if pkce:
        url = await oauth.begin_connection("logs", server, "alice", "browser-binding", "transaction-state")
        query = parse_qs(urlsplit(url).query)
        _, data = store.begin_delegated.call_args
        challenge = urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).decode().rstrip("=")
        assert query["resource"] == [resource] and query["client_id"] == ["monitor"] and query["scope"] == ["logs:read"]
        assert query["state"] == ["transaction-state"] and query["code_challenge"] == [challenge] and query["code_challenge_method"] == ["S256"]
    else:
        with pytest.raises(oauth.BrowserOAuthError, match="S256"):
            await oauth.begin_connection("logs", server, "alice", "browser-binding", "transaction-state")
        store.begin_delegated.assert_not_called()
    assert seen == ["/mcp", "/mcp-metadata", "/.well-known/oauth-authorization-server"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body", "expected"), [(400, {"error": "invalid_grant"}, oauth._InvalidGrant), (503, {}, oauth.BrowserOAuthError), (302, {}, oauth.BrowserOAuthError)])
async def test_token_errors_and_redirects_have_distinct_local_outcomes(monkeypatch, server, status, body, expected):
    from deerflow.mcp.oauth_store import DelegatedOAuthContext

    ctx = DelegatedOAuthContext(server.user_oauth.issuer, server.url, "https://login.example/token")
    called = []

    def responder(request):
        called.append(request.url.path)
        assert parse_qs(request.content.decode())["resource"] == [server.url]
        return httpx.Response(status, json=body, headers={"Location": "https://login.example/other"})

    monkeypatch.setattr(oauth, "_transport", lambda *_a, **_kw: httpx.MockTransport(responder))
    with pytest.raises(oauth.BrowserOAuthError) as exc:
        await oauth._exchange(server, ctx, {"grant_type": "refresh_token", "refresh_token": "example-token"})
    assert type(exc.value) is expected
    assert called == ["/token"]


@pytest.mark.asyncio
async def test_transport_does_not_connect_to_unregistered_destination(server):
    async with oauth.mcp_client_factory(server)() as client:
        with pytest.raises(oauth.BrowserOAuthError, match="configured MCP connection"):
            await client.get("https://other.example/mcp")


@pytest.mark.asyncio
async def test_access_only_grant_survives_until_expired_or_rejected(server, tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from cryptography.fernet import Fernet
    from langchain_core.tools import ToolException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.mcp import oauth_store
    from deerflow.persistence.base import Base
    from deerflow.persistence.mcp_oauth_tokens import McpOAuthAttemptRow, McpOAuthTokenRow, SqlMcpOAuthTokenRepository

    engine = create_engine("sqlite:///" + str(tmp_path / "grants.db"))
    try:
        Base.metadata.create_all(engine, tables=[McpOAuthTokenRow.__table__, McpOAuthAttemptRow.__table__])
        store = oauth_store.McpOAuthTokenStore(SqlMcpOAuthTokenRepository(sessionmaker(engine)), cipher=CredentialsCipher.from_keys([Fernet.generate_key()]))
        monkeypatch.setattr(oauth_store, "get_mcp_oauth_token_store", lambda: store)
        context = oauth_store.DelegatedOAuthContext(server.user_oauth.issuer, server.url, "https://login.example/token")
        for user, duration, reject in [("alice", 120, True), ("bob", -1, False)]:
            key = oauth_store.McpOAuthTokenKey.for_delegated("logs", user)
            epoch = store.begin_delegated(key, fingerprint=oauth.browser_grant_fingerprint(server), state=user, browser_binding=user, code_verifier="opaque", context=context)
            attempt = store.consume_delegated(user, owner_user_id=user, browser_binding=user)
            assert store.complete_delegated(attempt, access_token=user, expires_at=datetime.now(UTC) + timedelta(seconds=duration))
            if reject:
                assert await oauth.get_call_token("logs", server, user) == (user, epoch)
            with pytest.raises(ToolException, match="Capability Center"):
                await oauth.get_call_token("logs", server, user, rejected_token=user if reject else None)
            assert oauth.connection_state("logs", server, user) == "reconnect_required"
    finally:
        engine.dispose()


def test_registered_callback_only_allows_exact_route_and_https_or_loopback(server):
    from pydantic import ValidationError

    from deerflow.config.extensions_config import MCP_USER_OAUTH_CALLBACK_PATH, McpUserOAuthConfig

    entry = server.user_oauth.model_dump()
    for origin in ("http://localhost:8001", "http://127.0.0.1:8001", "http://[::1]:8001", "https://gateway.example"):
        assert McpUserOAuthConfig(**{**entry, "redirect_uri": origin + MCP_USER_OAUTH_CALLBACK_PATH}).redirect_uri == origin + MCP_USER_OAUTH_CALLBACK_PATH
    for bad in (
        "http://other.example" + MCP_USER_OAUTH_CALLBACK_PATH,
        "https://gateway.example/elsewhere",
        "https://user@gateway.example" + MCP_USER_OAUTH_CALLBACK_PATH,
        "https://gateway.example" + MCP_USER_OAUTH_CALLBACK_PATH + "?code=old",
    ):
        with pytest.raises(ValidationError):
            McpUserOAuthConfig(**{**entry, "redirect_uri": bad})

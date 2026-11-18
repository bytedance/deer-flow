"""Regression anchor: MCP OAuth refreshes through the shared token store must not block the event loop.

``OAuthTokenManager.get_authorization_header`` runs on whichever loop calls the
tool. With the Gateway's ``McpOAuthTokenStore`` installed, a refresh reads the
connection's ``mcp_oauth_tokens`` row, claims the refresh lease, encrypts and
writes the new tokens -- all synchronous SQL plus Fernet -- and a process
waiting on a peer's lease polls the row. Every one of those calls goes through
``asyncio.to_thread``; if one regresses onto the loop, the strict Blockbuster
gate raises ``BlockingError`` and these tests fail.

Database setup and inspection are offloaded with ``asyncio.to_thread``; the
token endpoint is an in-memory ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

from deerflow.config.credentials_key import CredentialsCipher
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp import oauth_store
from deerflow.mcp.oauth import OAuthTokenManager
from deerflow.mcp.oauth_store import McpOAuthTokenKey, McpOAuthTokenStore, oauth_config_fingerprint
from deerflow.persistence.base import Base
from deerflow.persistence.mcp_oauth_tokens import McpOAuthTokenRow, SqlMcpOAuthTokenRepository

pytestmark = pytest.mark.asyncio

CONFIG = ExtensionsConfig.model_validate(
    {
        "mcpServers": {
            "reports": {
                "type": "http",
                "url": "https://mcp.example.invalid/mcp",
                "oauth": {"token_url": "https://auth.example.invalid/token", "grant_type": "refresh_token", "refresh_token": "refresh-0"},
            }
        }
    }
)


@pytest.fixture
def token_endpoint(monkeypatch):
    issued: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        issued.append(parse_qs(request.content.decode())["refresh_token"][0])
        return httpx.Response(200, json={"access_token": f"access-{len(issued)}", "refresh_token": f"refresh-{len(issued)}", "expires_in": 3600})

    original_client = httpx.AsyncClient

    class OfflineClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", OfflineClient)
    return issued


def _session_factory(path) -> sessionmaker:
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine, tables=[McpOAuthTokenRow.__table__])
    return sessionmaker(engine, expire_on_commit=False)


def _store(session_factory) -> McpOAuthTokenStore:
    return McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=CredentialsCipher.from_keys([Fernet.generate_key()]))


async def test_refresh_and_adoption_through_the_store_do_not_block_the_event_loop(tmp_path, token_endpoint) -> None:
    session_factory = await asyncio.to_thread(_session_factory, tmp_path / "oauth.db")
    store = _store(session_factory)

    first = OAuthTokenManager.from_extensions_config(CONFIG, token_store=store)
    assert await first.get_authorization_header("reports") == "Bearer access-1"
    # A second process adopts the stored token without a refresh.
    second = OAuthTokenManager.from_extensions_config(CONFIG, token_store=store)
    assert await second.get_authorization_header("reports") == "Bearer access-1"
    assert token_endpoint == ["refresh-0"]


async def test_waiting_on_a_peer_lease_does_not_block_the_event_loop(tmp_path, token_endpoint, monkeypatch) -> None:
    monkeypatch.setattr(oauth_store, "REFRESH_LEASE_SECONDS", 0.3)
    session_factory = await asyncio.to_thread(_session_factory, tmp_path / "oauth.db")
    store = _store(session_factory)
    key = McpOAuthTokenKey.for_server("reports", None)
    # A peer claimed the refresh and never finished it.
    assert await asyncio.to_thread(store.claim, key, fingerprint=oauth_config_fingerprint(CONFIG.mcp_servers["reports"].oauth), expected_version=None)

    manager = OAuthTokenManager.from_extensions_config(CONFIG, token_store=store)
    assert await manager.get_authorization_header("reports") == "Bearer access-1"
    assert token_endpoint == ["refresh-0"]

"""MCP OAuth tokens shared through ``mcp_oauth_tokens`` (restarts and Gateway replicas).

A ``refresh_token`` connection's access token and rotated refresh token live in
one encrypted row per connection. Every manager below stands for a separate
Gateway process: its own ``McpOAuthTokenStore`` and in-process token state over
one shared database. The token endpoint rotates on every refresh and rejects a
consumed refresh token with ``invalid_grant``, like Auth0/Okta/Google, so any
replica or restart that falls back to an already-used seed fails loudly.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from deerflow.config.credentials_key import CredentialsCipher
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp import oauth_store
from deerflow.mcp.oauth import McpOAuthReauthorizationRequired, OAuthTokenManager
from deerflow.mcp.oauth_store import (
    McpOAuthTokenStore,
    McpOAuthTokenStoreUnavailable,
    StoredTokenLookup,
    oauth_config_fingerprint,
    oauth_token_request_fingerprint,
    set_mcp_oauth_token_store,
)
from deerflow.persistence.base import Base
from deerflow.persistence.mcp_oauth_tokens import McpOAuthTokenRow, SqlMcpOAuthTokenRepository
from deerflow.persistence.postgres_schema import dsn_with_search_path

SERVER = "reports"
REQUEST = "r" * 64


class _Clock:
    current = datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, _tz):
        return cls.current


class _RotatingTokenEndpoint:
    """Issue ``access-N``/``refresh-N`` and accept only the latest refresh token."""

    def __init__(self) -> None:
        self.refresh_token = "refresh-0"
        self.generation = 0
        self.refresh_requests: list[str] = []
        self.forms: list[dict[str, list[str]]] = []
        self.fail_with: int | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/token"
        form = parse_qs(request.content.decode())
        submitted = form["refresh_token"][0]
        self.refresh_requests.append(submitted)
        self.forms.append(form)
        if self.fail_with is not None:
            return httpx.Response(self.fail_with, json={"error": "server_error"})
        if submitted != self.refresh_token:
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.generation += 1
        self.refresh_token = f"refresh-{self.generation}"
        return httpx.Response(200, json={"access_token": f"access-{self.generation}", "refresh_token": self.refresh_token, "expires_in": 120})


@pytest.fixture
def endpoint(monkeypatch):
    server = _RotatingTokenEndpoint()
    original_client = httpx.AsyncClient

    class OfflineClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(lambda request: server.handle(request))
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", OfflineClient)
    monkeypatch.setattr("deerflow.mcp.oauth.datetime", _Clock)
    monkeypatch.setattr(_Clock, "current", datetime(2026, 1, 1, tzinfo=UTC))
    return server


@pytest.fixture(autouse=True)
def _no_installed_store():
    previous = set_mcp_oauth_token_store(None)
    yield
    set_mcp_oauth_token_store(previous)


@pytest.fixture(params=["sqlite", "postgres"])
def session_factory(request, tmp_path) -> sessionmaker[Session]:
    """The synchronous session factory the Gateway builds from ``app_sync_sqlalchemy_url``, on each dialect."""
    schema = None
    if request.param == "sqlite":
        engine = sa.create_engine(f"sqlite:///{(tmp_path / 'oauth.db').as_posix()}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres mcp_oauth_tokens)")
        schema = f"mcp_oauth_tokens_{uuid.uuid4().hex}"
        admin = sa.create_engine(make_url(uri).set(drivername="postgresql+psycopg"))
        with admin.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        admin.dispose()
        engine = sa.create_engine(make_url(dsn_with_search_path(uri, schema)).set(drivername="postgresql+psycopg"))
    Base.metadata.create_all(engine, tables=[McpOAuthTokenRow.__table__])
    yield sessionmaker(engine, expire_on_commit=False)
    if schema is not None:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


@pytest.fixture
def cipher() -> CredentialsCipher:
    return CredentialsCipher.from_keys([Fernet.generate_key()])


def _config(*, seed: str = "refresh-0", grant_type: str = "refresh_token", name: str = SERVER, token_url: str = "https://auth.example.invalid/token", extra_token_params: dict[str, str] | None = None) -> ExtensionsConfig:
    oauth = {"token_url": token_url, "grant_type": grant_type, "refresh_skew_seconds": 0, "extra_token_params": extra_token_params or {}}
    if grant_type == "refresh_token":
        oauth["refresh_token"] = seed
    else:
        oauth.update(client_id="client", client_secret="secret")
    return ExtensionsConfig.model_validate({"mcpServers": {name: {"type": "http", "url": "https://mcp.example.invalid/mcp", "oauth": oauth}}})


def _replica(session_factory, cipher, config: ExtensionsConfig | None = None, *, owner_user_id: str | None = None) -> OAuthTokenManager:
    """One Gateway process: a fresh store and fresh in-process token state over the shared database."""
    store = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher)
    return OAuthTokenManager.from_extensions_config(config or _config(), owner_user_id=owner_user_id, token_store=store)


def _rows(session_factory) -> list[McpOAuthTokenRow]:
    with session_factory() as session:
        return list(session.scalars(sa.select(McpOAuthTokenRow).order_by(McpOAuthTokenRow.scope, McpOAuthTokenRow.owner_user_id, McpOAuthTokenRow.server_key)))


def _expire_access_tokens() -> None:
    _Clock.current = _Clock.current + timedelta(seconds=300)


@pytest.mark.asyncio
async def test_peer_uses_the_rotated_refresh_token_without_calling_the_token_endpoint(session_factory, cipher, endpoint):
    a = _replica(session_factory, cipher)
    b = _replica(session_factory, cipher)

    assert await a.get_authorization_header(SERVER) == "Bearer access-1"
    # B has never refreshed, but A's still-valid access token is in the row.
    assert await b.get_authorization_header(SERVER) == "Bearer access-1"
    assert endpoint.refresh_requests == ["refresh-0"]

    _expire_access_tokens()
    # B refreshes with A's rotated token, not the consumed seed ...
    assert await b.get_authorization_header(SERVER) == "Bearer access-2"
    # ... and A adopts B's result instead of refreshing with its stale copy.
    assert await a.get_authorization_header(SERVER) == "Bearer access-2"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]


@pytest.mark.asyncio
async def test_restart_does_not_reseed_from_the_consumed_seed(session_factory, cipher, endpoint):
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-1"
    _expire_access_tokens()

    restarted = _replica(session_factory, cipher)

    assert await restarted.get_authorization_header(SERVER) == "Bearer access-2"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]


@pytest.mark.asyncio
async def test_changed_seed_wins_over_the_stored_rotation(session_factory, cipher, endpoint):
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-1"
    # The operator revokes the chain and configures a new seed.
    endpoint.refresh_token = "replacement-seed"
    changed = _config(seed="replacement-seed")

    assert await _replica(session_factory, cipher, changed).get_authorization_header(SERVER) == "Bearer access-2"
    _expire_access_tokens()
    # The new chain is what the next process continues from.
    assert await _replica(session_factory, cipher, changed).get_authorization_header(SERVER) == "Bearer access-3"
    assert endpoint.refresh_requests == ["refresh-0", "replacement-seed", "refresh-2"]
    (row,) = _rows(session_factory)
    assert row.config_fingerprint == oauth_config_fingerprint(changed.mcp_servers[SERVER].oauth)


def test_concurrent_refresh_across_replicas_makes_one_token_request(session_factory, cipher, endpoint, monkeypatch):
    a = _replica(session_factory, cipher)
    b = _replica(session_factory, cipher)
    a_fetching = threading.Event()
    b_waiting = threading.Event()
    release = threading.Event()
    handle = endpoint.handle

    async def held(request):
        a_fetching.set()
        assert await asyncio.to_thread(release.wait, 10), "test did not release the token response"
        return handle(request)

    monkeypatch.setattr(endpoint, "handle", held)
    b_store = b._token_store
    original_claim = b_store.claim

    def observed_claim(*args, **kwargs):
        claimed = original_claim(*args, **kwargs)
        if claimed is None:
            b_waiting.set()
        return claimed

    monkeypatch.setattr(b_store, "claim", observed_claim)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(lambda: asyncio.run(a.get_authorization_header(SERVER)))
        try:
            assert a_fetching.wait(10), "replica A never reached the token endpoint"
            second = executor.submit(lambda: asyncio.run(b.get_authorization_header(SERVER)))
            assert b_waiting.wait(10), "replica B did not find A's refresh lease"
        finally:
            release.set()
        assert first.result(timeout=10) == "Bearer access-1"
        assert second.result(timeout=10) == "Bearer access-1"
    assert endpoint.refresh_requests == ["refresh-0"]


@pytest.mark.asyncio
async def test_tokens_are_encrypted_at_rest_and_unreadable_rows_fall_back_to_the_seed(session_factory, cipher, endpoint, caplog):
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-1"
    (row,) = _rows(session_factory)
    assert (row.scope, row.owner_user_id, row.server_key, row.version) == ("deployment", "", SERVER, 1)
    for column in (row.access_token_enc, row.refresh_token_enc):
        assert column.startswith("fernet:v2:")
        assert "access-1" not in column and "refresh-1" not in column
    assert cipher.decrypt_text(row.access_token_enc) == "access-1"
    assert cipher.decrypt_text(row.refresh_token_enc) == "refresh-1"

    # A process with another key cannot read the row; it falls back to the
    # seed (here already consumed) instead of failing on the ciphertext, and
    # the rejection tells the connection's user why and who can fix it.
    other = _replica(session_factory, CredentialsCipher.from_keys([Fernet.generate_key()]))
    with caplog.at_level("WARNING", logger="deerflow.mcp.oauth_store"):
        with pytest.raises(McpOAuthReauthorizationRequired) as rejected:
            await other.get_authorization_header(SERVER)
    assert endpoint.refresh_requests == ["refresh-0", "refresh-0"]
    assert "cannot be decrypted" in caplog.text
    assert "refresh-1" not in caplog.text
    message = str(rejected.value)
    assert f"'{SERVER}'" in message and "invalid_grant" in message and "DEER_FLOW_CREDENTIALS_KEY" in message
    assert "refresh-0" not in message and "refresh-1" not in message
    assert isinstance(rejected.value.__cause__, httpx.HTTPStatusError)


@pytest.mark.asyncio
async def test_personal_and_deployment_connections_with_one_name_keep_separate_rows(session_factory, cipher, endpoint):
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-1"
    endpoint.refresh_token = "personal-seed"
    personal = _config(seed="personal-seed")
    assert await _replica(session_factory, cipher, personal, owner_user_id="user-1").get_authorization_header(SERVER) == "Bearer access-2"
    _expire_access_tokens()

    # Each owner continues from its own chain after a restart.
    assert await _replica(session_factory, cipher, personal, owner_user_id="user-1").get_authorization_header(SERVER) == "Bearer access-3"
    assert [(row.scope, row.owner_user_id, row.server_key) for row in _rows(session_factory)] == [("deployment", "", SERVER), ("personal", "user-1", SERVER)]
    assert endpoint.refresh_requests == ["refresh-0", "personal-seed", "refresh-2"]


@pytest.mark.asyncio
async def test_client_credentials_tokens_stay_in_process(session_factory, cipher, monkeypatch):
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(parse_qs(request.content.decode())["grant_type"][0])
        return httpx.Response(200, json={"access_token": f"cc-{len(requests)}", "expires_in": 120})

    original_client = httpx.AsyncClient

    class OfflineClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", OfflineClient)
    config = _config(grant_type="client_credentials")

    assert await _replica(session_factory, cipher, config).get_authorization_header(SERVER) == "Bearer cc-1"
    assert await _replica(session_factory, cipher, config).get_authorization_header(SERVER) == "Bearer cc-2"
    assert _rows(session_factory) == []


@pytest.mark.asyncio
async def test_failed_refresh_releases_the_lease_for_the_next_caller(session_factory, cipher, endpoint):
    endpoint.fail_with = 503
    with pytest.raises(httpx.HTTPStatusError):
        await _replica(session_factory, cipher).get_authorization_header(SERVER)
    (row,) = _rows(session_factory)
    assert row.refresh_lease_owner is None

    endpoint.fail_with = None
    # The seed was never consumed, so a peer retries it at once, not after the lease runs out.
    assert await asyncio.wait_for(_replica(session_factory, cipher).get_authorization_header(SERVER), 5) == "Bearer access-1"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-0"]


@pytest.mark.asyncio
async def test_an_abandoned_refresh_lease_is_taken_over_after_it_expires(session_factory, cipher, endpoint, monkeypatch):
    monkeypatch.setattr(oauth_store, "REFRESH_LEASE_SECONDS", 0.5)
    crashed = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher)
    key = oauth_store.McpOAuthTokenKey(scope="deployment", owner_user_id="", server_key=SERVER)
    fingerprint = oauth_config_fingerprint(_config().mcp_servers[SERVER].oauth)
    # A process claimed the first refresh and died before writing a token.
    assert crashed.claim(key, fingerprint=fingerprint, expected_version=None) is not None

    assert await asyncio.wait_for(_replica(session_factory, cipher).get_authorization_header(SERVER), 10) == "Bearer access-1"
    (row,) = _rows(session_factory)
    assert row.refresh_lease_owner is None
    assert row.version == 1


@pytest.mark.asyncio
async def test_store_errors_fail_the_refresh_without_leaking_sql_parameters(cipher, endpoint, tmp_path, caplog):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'missing-table.db').as_posix()}")
    manager = _replica(sessionmaker(engine), cipher)
    try:
        with caplog.at_level("ERROR"):
            with pytest.raises(McpOAuthTokenStoreUnavailable) as raised:
                await manager.get_authorization_header(SERVER)
    finally:
        engine.dispose()
    assert SERVER in str(raised.value)
    assert "mcp_oauth_tokens" not in str(raised.value)
    # Never refresh without a place to put the rotated token.
    assert endpoint.refresh_requests == []


@pytest.mark.asyncio
async def test_installed_store_is_used_by_managers_built_without_one(session_factory, cipher, endpoint):
    set_mcp_oauth_token_store(McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher))

    assert await OAuthTokenManager.from_extensions_config(_config()).get_authorization_header(SERVER) == "Bearer access-1"
    _expire_access_tokens()
    assert await OAuthTokenManager.from_extensions_config(_config()).get_authorization_header(SERVER) == "Bearer access-2"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]


@pytest.mark.asyncio
async def test_without_a_store_tokens_stay_in_process(endpoint):
    assert await OAuthTokenManager.from_extensions_config(_config()).get_authorization_header(SERVER) == "Bearer access-1"
    _expire_access_tokens()
    # Today's behaviour: a new manager starts again from the configured seed,
    # and the rejection names the remedy instead of a bare HTTP 400.
    with pytest.raises(McpOAuthReauthorizationRequired, match="configuring a new refresh token") as rejected:
        await OAuthTokenManager.from_extensions_config(_config()).get_authorization_header(SERVER)
    assert "DEER_FLOW_CREDENTIALS_KEY" not in str(rejected.value)


def test_fingerprint_follows_the_token_chain_identity_not_the_client_secret():
    base = _config().mcp_servers[SERVER].oauth
    fingerprint = oauth_config_fingerprint(base)
    for field, value in {"token_url": "https://other.example.invalid/token", "client_id": "other", "scope": "read", "audience": "api", "refresh_token": "other-seed"}.items():
        assert oauth_config_fingerprint(base.model_copy(update={field: value})) != fingerprint, field
    # A rotated client secret keeps the issued refresh-token chain valid.
    assert oauth_config_fingerprint(base.model_copy(update={"client_secret": "rotated"})) == fingerprint
    assert "refresh-0" not in fingerprint


def test_a_claim_fails_once_a_peer_wrote_since_the_read(session_factory, cipher):
    """The version compare-and-set keeps a reader from refreshing with a refresh token a peer just consumed."""
    key = oauth_store.McpOAuthTokenKey(scope="deployment", owner_user_id="", server_key=SERVER)
    fingerprint = oauth_config_fingerprint(_config().mcp_servers[SERVER].oauth)
    a = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher)
    b = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher)
    expires_at = datetime(2030, 1, 1, tzinfo=UTC)

    lease = a.claim(key, fingerprint=fingerprint, expected_version=None)
    assert a.save(key, lease_owner=lease, fingerprint=fingerprint, request_fingerprint=REQUEST, access_token="access-1", token_type="Bearer", expires_at=expires_at, refresh_token="refresh-1", rotated=True)
    assert b.load(key, fingerprint=fingerprint, request_fingerprint=REQUEST)[0] == 1
    # Both read version 1; A refreshes first.
    lease = a.claim(key, fingerprint=fingerprint, expected_version=1)
    assert lease is not None
    assert b.claim(key, fingerprint=fingerprint, expected_version=1) is None, "a live lease must block the peer"
    assert a.save(key, lease_owner=lease, fingerprint=fingerprint, request_fingerprint=REQUEST, access_token="access-2", token_type="Bearer", expires_at=expires_at, refresh_token="refresh-2", rotated=True)

    assert b.claim(key, fingerprint=fingerprint, expected_version=1) is None, "the lease is free, but the row moved on"
    version, stored, _unreadable = b.load(key, fingerprint=fingerprint, request_fingerprint=REQUEST)
    assert (version, stored.refresh_token, stored.access_token) == (2, "refresh-2", "access-2")
    # A write under a lease that is no longer held is refused.
    assert not b.save(key, lease_owner="not-the-holder", fingerprint=fingerprint, request_fingerprint=REQUEST, access_token="x", token_type="Bearer", expires_at=expires_at, refresh_token="y", rotated=True)
    assert b.load(key, fingerprint=fingerprint, request_fingerprint=REQUEST)[1].refresh_token == "refresh-2"
    assert b.load(key, fingerprint="another-chain", request_fingerprint=REQUEST) == StoredTokenLookup(2, None)


@pytest.mark.asyncio
async def test_an_unloadable_credentials_key_keeps_tokens_in_process(session_factory, endpoint, monkeypatch, caplog):
    def broken_key():
        raise oauth_store.McpOAuthTokenKeyUnavailable("no key")

    store = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory))
    monkeypatch.setattr(store, "_cipher", broken_key)
    manager = OAuthTokenManager.from_extensions_config(_config(), token_store=store)

    with caplog.at_level("WARNING", logger="deerflow.mcp.oauth"):
        assert await manager.get_authorization_header(SERVER) == "Bearer access-1"
    assert "in this process only" in caplog.text
    assert _rows(session_factory) == []


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_gateway_shares_tokens_only_through_a_sql_database(backend, tmp_path):
    from app.gateway.mcp_oauth_tokens import build_mcp_oauth_token_store
    from deerflow.config.database_config import DatabaseConfig

    database = DatabaseConfig(backend=backend, sqlite_dir=str(tmp_path))
    store = build_mcp_oauth_token_store(SimpleNamespace(database=database))
    if backend == "memory":
        assert store is None
    else:
        assert isinstance(store, McpOAuthTokenStore)
    assert build_mcp_oauth_token_store(SimpleNamespace()) is None


def test_forgetting_unconfigured_connections_deletes_only_that_owners_other_rows(session_factory, cipher):
    store = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher)
    for owner, name in ((None, "kept"), (None, "removed"), ("alice", "kept"), ("alice", "removed"), ("bob", "removed")):
        assert store.claim(oauth_store.McpOAuthTokenKey.for_server(name, owner), fingerprint="f" * 64, expected_version=None)

    assert store.forget_unconfigured("alice", {"kept"}) == 1
    assert store.forget_unconfigured(None, {"kept", "never-stored"}) == 1
    assert [(row.scope, row.owner_user_id, row.server_key) for row in _rows(session_factory)] == [
        ("deployment", "", "kept"),
        ("personal", "alice", "kept"),
        ("personal", "bob", "removed"),
    ]
    # An owner with no connections left loses every row.
    assert store.forget_unconfigured("bob", set()) == 1
    assert [row.owner_user_id for row in _rows(session_factory)] == ["", "alice"]


@pytest.mark.asyncio
async def test_a_revoked_stored_chain_asks_to_reauthorize_without_blaming_the_key(session_factory, cipher, endpoint):
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-1"
    endpoint.refresh_token = "revoked-by-the-provider"
    _expire_access_tokens()

    with pytest.raises(McpOAuthReauthorizationRequired) as rejected:
        await _replica(session_factory, cipher).get_authorization_header(SERVER)
    assert "configuring a new refresh token" in str(rejected.value)
    assert "DEER_FLOW_CREDENTIALS_KEY" not in str(rejected.value)
    (row,) = _rows(session_factory)
    assert row.refresh_lease_owner is None, "a rejected refresh releases its lease"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]


class _SlowStreamingTokenServer:
    """A real loopback token endpoint that streams its JSON body in slow chunks.

    HTTPX timeouts bound each read, not the whole response, so a body that
    keeps trickling in can outlive any fixed lease.
    """

    def __init__(self, *, chunks: int, chunk_delay: float) -> None:
        import http.server
        import json as json_module
        import socketserver
        import time as time_module

        self.requests: list[str] = []
        self.started = threading.Event()
        endpoint = self
        current = {"refresh_token": "refresh-0", "generation": 0}

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                submitted = parse_qs(body)["refresh_token"][0]
                endpoint.requests.append(submitted)
                endpoint.started.set()
                if submitted != current["refresh_token"]:
                    payload = json_module.dumps({"error": "invalid_grant"}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                current["generation"] += 1
                current["refresh_token"] = f"refresh-{current['generation']}"
                payload = json_module.dumps({"access_token": f"access-{current['generation']}", "refresh_token": current["refresh_token"], "expires_in": 120}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                size = -(-len(payload) // chunks)
                for offset in range(0, len(payload), size):
                    piece = payload[offset : offset + size]
                    self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                    self.wfile.flush()
                    time_module.sleep(chunk_delay)
                self.wfile.write(b"0\r\n\r\n")

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/token"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def test_a_slow_token_response_keeps_its_lease_until_the_token_lands(session_factory, cipher, monkeypatch):
    """The holder renews its lease while the body streams, so a peer waits instead of resending the consumed token."""
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(oauth_store, "REFRESH_LEASE_SECONDS", 0.6)
    monkeypatch.setattr(oauth_store, "REFRESH_POLL_SECONDS", 0.05)

    # About 1.8 s of streaming: three times the lease.
    with _SlowStreamingTokenServer(chunks=6, chunk_delay=0.3) as server:
        config = _config(token_url=server.url)
        a = _replica(session_factory, cipher, config)
        b = _replica(session_factory, cipher, config)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(lambda: asyncio.run(a.get_authorization_header(SERVER)))
            assert server.started.wait(10), "replica A never reached the token endpoint"
            second = executor.submit(lambda: asyncio.run(b.get_authorization_header(SERVER)))
            assert first.result(timeout=20) == "Bearer access-1"
            assert second.result(timeout=20) == "Bearer access-1"
    assert server.requests == ["refresh-0"]
    (row,) = _rows(session_factory)
    assert (row.version, row.refresh_lease_owner) == (1, None)
    assert cipher.decrypt_text(row.refresh_token_enc) == "refresh-1"


@pytest.mark.asyncio
async def test_a_token_request_that_never_finishes_gives_up_and_releases_the_lease(session_factory, cipher, endpoint, monkeypatch):
    monkeypatch.setattr(oauth_store, "REFRESH_MAX_SECONDS", 0.3)
    handle = endpoint.handle

    async def stalled(request):
        await asyncio.sleep(5)
        return handle(request)

    monkeypatch.setattr(endpoint, "handle", stalled)
    with pytest.raises(RuntimeError, match="did not finish within"):
        await asyncio.wait_for(_replica(session_factory, cipher).get_authorization_header(SERVER), 5)
    (row,) = _rows(session_factory)
    assert row.refresh_lease_owner is None


def _fail_next_writes(store: McpOAuthTokenStore, monkeypatch, count: int = 1) -> None:
    """Make the next ``count`` token writes fail like a database outage."""
    original = store._repo.write
    remaining = {"n": count}

    def write(*args, **kwargs):
        if remaining["n"] > 0:
            remaining["n"] -= 1
            raise sa.exc.OperationalError("UPDATE mcp_oauth_tokens", {}, Exception("database is unavailable"))
        return original(*args, **kwargs)

    monkeypatch.setattr(store._repo, "write", write)


@pytest.mark.asyncio
async def test_a_rotation_the_store_missed_is_stored_before_the_next_refresh(session_factory, cipher, endpoint, monkeypatch):
    a = _replica(session_factory, cipher)
    assert await a.get_authorization_header(SERVER) == "Bearer access-1"
    _expire_access_tokens()
    _fail_next_writes(a._token_store, monkeypatch)
    # refresh-1 -> refresh-2, but the row keeps the consumed refresh-1.
    assert await a.get_authorization_header(SERVER) == "Bearer access-2"
    _expire_access_tokens()

    # The live refresh-2 is stored first instead of being replaced by refresh-1.
    assert await a.get_authorization_header(SERVER) == "Bearer access-3"
    _expire_access_tokens()
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-4"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1", "refresh-2", "refresh-3"]


@pytest.mark.asyncio
async def test_a_missed_rotation_reaches_peers_while_the_access_token_is_still_valid(session_factory, cipher, endpoint, monkeypatch):
    monkeypatch.setattr("deerflow.mcp.oauth._UNSAVED_ROTATION_RETRY_SECONDS", 0.0)
    a = _replica(session_factory, cipher)
    _fail_next_writes(a._token_store, monkeypatch)
    assert await a.get_authorization_header(SERVER) == "Bearer access-1"
    assert _rows(session_factory)[0].refresh_token_enc is None, "the first write failed"

    # The next call, still within the token's lifetime, stores the rotation.
    assert await a.get_authorization_header(SERVER) == "Bearer access-1"
    _expire_access_tokens()
    assert await _replica(session_factory, cipher).get_authorization_header(SERVER) == "Bearer access-2"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]


@pytest.mark.asyncio
async def test_a_newer_peer_chain_supersedes_a_missed_rotation(session_factory, cipher, endpoint, monkeypatch):
    a = _replica(session_factory, cipher)
    assert await a.get_authorization_header(SERVER) == "Bearer access-1"
    _expire_access_tokens()
    _fail_next_writes(a._token_store, monkeypatch)
    assert await a.get_authorization_header(SERVER) == "Bearer access-2"

    # Meanwhile a peer stored a newer chain over version 1 (e.g. a provider with a reuse grace period).
    peer = McpOAuthTokenStore(SqlMcpOAuthTokenRepository(session_factory), cipher=cipher)
    key = oauth_store.McpOAuthTokenKey.for_server(SERVER, None)
    oauth = _config().mcp_servers[SERVER].oauth
    lease = peer.claim(key, fingerprint=oauth_config_fingerprint(oauth), expected_version=1)
    assert lease is not None
    assert peer.save(
        key,
        lease_owner=lease,
        fingerprint=oauth_config_fingerprint(oauth),
        request_fingerprint=oauth_token_request_fingerprint(oauth),
        access_token="peer-access",
        token_type="Bearer",
        expires_at=_Clock.current + timedelta(seconds=900),
        refresh_token="peer-refresh",
        rotated=True,
    )
    _expire_access_tokens()

    assert await a.get_authorization_header(SERVER) == "Bearer peer-access"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]


@pytest.mark.asyncio
async def test_changed_token_request_parameters_refresh_from_the_stored_chain_instead_of_reusing_the_access_token(session_factory, cipher, endpoint):
    assert await _replica(session_factory, cipher, _config(extra_token_params={"resource": "https://old-api"})).get_authorization_header(SERVER) == "Bearer access-1"

    # A hot-reloaded server asks for another resource: the old access token is
    # for the wrong audience, but its refresh-token chain is still the live one.
    changed = _config(extra_token_params={"resource": "https://new-api"})
    assert await _replica(session_factory, cipher, changed).get_authorization_header(SERVER) == "Bearer access-2"
    assert endpoint.refresh_requests == ["refresh-0", "refresh-1"]
    assert endpoint.forms[-1]["resource"] == ["https://new-api"]
    # Processes with the new parameters now share the new access token.
    assert await _replica(session_factory, cipher, changed).get_authorization_header(SERVER) == "Bearer access-2"
    assert len(endpoint.refresh_requests) == 2


def test_request_fingerprint_follows_token_request_parameters_not_the_chain():
    base = _config(extra_token_params={"resource": "https://api"}).mcp_servers[SERVER].oauth
    fingerprint = oauth_token_request_fingerprint(base)
    for update in ({"extra_token_params": {"resource": "https://other"}}, {"extra_token_params": {}}, {"token_field": "id_token"}):
        changed = base.model_copy(update=update)
        assert oauth_token_request_fingerprint(changed) != fingerprint, update
        assert oauth_config_fingerprint(changed) == oauth_config_fingerprint(base), "the refresh-token chain is unaffected"
    assert oauth_token_request_fingerprint(base.model_copy(update={"extra_token_params": {"resource": "https://api"}})) == fingerprint

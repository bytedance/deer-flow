"""Split browser MCP authorization across requests; only the SQL store owns the grant."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import ssl
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import httpx
from langchain_core.tools import ToolException
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    issuers_match,
    validate_metadata_issuer,
)
from mcp.shared.auth import OAuthMetadata, OAuthToken, ProtectedResourceMetadata

from deerflow.community.url_safety import resolve_host_addresses, resolve_public_addresses
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp import oauth_store
from deerflow.mcp.headers import illegal_header_value_reason
from deerflow.mcp.personal_network import DestinationPinnedTransport

_CONNECT = "Connect or reconnect this MCP server in Capability Center."
_UNAVAILABLE = "The MCP authorization service is unavailable. Please try again later."
_MAX_RESPONSE = 256 * 1024


class BrowserOAuthError(Exception):
    """All outward errors are fixed messages; remote bodies / credentials stay private."""


class _InvalidGrant(BrowserOAuthError):
    pass


def _https(value) -> httpx.URL:
    url = httpx.URL(str(value))
    if url.scheme != "https" or not url.host or url.userinfo or url.fragment:
        raise BrowserOAuthError("MCP authorization requires trusted HTTPS endpoints.")
    return url


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


def _trusted_endpoint(value, configured) -> httpx.URL:
    url = _https(value)
    if _origin(url) != _origin(_https(configured)):
        raise BrowserOAuthError("The discovered endpoint is outside the configured origin.")
    return url


def _transport(server: McpServerConfig, *, resource_only: bool) -> DestinationPinnedTransport:
    resource = _https(server.url)
    trusted = {_origin(resource), _origin(_https(server.user_oauth.issuer))}

    def resolve(value: httpx.URL) -> list[str]:
        url = _https(value)
        if (resource_only and url != resource) or _origin(url) not in trusted:
            raise BrowserOAuthError("The destination does not match the configured MCP connection.")
        addresses = resolve_host_addresses(url.host) if server.user_oauth.allow_private_addresses else resolve_public_addresses(url.host, action="connect to")
        if not addresses:
            raise BrowserOAuthError(_UNAVAILABLE)
        return list(map(str, addresses))

    # Respect the operator's CA trust for this opt-in mode, never proxy credentials through env proxies.
    return DestinationPinnedTransport(resolve=resolve, tls_context=ssl.create_default_context)


def mcp_client_factory(server: McpServerConfig):
    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(headers=headers, timeout=timeout or 10.0, auth=auth, follow_redirects=False, trust_env=False, transport=_transport(server, resource_only=True))

    return factory


def browser_grant_fingerprint(server: McpServerConfig) -> str:
    oauth = server.user_oauth
    binding = [server.type, server.url, oauth.issuer, oauth.client_id, oauth.redirect_uri, oauth.scope, oauth.grant_revision, oauth.allow_private_addresses]
    return hashlib.sha256(json.dumps(binding, separators=(",", ":"), default=str).encode()).hexdigest()


def configured_servers() -> dict[str, McpServerConfig]:
    # The same deployment JSON snapshot feeds tool assembly. Never substitute a
    # last-known-good cache, a YAML-only entry, or an untrusted run override.
    config = ExtensionsConfig.from_file()
    return {name: s for name, s in config.get_enabled_mcp_servers().items() if s.uses_browser_oauth}


def get_browser_oauth_server(name: str) -> McpServerConfig | None:
    return configured_servers().get(name)


def _store():
    store = oauth_store.get_mcp_oauth_token_store()
    if store is None:
        raise BrowserOAuthError(_UNAVAILABLE)
    return store


async def _json(client, method: str, url, **kwargs) -> tuple[int, dict]:
    async with client.stream(method, url, **kwargs) as response:
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=16384):
            data.extend(chunk)
            if len(data) > _MAX_RESPONSE:
                raise BrowserOAuthError("The authorization response is too large.")
        try:
            body = json.loads(data) if data else {}
        except ValueError:
            body = {}
        return response.status_code, body if isinstance(body, dict) else {}


async def _metadata(client, urls, model, expected_origin):
    for url in dict.fromkeys(urls):
        status, data = await _json(client, "GET", _trusted_endpoint(url, expected_origin), headers={"Accept": "application/json"})
        if status == 404:
            continue
        if status == 200:
            return model.model_validate(data)
        break
    raise BrowserOAuthError("Could not discover OAuth metadata for the configured MCP server.")


async def begin_connection(name, server, owner, browser_binding, state):
    oauth = server.user_oauth
    async with asyncio.timeout(20), httpx.AsyncClient(transport=_transport(server, resource_only=False), follow_redirects=False, trust_env=False, timeout=5) as client:
        # No credential on the probe. Real Streamable HTTP servers may reply with an SSE stream;
        # consume only the challenge headers, never that stream.
        async with client.stream(
            "POST",
            _https(server.url),
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "DeerFlow", "version": "1"}}},
        ) as response:
            if response.is_redirect or response.status_code >= 500:
                raise BrowserOAuthError("Could not contact the configured MCP server.")
            challenge = extract_resource_metadata_from_www_auth(response)
            required_scope = extract_scope_from_www_auth(response)
        protected = await _metadata(client, build_protected_resource_metadata_discovery_urls(challenge, str(server.url)), ProtectedResourceMetadata, server.url)
        if not issuers_match(str(protected.resource), str(server.url)) or not any(issuers_match(str(i), str(oauth.issuer)) for i in protected.authorization_servers or ()):
            raise BrowserOAuthError("The MCP resource or authorization issuer does not match its configuration.")
        issuer = str(oauth.issuer)
        md = await _metadata(client, build_oauth_authorization_server_metadata_discovery_urls(issuer, str(server.url)), OAuthMetadata, issuer)
        validate_metadata_issuer(md, issuer)
        if "S256" not in (md.code_challenge_methods_supported or ()) or "code" not in md.response_types_supported:
            raise BrowserOAuthError("The MCP authorization server must support authorization code with PKCE S256.")
        auth_method = "client_secret_basic" if oauth.client_secret else "none"
        if md.token_endpoint_auth_methods_supported is not None and auth_method not in md.token_endpoint_auth_methods_supported:
            raise BrowserOAuthError("The configured client authentication method is not supported.")
        token_url = _trusted_endpoint(md.token_endpoint, issuer)
        authorize = _trusted_endpoint(md.authorization_endpoint, issuer)
        if not oauth.allow_private_addresses:
            await asyncio.to_thread(resolve_public_addresses, authorize.host, action="connect to")
        pkce = PKCEParameters.generate()
        # The configured scope bounds what a challenge may request.
        if oauth.scope and required_scope and not set(required_scope.split()) <= set(oauth.scope.split()):
            raise BrowserOAuthError("The challenged scopes exceed the operator-approved scope.")
        scope = required_scope or oauth.scope or " ".join(protected.scopes_supported or ()) or None
        context = oauth_store.DelegatedOAuthContext(issuer=issuer, resource=str(server.url), token_url=str(token_url), scope=scope)
        params = {"response_type": "code", "client_id": oauth.client_id, "redirect_uri": str(oauth.redirect_uri), "resource": context.resource, "code_challenge": pkce.code_challenge, "code_challenge_method": "S256", "state": state}
        if scope:
            params["scope"] = scope
        key = oauth_store.McpOAuthTokenKey.for_delegated(name, owner)
        await asyncio.to_thread(_store().begin_delegated, key, fingerprint=browser_grant_fingerprint(server), state=state, browser_binding=browser_binding, code_verifier=pkce.code_verifier, context=context)
        return str(authorize.copy_merge_params(params))


async def _exchange(server, context, form):
    oauth = server.user_oauth
    data = {**form, "resource": context.resource}
    auth = None
    if oauth.client_secret:
        auth = httpx.BasicAuth(quote_plus(oauth.client_id), quote_plus(oauth.client_secret))
    else:
        data["client_id"] = oauth.client_id
    async with asyncio.timeout(10), httpx.AsyncClient(transport=_transport(server, resource_only=False), trust_env=False, follow_redirects=False, timeout=5.0) as client:
        status, body = await _json(client, "POST", _trusted_endpoint(context.token_url, oauth.issuer), data=data, auth=auth, headers={"Accept": "application/json"})
    if status in (400, 401) and body.get("error") == "invalid_grant":
        raise _InvalidGrant(_CONNECT)
    if status != 200 or not isinstance(body.get("token_type"), str):
        raise BrowserOAuthError(_UNAVAILABLE)
    token = OAuthToken.model_validate(body)
    if not token.access_token or illegal_header_value_reason(token.access_token) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token.access_token):
        raise BrowserOAuthError("The provider did not return a usable bearer token.")
    # RFC 6749 permits the provider to omit expires_in. Use a bounded local lifetime
    # instead of considering an unqualified browser credential permanent.
    expires = datetime.now(UTC) + timedelta(seconds=min(365 * 86400, max(0, token.expires_in if token.expires_in is not None else 3600)))
    return token, expires


async def finish_connection(attempt, server, code: str) -> bool:
    if browser_grant_fingerprint(server) != attempt.fingerprint:
        return False
    token, expires = await _exchange(server, attempt.context, {"grant_type": "authorization_code", "code": code, "code_verifier": attempt.code_verifier, "redirect_uri": str(server.user_oauth.redirect_uri)})
    current = (await asyncio.to_thread(configured_servers)).get(attempt.key.server_key)
    if not current or browser_grant_fingerprint(current) != attempt.fingerprint:
        return False
    return await asyncio.to_thread(_store().complete_delegated, attempt, access_token=token.access_token, expires_at=expires, refresh_token=token.refresh_token)


def connection_state(name, server, owner):
    store = oauth_store.get_mcp_oauth_token_store()
    if store is None:
        return "unavailable"
    key = oauth_store.McpOAuthTokenKey.for_delegated(name, owner)
    fingerprint = browser_grant_fingerprint(server)
    grant = store.get_delegated(key, fingerprint=fingerprint)
    if grant is None:
        return "reconnect_required" if store.delegated_needs_reconnect(key, fingerprint=fingerprint) else "disconnected"
    if not grant.token.refresh_token and grant.token.expires_at and grant.token.expires_at <= datetime.now(UTC):
        return "reconnect_required"
    return "connected"


async def get_call_token(name, server, owner, *, expected_epoch=None, rejected_token=None):
    """Get current authority at dispatch; the caller must not replay a tool side effect."""
    try:
        return await _call_token(name, server, owner, expected_epoch, rejected_token)
    except ToolException:
        raise
    except Exception:
        raise ToolException(_UNAVAILABLE) from None


async def _call_token(name, server, owner, expected_epoch, rejected_token):
    store = _store()
    key = oauth_store.McpOAuthTokenKey.for_delegated(name, owner)
    fp = browser_grant_fingerprint(server)
    deadline = time.monotonic() + oauth_store.REFRESH_LEASE_SECONDS + 12
    while time.monotonic() < deadline:
        grant = await asyncio.to_thread(store.get_delegated, key, fingerprint=fp)
        if grant is None or expected_epoch is not None and grant.grant_epoch != expected_epoch:
            raise ToolException(_CONNECT)
        current = grant.token
        rejected = rejected_token is not None and secrets.compare_digest(current.access_token or "", rejected_token)
        if current.access_token and not rejected and (current.expires_at is None or current.expires_at > datetime.now(UTC)):
            return current.access_token, grant.grant_epoch
        if not current.refresh_token:
            if await asyncio.to_thread(store.mark_delegated_reconnect, key, expected_epoch=grant.grant_epoch, expected_version=grant.version):
                raise ToolException(_CONNECT)
            continue
        lease = await asyncio.to_thread(store.claim, key, fingerprint=fp, expected_version=grant.version, grant_epoch=grant.grant_epoch)
        if not lease:
            await asyncio.sleep(oauth_store.REFRESH_POLL_SECONDS)
            continue
        try:
            # Hard timeout < the existing refresh lease; no second worker can refresh a live request.
            token, expires = await _exchange(server, grant.context, {"grant_type": "refresh_token", "refresh_token": current.refresh_token})
            saved = await asyncio.to_thread(
                store.save,
                key,
                lease_owner=lease,
                fingerprint=fp,
                request_fingerprint=fp,
                grant_epoch=grant.grant_epoch,
                access_token=token.access_token,
                token_type=token.token_type,
                expires_at=expires,
                refresh_token=token.refresh_token or current.refresh_token,
                rotated=bool(token.refresh_token and token.refresh_token != current.refresh_token),
            )
            if saved:
                return token.access_token, grant.grant_epoch
            raise ToolException(_CONNECT)
        except _InvalidGrant:
            await asyncio.to_thread(store.disconnect_delegated, key, expected_epoch=grant.grant_epoch, lease_owner=lease)
            raise ToolException(_CONNECT) from None
        finally:
            await asyncio.to_thread(store.release, key, lease)
    raise ToolException(_UNAVAILABLE)

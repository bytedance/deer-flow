"""OAuth token support for MCP HTTP/SSE servers."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, McpOAuthConfig
from deerflow.mcp.headers import apply_header_overrides, header_spellings, illegal_header_value_reason

logger = logging.getLogger(__name__)


@dataclass
class _OAuthToken:
    """Cached OAuth token."""

    access_token: str
    token_type: str
    expires_at: datetime


@dataclass
class _OAuthState:
    """One connection's mutable tokens and loop-independent refresh signal."""

    config: McpOAuthConfig
    token: _OAuthToken | None = None
    # Protect short state transitions only; never hold this lock across an await.
    lock: threading.Lock = field(default_factory=threading.Lock)
    refresh_done: Future[None] | None = None


class OAuthTokenManager:
    """Acquire/cache/refresh OAuth tokens for MCP servers."""

    def __init__(self, oauth_by_server: dict[str, McpOAuthConfig]):
        # Refresh-token rotation belongs to runtime state, not the parsed config
        # used by cache/snapshot validation or custom interceptor builders.
        # Sync tool wrappers use a fresh asyncio.run() per call. Refresh waiters
        # therefore need a signal that can be awaited from different loops.
        self._states = {name: _OAuthState(config=oauth.model_copy(deep=True)) for name, oauth in oauth_by_server.items()}

    @classmethod
    def from_extensions_config(
        cls,
        extensions_config: ExtensionsConfig,
        *,
        shared_manager: OAuthTokenManager | None = None,
    ) -> OAuthTokenManager:
        """Build a manager, optionally reusing already-validated connection state.

        The durable runtime supplies ``shared_manager`` only after validating
        the deployment snapshot. Personal connections must never use it.
        """
        oauth_by_server: dict[str, McpOAuthConfig] = {}
        for server_name, server_config in extensions_config.get_enabled_mcp_servers().items():
            if server_config.oauth and server_config.oauth.enabled:
                oauth_by_server[server_name] = server_config.oauth
        manager = cls(oauth_by_server)
        if shared_manager is not None:
            for name in manager._states.keys() & shared_manager._states.keys():
                manager._states[name] = shared_manager._states[name]
        return manager

    def has_oauth_servers(self) -> bool:
        return bool(self._states)

    def oauth_server_names(self) -> list[str]:
        return list(self._states)

    async def get_authorization_header(self, server_name: str) -> str | None:
        state = self._states.get(server_name)
        if state is None:
            return None

        oauth = state.config
        while True:
            with state.lock:
                token = state.token
                if token and not self._is_expiring(token, oauth):
                    return self._authorization_value(token, server_name)
                refresh_done = state.refresh_done
                if refresh_done is None:
                    refresh_done = state.refresh_done = Future()
                    break
            # Blocking lock waiters can exhaust the default executor needed by
            # the refresh owner's DNS lookup. Await a loop-local wrapper instead;
            # cancelling a waiter must not cancel the shared completion signal.
            await asyncio.shield(asyncio.wrap_future(refresh_done))

        try:
            fresh = await self._fetch_token(oauth)
            with state.lock:
                state.token = fresh
            logger.info(f"Refreshed OAuth access token for MCP server: {server_name}")
            return self._authorization_value(fresh, server_name)
        finally:
            with state.lock:
                state.refresh_done = None
            # Wake every loop even when this caller fails or is cancelled. They
            # recheck the cache and may elect a new owner. Notify outside the lock.
            refresh_done.set_result(None)

    @staticmethod
    def _authorization_value(token: _OAuthToken, server_name: str) -> str:
        """Render the Authorization value, refusing one the transport would echo.

        The token endpoint's response is not this process's to control: an
        ``access_token`` or ``token_type`` carrying a newline reaches h11, which
        raises with the full value in the message, and
        ``ToolErrorHandlingMiddleware`` copies that message into a
        model-visible ToolMessage. Failing closed here keeps the token out of
        the prompt, the checkpoint, and traces, at the one boundary every caller
        goes through -- the tool interceptor, the initial discovery headers, and
        the durable task path all read their value from here. A token outside
        ASCII fails earlier, inside httpx, with only the offending character in
        the message; that one is refused for a deliverable error rather than for
        secrecy.

        The rendered value is what gets checked, not the two fields separately,
        because the rendered value is what the transport sees. An
        ``access_token`` of ``" abc"`` is legal once it sits after ``Bearer ``
        even though the field on its own carries leading whitespace, and
        rejecting it would deny a token the server would have accepted.
        """
        value = f"{token.token_type} {token.access_token}"
        reason = illegal_header_value_reason(value)
        if reason is not None:
            # Names the server and the reason, never the token: this message
            # travels to the model on the interceptor path.
            raise ValueError(f"OAuth token for MCP server '{server_name}' cannot be sent as an HTTP header value: the Authorization value {reason}. Check what the token endpoint returned for this server.")
        return value

    @staticmethod
    def _is_expiring(token: _OAuthToken, oauth: McpOAuthConfig) -> bool:
        now = datetime.now(UTC)
        return token.expires_at <= now + timedelta(seconds=max(oauth.refresh_skew_seconds, 0))

    async def _fetch_token(self, oauth: McpOAuthConfig) -> _OAuthToken:
        import httpx  # pyright: ignore[reportMissingImports]

        # extra_token_params is spread first so the reserved fields below
        # (grant_type, scope, audience, client_id, ...) cannot be silently
        # overridden by an operator-supplied key — otherwise the branch logic
        # below (which keys off oauth.grant_type) and the value actually sent
        # to the token endpoint would disagree.
        data: dict[str, str] = dict(oauth.extra_token_params)
        data["grant_type"] = oauth.grant_type

        if oauth.scope:
            data["scope"] = oauth.scope
        if oauth.audience:
            data["audience"] = oauth.audience

        if oauth.grant_type == "client_credentials":
            if not oauth.client_id or not oauth.client_secret:
                raise ValueError("OAuth client_credentials requires client_id and client_secret")
            data["client_id"] = oauth.client_id
            data["client_secret"] = oauth.client_secret
        elif oauth.grant_type == "refresh_token":
            if not oauth.refresh_token:
                raise ValueError("OAuth refresh_token grant requires refresh_token")
            data["refresh_token"] = oauth.refresh_token
            if oauth.client_id:
                data["client_id"] = oauth.client_id
            if oauth.client_secret:
                data["client_secret"] = oauth.client_secret
        else:
            raise ValueError(f"Unsupported OAuth grant type: {oauth.grant_type}")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(oauth.token_url, data=data)
            response.raise_for_status()
            payload = response.json()

        access_token = payload.get(oauth.token_field)
        if not access_token:
            raise ValueError(f"OAuth token response missing '{oauth.token_field}'")

        # Persist a rotated refresh_token so subsequent refreshes use the latest
        # value. This updates our private runtime copy only — neither the parsed
        # extensions config nor extensions_config.json. Providers that rotate refresh
        # tokens (Auth0, Okta, Google, etc.) return a new refresh_token on each
        # refresh; discarding it makes the next refresh fail with invalid_grant.
        if oauth.grant_type == "refresh_token":
            rotated = payload.get("refresh_token")
            if isinstance(rotated, str) and rotated:
                oauth.refresh_token = rotated

        token_type = str(payload.get(oauth.token_type_field, oauth.default_token_type) or oauth.default_token_type)

        expires_in_raw = payload.get(oauth.expires_in_field, 3600)
        try:
            expires_in = int(expires_in_raw)
        except (TypeError, ValueError):
            expires_in = 3600

        expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in, 1))
        return _OAuthToken(access_token=access_token, token_type=token_type, expires_at=expires_at)


def build_oauth_tool_interceptor(
    extensions_config: ExtensionsConfig,
    *,
    token_manager: OAuthTokenManager | None = None,
) -> Any | None:
    """Build a tool interceptor that injects OAuth Authorization headers."""
    token_manager = token_manager or OAuthTokenManager.from_extensions_config(extensions_config)
    if not token_manager.has_oauth_servers():
        return None

    # The servers' static header spellings, so the injected token replaces a
    # static header spelled 'authorization' at the adapter's case-sensitive
    # connection merge instead of riding alongside it (see ``mcp/headers.py``).
    spellings_by_server = {server_name: header_spellings(server_config.headers) for server_name, server_config in extensions_config.get_enabled_mcp_servers().items()}

    async def oauth_interceptor(request: Any, handler: Any) -> Any:
        header = await token_manager.get_authorization_header(request.server_name)
        if not header:
            return await handler(request)

        updated_headers = apply_header_overrides(
            request.headers,
            {"Authorization": header},
            spellings=spellings_by_server.get(request.server_name),
        )
        return await handler(request.override(headers=updated_headers))

    return oauth_interceptor


async def get_initial_oauth_headers(
    extensions_config: ExtensionsConfig,
    *,
    token_manager: OAuthTokenManager | None = None,
) -> dict[str, str]:
    """Get initial OAuth Authorization headers for MCP server connections."""
    token_manager = token_manager or OAuthTokenManager.from_extensions_config(extensions_config)
    if not token_manager.has_oauth_servers():
        return {}

    headers: dict[str, str] = {}
    for server_name in token_manager.oauth_server_names():
        try:
            value = await token_manager.get_authorization_header(server_name)
        except Exception:
            logger.warning(
                "Skipping initial OAuth header for MCP server '%s' after token fetch failed",
                server_name,
                exc_info=True,
            )
            continue
        if value:
            headers[server_name] = value

    return {name: value for name, value in headers.items() if value}

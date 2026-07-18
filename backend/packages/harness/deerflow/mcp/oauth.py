"""OAuth token support for MCP HTTP/SSE servers."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, McpOAuthConfig

logger = logging.getLogger(__name__)


@dataclass
class _OAuthToken:
    """Cached OAuth token."""

    access_token: str
    token_type: str
    expires_at: datetime


class OAuthTokenManager:
    """Acquire/cache/refresh OAuth tokens for MCP servers."""

    def __init__(self, oauth_by_server: dict[str, McpOAuthConfig]):
        self._oauth_by_server = oauth_by_server
        self._tokens: dict[str, _OAuthToken] = {}
        # A plain threading.Lock, not asyncio.Lock: the embedded/TUI sync tool-call
        # path (DeerFlowClient.stream() -> LangGraph ToolNode._func -> a
        # ThreadPoolExecutor -> deerflow.tools.sync.make_sync_tool_wrapper's
        # per-call asyncio.run()) invokes get_authorization_header from a fresh
        # event loop on a fresh OS thread for every concurrent tool call. An
        # asyncio.Lock binds to whichever loop first contends on it; a second
        # caller's release/wake-up crossing loops without call_soon_threadsafe
        # either deadlocks silently or raises "bound to a different event loop".
        # threading.Lock has no loop affinity, so it is safe to share across
        # however many event loops/threads call into the same server's lock.
        self._locks: dict[str, threading.Lock] = {name: threading.Lock() for name in oauth_by_server}

    @classmethod
    def from_extensions_config(cls, extensions_config: ExtensionsConfig) -> OAuthTokenManager:
        oauth_by_server: dict[str, McpOAuthConfig] = {}
        for server_name, server_config in extensions_config.get_enabled_mcp_servers().items():
            if server_config.oauth and server_config.oauth.enabled:
                oauth_by_server[server_name] = server_config.oauth
        return cls(oauth_by_server)

    def has_oauth_servers(self) -> bool:
        return bool(self._oauth_by_server)

    def oauth_server_names(self) -> list[str]:
        return list(self._oauth_by_server.keys())

    async def get_authorization_header(self, server_name: str) -> str | None:
        oauth = self._oauth_by_server.get(server_name)
        if not oauth:
            return None

        token = self._tokens.get(server_name)
        if token and not self._is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"

        lock = self._locks[server_name]
        # Acquire the OS-level lock off-thread so a blocking wait never blocks this
        # event loop, then release it synchronously (release() never blocks). This
        # keeps the de-duplication behavior of the old `async with lock:` (only one
        # concurrent caller per server actually fetches a token) while remaining
        # safe when callers are on different event loops/threads.
        #
        # The acquisition itself runs as an explicit Task, shielded from this
        # coroutine's own cancellation. A bare `await asyncio.to_thread(lock.acquire)`
        # cannot be safely cancelled: once the executor thread has started running
        # lock.acquire(), Python has no way to stop it, so a cancellation delivered
        # at that await would still let the thread go on to acquire the lock later
        # (whenever the current holder releases it) with this coroutine already
        # gone and nobody left to call release() -- the lock would stay locked
        # forever and every later call for this server would block permanently at
        # this same line. Shielding the acquisition task means a cancelled caller
        # can instead wait for that (unstoppable) acquisition to actually land and
        # release the lock immediately, rather than leaking ownership of it.
        acquire_task = asyncio.create_task(asyncio.to_thread(lock.acquire), name=f"oauth-lock-acquire:{server_name}")
        try:
            await asyncio.shield(acquire_task)
        except asyncio.CancelledError:
            # Keep waiting -- shielded on every retry -- until the acquisition
            # actually finishes, even if this coroutine is cancelled again while
            # cleaning up: the underlying thread cannot be interrupted, so this is
            # the only way to learn when the lock becomes ours and release it
            # right away instead of leaving it locked forever.
            while not acquire_task.done():
                try:
                    await asyncio.shield(acquire_task)
                except asyncio.CancelledError:
                    continue
            lock.release()
            raise
        try:
            token = self._tokens.get(server_name)
            if token and not self._is_expiring(token, oauth):
                return f"{token.token_type} {token.access_token}"

            fresh = await self._fetch_token(oauth)
            self._tokens[server_name] = fresh
            logger.info(f"Refreshed OAuth access token for MCP server: {server_name}")
            return f"{fresh.token_type} {fresh.access_token}"
        finally:
            lock.release()

    @staticmethod
    def _is_expiring(token: _OAuthToken, oauth: McpOAuthConfig) -> bool:
        now = datetime.now(UTC)
        return token.expires_at <= now + timedelta(seconds=max(oauth.refresh_skew_seconds, 0))

    async def _fetch_token(self, oauth: McpOAuthConfig) -> _OAuthToken:
        import httpx  # pyright: ignore[reportMissingImports]

        data: dict[str, str] = {
            "grant_type": oauth.grant_type,
            **oauth.extra_token_params,
        }

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
        # value. This is an in-process update only — it is intentionally NOT
        # written back to extensions_config.json. Providers that rotate refresh
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


def build_oauth_tool_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    """Build a tool interceptor that injects OAuth Authorization headers."""
    token_manager = OAuthTokenManager.from_extensions_config(extensions_config)
    if not token_manager.has_oauth_servers():
        return None

    async def oauth_interceptor(request: Any, handler: Any) -> Any:
        header = await token_manager.get_authorization_header(request.server_name)
        if not header:
            return await handler(request)

        updated_headers = dict(request.headers or {})
        updated_headers["Authorization"] = header
        return await handler(request.override(headers=updated_headers))

    return oauth_interceptor


async def get_initial_oauth_headers(extensions_config: ExtensionsConfig) -> dict[str, str]:
    """Get initial OAuth Authorization headers for MCP server connections."""
    token_manager = OAuthTokenManager.from_extensions_config(extensions_config)
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

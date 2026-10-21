"""OAuth token support for MCP HTTP/SSE servers."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, McpOAuthConfig
from deerflow.mcp import oauth_store
from deerflow.mcp.headers import apply_header_overrides, header_spellings, illegal_header_value_reason
from deerflow.mcp.oauth_store import (
    McpOAuthTokenKey,
    McpOAuthTokenKeyUnavailable,
    McpOAuthTokenStore,
    McpOAuthTokenStoreUnavailable,
    get_mcp_oauth_token_store,
    oauth_config_fingerprint,
    oauth_token_request_fingerprint,
)

logger = logging.getLogger(__name__)

# Used when the token endpoint omits ``expires_in`` or returns a value the
# manager cannot turn into a lifetime.
_DEFAULT_TOKEN_LIFETIME_SECONDS = 3600
# How often a still-valid token retries storing a rotation the store missed.
_UNSAVED_ROTATION_RETRY_SECONDS = 5.0


class McpOAuthReauthorizationRequired(RuntimeError):
    """The token endpoint rejected the refresh token (``invalid_grant``); only a new one fixes the connection.

    The message names the server and the remedy, never a token: on the tool
    interceptor path it is the model-visible tool error the owner reads.
    """


class _RefreshTokenRejected(Exception):
    """Internal: ``invalid_grant`` for a refresh_token request, before the server name is known."""

    def __init__(self) -> None:
        super().__init__("invalid_grant")
        # Set when this process fell back to the seed because it could not
        # decrypt the chain a peer stored: a key mismatch, not a lapsed grant.
        self.stored_chain_unreadable = False


def _is_invalid_grant(response: Any) -> bool:
    if getattr(response, "status_code", None) not in (400, 401):
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("error") == "invalid_grant"


def _reauthorization_message(server_name: str, *, stored_chain_unreadable: bool) -> str:
    message = f"The OAuth provider rejected the refresh token for MCP server '{server_name}' (invalid_grant). Re-authorize this connection by configuring a new refresh token for it."
    if stored_chain_unreadable:
        message += " This Gateway instance could not decrypt the token chain another instance stored, so every instance needs the same DEER_FLOW_CREDENTIALS_KEY; ask the operator to set it."
    return message


@dataclass
class _OAuthToken:
    """Cached OAuth token."""

    access_token: str
    token_type: str
    expires_at: datetime


@dataclass
class _OAuthState:
    """One connection's mutable tokens and cross-loop refresh lock."""

    config: McpOAuthConfig
    token: _OAuthToken | None = None
    # Sync tool wrappers and the Gateway can refresh from different loops.
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Shared-store row and token-chain identity; only the refresh_token grant
    # has a rotating credential worth sharing across processes.
    store_key: McpOAuthTokenKey | None = None
    fingerprint: str | None = None
    request_fingerprint: str | None = None
    # Set when this process's latest refresh could not be stored: the row
    # version it refreshed from. Peers still see the consumed refresh token,
    # so the live one in ``config`` is written back before anything older is
    # adopted or refreshed with.
    unsaved_base_version: int | None = None
    unsaved_retry_at: float = 0.0


class OAuthTokenManager:
    """Acquire/cache/refresh OAuth tokens for MCP servers."""

    def __init__(
        self,
        oauth_by_server: dict[str, McpOAuthConfig],
        *,
        owner_user_id: str | None = None,
        token_store: McpOAuthTokenStore | None = None,
    ):
        # Refresh-token rotation belongs to runtime state, not the parsed config
        # used by cache/snapshot validation or custom interceptor builders.
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
        #
        # ``owner_user_id`` marks a personal connection's manager; ``token_store``
        # overrides the host-installed store (``oauth_store``) for refresh_token
        # connections, which then survive restarts and are shared by replicas.
        self._token_store = token_store
        self._states = {name: self._new_state(name, oauth, owner_user_id) for name, oauth in oauth_by_server.items()}

    @staticmethod
    def _new_state(server_name: str, oauth: McpOAuthConfig, owner_user_id: str | None) -> _OAuthState:
        state = _OAuthState(config=oauth.model_copy(deep=True))
        if oauth.grant_type == "refresh_token":
            state.store_key = McpOAuthTokenKey.for_server(server_name, owner_user_id)
            state.fingerprint = oauth_config_fingerprint(oauth)
            state.request_fingerprint = oauth_token_request_fingerprint(oauth)
        return state

    @classmethod
    def from_extensions_config(
        cls,
        extensions_config: ExtensionsConfig,
        *,
        shared_manager: OAuthTokenManager | None = None,
        owner_user_id: str | None = None,
        token_store: McpOAuthTokenStore | None = None,
    ) -> OAuthTokenManager:
        """Build a manager, optionally reusing already-validated connection state.

        The durable runtime supplies ``shared_manager`` only after validating
        the deployment snapshot. Personal connections must never use it; they
        pass their ``owner_user_id`` instead, which keys their stored tokens.
        """
        oauth_by_server: dict[str, McpOAuthConfig] = {}
        for server_name, server_config in extensions_config.get_enabled_mcp_servers().items():
            if server_config.oauth and server_config.oauth.enabled:
                oauth_by_server[server_name] = server_config.oauth
        manager = cls(oauth_by_server, owner_user_id=owner_user_id, token_store=token_store)
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
        token = state.token
        if token and not self._is_expiring(token, oauth) and state.unsaved_base_version is None:
            return self._authorization_value(token, server_name)

        lock = state.lock
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
            store = self._token_store or get_mcp_oauth_token_store()
            token = state.token
            if token and not self._is_expiring(token, oauth):
                if state.unsaved_base_version is not None and store is not None:
                    await self._retry_unsaved_rotation(state, store)
                return self._authorization_value(token, server_name)

            fresh = None
            try:
                if store is not None and state.store_key is not None:
                    try:
                        fresh = await self._refresh_shared(state, store, server_name)
                    except McpOAuthTokenKeyUnavailable:
                        logger.warning("Keeping OAuth tokens for MCP server '%s' in this process only: the credentials key cannot be loaded", server_name)
                if fresh is None:
                    fresh = await self._fetch_token(oauth)
                    logger.info(f"Refreshed OAuth access token for MCP server: {server_name}")
            except _RefreshTokenRejected as exc:
                logger.warning("OAuth refresh token for MCP server '%s' was rejected (invalid_grant); the connection needs a new refresh token", server_name)
                raise McpOAuthReauthorizationRequired(_reauthorization_message(server_name, stored_chain_unreadable=exc.stored_chain_unreadable)) from exc.__cause__
            state.token = fresh
            return self._authorization_value(fresh, server_name)
        finally:
            lock.release()

    async def _refresh_shared(self, state: _OAuthState, store: McpOAuthTokenStore, server_name: str) -> _OAuthToken:
        """Adopt a peer's token from the shared row, or refresh once for every process.

        Runs under the connection's process lock. The row is re-read first,
        since a peer (another replica, or this process before a restart) may
        already hold a newer token. A refresh is claimed with a lease plus a
        compare-and-set on the row's version and never holds a row lock across
        the token request; the lease is renewed while the request runs, because
        HTTP timeouts bound each I/O wait rather than the whole request. While
        a peer holds the lease, the row is polled until its token lands or the
        lease expires. The refreshed tokens, including a rotated refresh token,
        are written back under the claim; a rotation the store missed stays
        pending and is written back before anything older is used.
        """
        key, fingerprint, request_fingerprint, oauth = state.store_key, state.fingerprint, state.request_fingerprint, state.config
        assert key is not None and fingerprint is not None and request_fingerprint is not None
        # A waiter must outlast a live holder, which may renew its lease for
        # up to REFRESH_MAX_SECONDS; a dead holder's lease expires sooner.
        deadline = time.monotonic() + oauth_store.REFRESH_MAX_SECONDS + oauth_store.REFRESH_LEASE_SECONDS
        while True:
            version, stored, unreadable = await asyncio.to_thread(store.load, key, fingerprint=fingerprint, request_fingerprint=request_fingerprint)
            if state.unsaved_base_version is not None and version != state.unsaved_base_version:
                # A peer stored a newer chain after this process's rotation.
                state.unsaved_base_version = None
            if state.unsaved_base_version is not None:
                # The row still holds the refresh token this process consumed;
                # store the live one first, then continue from the row.
                if await self._store_unsaved_rotation(state, store, version):
                    continue
            else:
                if stored is not None:
                    # The row continues this chain; without one (or under another
                    # fingerprint) the configured seed is the refresh token.
                    oauth.refresh_token = stored.refresh_token
                    if stored.access_token and stored.expires_at is not None:
                        token = _OAuthToken(access_token=stored.access_token, token_type=stored.token_type or oauth.default_token_type, expires_at=stored.expires_at)
                        if not self._is_expiring(token, oauth):
                            return token
                lease_owner = await asyncio.to_thread(store.claim, key, fingerprint=fingerprint, expected_version=version)
                if lease_owner is not None:
                    break
            if time.monotonic() >= deadline:
                raise McpOAuthTokenStoreUnavailable(f"Timed out waiting for another DeerFlow process to refresh the OAuth token for MCP server '{server_name}'")
            await asyncio.sleep(oauth_store.REFRESH_POLL_SECONDS)

        # A claim on a missing row inserts it at version 0.
        base_version = 0 if version is None else version
        used_refresh_token = oauth.refresh_token
        renewal = asyncio.create_task(self._renew_lease(store, key, lease_owner, server_name), name=f"oauth-lease-renewal:{server_name}")
        try:
            async with asyncio.timeout(oauth_store.REFRESH_MAX_SECONDS):
                fresh = await self._fetch_token(oauth)
        except asyncio.CancelledError:
            # A cancelled caller cannot await the release; hand it to a worker
            # rather than make every peer wait out the lease.
            asyncio.get_running_loop().run_in_executor(None, self._release_quietly, store, key, lease_owner)
            raise
        except Exception as exc:
            await asyncio.to_thread(self._release_quietly, store, key, lease_owner)
            if isinstance(exc, _RefreshTokenRejected):
                exc.stored_chain_unreadable = unreadable
            if isinstance(exc, TimeoutError):
                raise RuntimeError(f"The OAuth token request for MCP server '{server_name}' did not finish within {oauth_store.REFRESH_MAX_SECONDS:g} seconds") from None
            raise
        finally:
            renewal.cancel()
        logger.info(f"Refreshed OAuth access token for MCP server: {server_name}")
        try:
            saved = await asyncio.to_thread(
                store.save,
                key,
                lease_owner=lease_owner,
                fingerprint=fingerprint,
                request_fingerprint=request_fingerprint,
                access_token=fresh.access_token,
                token_type=fresh.token_type,
                expires_at=fresh.expires_at,
                refresh_token=oauth.refresh_token or "",
                rotated=oauth.refresh_token != used_refresh_token,
            )
        except McpOAuthTokenStoreUnavailable:
            # Logged by the store. Free the claim so the pending rotation (or a
            # peer) need not wait out the lease once the database answers again.
            saved = False
            await asyncio.to_thread(self._release_quietly, store, key, lease_owner)
        if saved:
            state.unsaved_base_version = None
        else:
            # The token is valid for this process, but peers still read the
            # refresh token it consumed: keep the new one pending.
            state.unsaved_base_version = base_version
            state.unsaved_retry_at = time.monotonic() + _UNSAVED_ROTATION_RETRY_SECONDS
            logger.warning("The new OAuth token for MCP server '%s' could not be stored; this process keeps it and retries storing it before other processes refresh again", server_name)
        return fresh

    async def _store_unsaved_rotation(self, state: _OAuthState, store: McpOAuthTokenStore, version: int | None) -> bool:
        """Write the pending rotation over the row it was refreshed from; ``False`` while a peer holds the lease."""
        key, oauth, token = state.store_key, state.config, state.token
        assert key is not None and state.fingerprint is not None and state.request_fingerprint is not None
        if token is None:
            state.unsaved_base_version = None
            return True
        lease_owner = await asyncio.to_thread(store.claim, key, fingerprint=state.fingerprint, expected_version=version)
        if lease_owner is None:
            return False
        try:
            saved = await asyncio.to_thread(
                store.save,
                key,
                lease_owner=lease_owner,
                fingerprint=state.fingerprint,
                request_fingerprint=state.request_fingerprint,
                access_token=token.access_token,
                token_type=token.token_type,
                expires_at=token.expires_at,
                refresh_token=oauth.refresh_token or "",
                rotated=True,
            )
        except McpOAuthTokenStoreUnavailable:
            await asyncio.to_thread(self._release_quietly, store, key, lease_owner)
            raise
        if saved:
            state.unsaved_base_version = None
        return saved

    async def _retry_unsaved_rotation(self, state: _OAuthState, store: McpOAuthTokenStore) -> None:
        """While the local token is still valid, retry storing a missed rotation now and then.

        Until it is stored, a peer whose token expires first would refresh with
        the consumed refresh token. Best effort: failures wait for the next try.
        """
        if time.monotonic() < state.unsaved_retry_at:
            return
        state.unsaved_retry_at = time.monotonic() + _UNSAVED_ROTATION_RETRY_SECONDS
        key = state.store_key
        assert key is not None and state.fingerprint is not None and state.request_fingerprint is not None
        try:
            version, _stored, _unreadable = await asyncio.to_thread(store.load, key, fingerprint=state.fingerprint, request_fingerprint=state.request_fingerprint)
            if version != state.unsaved_base_version:
                state.unsaved_base_version = None
                return
            await self._store_unsaved_rotation(state, store, version)
        except McpOAuthTokenStoreUnavailable:
            pass  # Logged by the store.

    async def _renew_lease(self, store: McpOAuthTokenStore, key: McpOAuthTokenKey, lease_owner: str, server_name: str) -> None:
        """Keep the claim's lease alive while its token request runs (cancelled when it ends)."""
        while True:
            await asyncio.sleep(oauth_store.REFRESH_LEASE_SECONDS / 3)
            try:
                renewed = await asyncio.to_thread(store.renew, key, lease_owner)
            except McpOAuthTokenStoreUnavailable:
                continue  # Logged by the store; the next tick retries.
            if not renewed:
                logger.warning("The refresh lease for MCP server '%s' expired while its token request was running; another process may refresh too", server_name)
                return

    @staticmethod
    def _release_quietly(store: McpOAuthTokenStore, key: McpOAuthTokenKey, lease_owner: str) -> None:
        try:
            store.release(key, lease_owner)
        except McpOAuthTokenStoreUnavailable:
            pass  # Logged by the store; the lease expires on its own.

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
            if oauth.grant_type == "refresh_token" and _is_invalid_grant(response):
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _RefreshTokenRejected() from exc
            response.raise_for_status()
            payload = response.json()

        access_token = payload.get(oauth.token_field)
        if not access_token:
            raise ValueError(f"OAuth token response missing '{oauth.token_field}'")

        # Persist a rotated refresh_token so subsequent refreshes use the latest
        # value. This updates our private runtime copy only — neither the parsed
        # extensions config nor extensions_config.json; the shared token store,
        # when installed, receives it from ``_refresh_shared``. Providers that rotate
        # refresh tokens (Auth0, Okta, Google, etc.) return a new refresh_token on
        # each refresh; discarding it makes the next refresh fail with invalid_grant.
        if oauth.grant_type == "refresh_token":
            rotated = payload.get("refresh_token")
            if isinstance(rotated, str) and rotated:
                oauth.refresh_token = rotated

        token_type = str(payload.get(oauth.token_type_field, oauth.default_token_type) or oauth.default_token_type)

        expires_in_raw = payload.get(oauth.expires_in_field, _DEFAULT_TOKEN_LIFETIME_SECONDS)
        try:
            expires_in = int(expires_in_raw)
        except (TypeError, ValueError, OverflowError):
            # ``OverflowError``: ``json.loads`` accepts ``Infinity``/``NaN``, and
            # ``int()`` rejects a non-finite float. Treat it like any other
            # unusable value instead of failing the whole token fetch.
            expires_in = _DEFAULT_TOKEN_LIFETIME_SECONDS
        now = datetime.now(UTC)
        try:
            expires_at = now + timedelta(seconds=max(expires_in, 1))
        except OverflowError:
            # Either timedelta construction or datetime addition can overflow.
            # Let the arithmetic enforce its exact range, avoiding a rounded
            # total_seconds() ceiling, and use the same instant for fallback.
            expires_at = now + timedelta(seconds=_DEFAULT_TOKEN_LIFETIME_SECONDS)
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
    server_names: Collection[str] | None = None,
) -> dict[str, str]:
    """Get initial OAuth Authorization headers for MCP server connections."""
    token_manager = token_manager or OAuthTokenManager.from_extensions_config(extensions_config)
    if not token_manager.has_oauth_servers():
        return {}

    headers: dict[str, str] = {}
    requested = set(server_names) if server_names is not None else None
    for server_name in token_manager.oauth_server_names():
        if requested is not None and server_name not in requested:
            continue
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

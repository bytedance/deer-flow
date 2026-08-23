"""Per-user credential injection for shared MCP servers.

One configured HTTP/SSE MCP server can serve several DeerFlow users, each
authenticated to the remote service with their own credential. A server opts in
by declaring a ``user_auth`` block (:class:`McpUserScopedAuthConfig`) mapping
DeerFlow user ids to credential header values. On every tool call the
interceptor resolves the authenticated user and rewrites the configured header
via ``request.override(headers=...)`` — the same per-call mechanism the OAuth
interceptor uses.

The server entry's static ``headers`` are used only for startup tool discovery
(``tools/list``); they never authenticate a user's tool call when ``user_auth``
is enabled for that server, except under an explicit ``on_missing:
"passthrough"`` opt-out.

Fail-closed by default: an unmapped user (including the anonymous
``DEFAULT_USER_ID`` fallback), or a mapped credential whose ``$ENV_VAR``
reference resolved to an empty string, gets an actionable ``ToolException``
instead of another user's credential or the discovery credential.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpUserScopedAuthConfig
from deerflow.runtime.user_context import resolve_runtime_user_id

logger = logging.getLogger(__name__)


def _current_runtime() -> Any | None:
    """Best-effort access to the LangGraph runtime for the current tool call.

    ``get_runtime()`` raises outside a runtime context (embedded clients, unit
    tests, discovery paths); ``resolve_runtime_user_id`` accepts ``None`` and
    falls back to LangGraph auth config and the request-scoped user
    ContextVar, so failures here reduce accuracy but never crash the call.
    """
    try:
        from langgraph.runtime import get_runtime

        return get_runtime()
    except Exception:
        return None


def build_user_scoped_auth_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    """Build a tool interceptor injecting per-user credentials, or ``None``.

    Returns ``None`` when no enabled server declares an enabled ``user_auth``
    block, so callers can skip registration entirely (mirrors
    ``build_oauth_tool_interceptor``).
    """
    user_auth_by_server: dict[str, McpUserScopedAuthConfig] = {}
    for server_name, server_config in extensions_config.get_enabled_mcp_servers().items():
        if server_config.user_auth is None or not server_config.user_auth.enabled:
            continue
        if server_config.type not in ("sse", "http"):
            # A stdio server has no HTTP headers: the pooled stdio path forwards
            # rewritten headers as call meta, never a transport header, so the
            # credential would go nowhere while deny errors still fired for
            # unmapped users. Warn-and-skip matches the existing convention for
            # transport/config mismatches (e.g. tool_call_timeout on non-stdio).
            logger.warning(
                "MCP server '%s' declares user_auth but uses the '%s' transport; user-scoped credentials only apply to 'sse'/'http' servers — ignoring user_auth for this server",
                server_name,
                server_config.type,
            )
            continue
        user_auth_by_server[server_name] = server_config.user_auth

    if not user_auth_by_server:
        return None

    async def user_scoped_auth_interceptor(request: Any, handler: Any) -> Any:
        user_auth = user_auth_by_server.get(request.server_name)
        if user_auth is None:
            return await handler(request)

        # Prefer the runtime attached to the request (set by the adapter when
        # the call originates inside a graph); fall back to the ambient
        # LangGraph runtime, then to resolve_runtime_user_id's own chain
        # (LangGraph auth config → request-scoped user ContextVar → default).
        runtime = getattr(request, "runtime", None)
        if runtime is None:
            runtime = _current_runtime()
        user_id = resolve_runtime_user_id(runtime)
        # Empty string covers a `$ENV_VAR` reference whose variable was unset:
        # ExtensionsConfig.resolve_env_variables stores "" for those, and an
        # empty credential must fail closed rather than send an empty header.
        credential = user_auth.users.get(user_id, "")
        if not credential:
            if user_auth.on_missing == "passthrough":
                return await handler(request)
            logger.warning(
                "Denied MCP tool call to server '%s': no user-scoped credential for user '%s'",
                request.server_name,
                user_id,
            )
            # The resolved id is included so the operator can copy the exact
            # ``users`` key: it differs by deployment path (a safe-slug like
            # ``alice-example-com-ab12cd34`` via LangGraph auth, a raw user
            # UUID via the embedded Gateway). It is the caller's own id, so
            # surfacing it leaks nothing across users.
            raise ToolException(
                f"No credential is configured for your account (user id '{user_id}') on MCP server '{request.server_name}'. Ask the operator to add this exact id to that server's user_auth.users map (or set its environment variable)."
            )

        updated_headers = dict(request.headers or {})
        updated_headers[user_auth.header] = credential
        return await handler(request.override(headers=updated_headers))

    return user_scoped_auth_interceptor

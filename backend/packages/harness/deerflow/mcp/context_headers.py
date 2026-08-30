"""Per-request credential injection for shared MCP servers.

``user_auth`` binds a credential to a *configured* DeerFlow user, which forces
one MCP server entry per credential when the credential is chosen by the caller
at request time (multi-tenant gateways, per-run API keys). This module closes
that gap: a server opts in by declaring a ``headers_from_context`` block
(:class:`McpContextHeadersConfig`) mapping HTTP header names to keys of the run
request's ``config.context.secrets`` carrier. On every tool call the interceptor
resolves the mapping from the live run context and rewrites those headers via
``request.override(headers=...)`` — the same per-call mechanism the OAuth and
user-scoped auth interceptors use.

The secret values arrive out-of-band with the run request and stay there: they
are never rendered into the prompt, the tool arguments, or trace payloads (see
``runtime/secret_context.py``). Only the *names* live in the config file, so no
credential is written to disk or returned by the config API.

Registered last in ``mcp/interceptors.py``, so for a server declaring several
credential sources the per-request value wins the final header — interceptors
wrap outermost-first, and the later-registered one runs closer to the transport.
Header names are written case-insensitively through ``mcp/headers.py``, so a
mapped ``Authorization`` replaces a static ``authorization`` rather than putting
a second copy of the field on the wire ahead of it.

Fail-closed by default: a mapped key that is absent from the request secrets
(or resolved empty) gets an actionable ``ToolException`` rather than silently
falling back to the server's static discovery credential, which in a
multi-tenant deployment would send one tenant's request under another
tenant's authority. ``on_missing: "passthrough"`` is the explicit opt-out.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpContextHeadersConfig
from deerflow.mcp.headers import apply_header_overrides, header_spellings
from deerflow.runtime.secret_context import extract_request_secrets

logger = logging.getLogger(__name__)


def _current_runtime() -> Any | None:
    """Best-effort access to the LangGraph runtime for the current tool call.

    ``get_runtime()`` raises outside a runtime context (embedded clients, unit
    tests, discovery paths). Mirrors ``mcp/user_scoped_auth.py``: a failure here
    only means the request carries no resolvable secrets, which the caller then
    handles through ``on_missing``.
    """
    try:
        from langgraph.runtime import get_runtime

        return get_runtime()
    except Exception:
        return None


def _request_secrets(request: Any) -> dict[str, str]:
    """Return the run request's ``config.context.secrets``, or ``{}``.

    Prefer the runtime attached to the request: LangGraph's tool node injects it
    into any tool parameter named ``runtime``, which covers both the pooled
    stdio wrapper and ``langchain_mcp_adapters``' own HTTP/SSE tool. Fall back to
    the ambient runtime for call paths outside a tool node.

    Deliberately not read from ``langgraph.config.get_config()``: the run context
    is carried on the runtime, not on the ``RunnableConfig`` propagated to child
    runnables, so ``get_config().get("context")`` is ``None`` inside a tool call.
    """
    runtime = getattr(request, "runtime", None)
    if runtime is None:
        runtime = _current_runtime()
    return extract_request_secrets(getattr(runtime, "context", None))


def build_context_headers_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    """Build a tool interceptor injecting per-request headers, or ``None``.

    Returns ``None`` when no enabled server declares a usable
    ``headers_from_context`` block, so callers can skip registration entirely
    (mirrors ``build_oauth_tool_interceptor`` / ``build_user_scoped_auth_interceptor``).
    """
    mapping_by_server: dict[str, McpContextHeadersConfig] = {}
    # The server's static header spellings, so a mapped name that differs from
    # the configured one only in case still *replaces* it at the adapter's
    # case-sensitive connection merge instead of riding alongside it.
    spellings_by_server: dict[str, dict[str, str]] = {}
    for server_name, server_config in extensions_config.get_enabled_mcp_servers().items():
        context_headers = server_config.headers_from_context
        if context_headers is None or not context_headers.enabled or not context_headers.headers:
            continue
        if server_config.type not in ("sse", "http"):
            # A stdio server has no HTTP headers: the pooled stdio path forwards
            # rewritten headers as call meta, never a transport header, so the
            # credential would go nowhere while deny errors still fired for
            # runs that carry no secrets. Warn-and-skip matches user_auth.
            logger.warning(
                "MCP server '%s' declares headers_from_context but uses the '%s' transport; request-scoped headers only apply to 'sse'/'http' servers — ignoring headers_from_context for this server",
                server_name,
                server_config.type,
            )
            continue
        if server_config.task_toolsets:
            # Submitting a durable task happens inside the Agent run and carries
            # the request secrets; the later status/cancel polls do not, because
            # the task runtime drives them long after that run ended. Those calls
            # deliberately skip this interceptor (see McpTaskToolCaller), so the
            # background half authenticates with the server's own credentials.
            logger.warning(
                "MCP server '%s' declares both headers_from_context and task_toolsets; background task status/cancel polls run outside an Agent run and will use this server's static/OAuth credentials instead of the per-request headers",
                server_name,
            )
        mapping_by_server[server_name] = context_headers
        spellings_by_server[server_name] = header_spellings(server_config.headers)

    if not mapping_by_server:
        return None

    async def context_headers_interceptor(request: Any, handler: Any) -> Any:
        context_headers = mapping_by_server.get(request.server_name)
        if context_headers is None:
            return await handler(request)

        secrets = _request_secrets(request)
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for header_name, secret_key in context_headers.headers.items():
            # Empty string covers a caller-side `$ENV_VAR` that was unset: an
            # empty credential must fail closed rather than send an empty header.
            value = secrets.get(secret_key, "")
            if value:
                resolved[header_name] = value
            else:
                missing.append(secret_key)

        if missing and context_headers.on_missing == "deny":
            missing_keys = ", ".join(sorted(missing))
            logger.warning(
                "Denied MCP tool call to server '%s': request context is missing secret(s) %s",
                request.server_name,
                missing_keys,
            )
            # Only the configured *key names* are surfaced — they already live in
            # the config file, so this leaks nothing the operator has not written
            # down, while telling the caller exactly what to send.
            raise ToolException(f"MCP server '{request.server_name}' needs request-scoped credential(s) {missing_keys}. Send them in config.context.secrets, or set this server's headers_from_context.on_missing to 'passthrough'.")

        if not resolved:
            return await handler(request)

        updated_headers = apply_header_overrides(
            request.headers,
            resolved,
            spellings=spellings_by_server.get(request.server_name),
        )
        return await handler(request.override(headers=updated_headers))

    return context_headers_interceptor

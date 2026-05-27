"""Inject DeerFlow user context into outbound MCP tool calls."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

# HTTP/SSE MCP servers can read these headers to identify the caller.
HEADER_USER_ID = "X-DeerFlow-User-Id"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve_run_context(request: Any | None = None) -> dict[str, str]:
    """Read user_id from config['configurable'] with minimal fallback."""
    del request  # keep signature stable for interceptor calls
    try:
        from langgraph.config import get_config
    except ImportError:
        return {"user_id": get_effective_user_id()}

    config = _as_dict(get_config() or {})
    configurable = _as_dict(config.get("configurable"))
    configurable_context = _as_dict(configurable.get("context"))

    user_id = configurable_context.get("user_id") or configurable.get("user_id") or get_effective_user_id()
    resolved: dict[str, str] = {"user_id": str(user_id)}

    user_source = "configurable.context.user_id" if configurable_context.get("user_id") else ("configurable.user_id" if configurable.get("user_id") else "fallback:get_effective_user_id")
    logger.info(
        "MCP auth resolve context: user_id=%s user_source=%s configurable_keys=%s configurable_context_keys=%s",
        resolved["user_id"],
        user_source,
        sorted(configurable.keys()),
        sorted(configurable_context.keys()),
    )
    return resolved


def build_auth_interceptor() -> Callable[[Any, Any], Awaitable[Any]]:
    """Build an MCP tool interceptor that stamps user context on each call."""

    async def auth_interceptor(request: Any, handler: Any) -> Any:
        run_ctx = _resolve_run_context(request)
        headers = dict(request.headers or {})
        headers[HEADER_USER_ID] = run_ctx.get("user_id", get_effective_user_id())

        user_id = run_ctx.get("user_id")
        logged_headers = {key: ("***" if key.lower() == "authorization" else value) for key, value in headers.items() if key.startswith("X-DeerFlow-") or key.lower() == "authorization"}
        logger.info(
            "MCP auth interceptor: user_id=%s server=%s tool=%s headers=%s",
            user_id,
            getattr(request, "server_name", None),
            getattr(request, "name", None),
            logged_headers,
        )

        return await handler(request.override(headers=headers))

    return auth_interceptor

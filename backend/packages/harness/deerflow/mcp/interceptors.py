"""Shared construction of MCP tool-call interceptors."""

from __future__ import annotations

import logging
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.oauth import build_oauth_tool_interceptor
from deerflow.mcp.user_scoped_auth import build_user_scoped_auth_interceptor
from deerflow.reflection import resolve_variable

logger = logging.getLogger(__name__)


def build_mcp_tool_interceptors(
    extensions_config: ExtensionsConfig,
    *,
    oauth_builder: Any = build_oauth_tool_interceptor,
    user_auth_builder: Any = build_user_scoped_auth_interceptor,
    resolver: Any = resolve_variable,
    target_logger: logging.Logger = logger,
) -> list[Any]:
    """Build OAuth, user-scoped auth, then configured custom MCP interceptors."""
    interceptors: list[Any] = []
    oauth_interceptor = oauth_builder(extensions_config)
    if oauth_interceptor is not None:
        interceptors.append(oauth_interceptor)

    # After OAuth so a server declaring both gets the per-user credential:
    # interceptors wrap outermost-first, so the later-registered user-scoped
    # override runs closer to the transport and wins the final header value.
    user_auth_interceptor = user_auth_builder(extensions_config)
    if user_auth_interceptor is not None:
        interceptors.append(user_auth_interceptor)

    raw_paths = (extensions_config.model_extra or {}).get("mcpInterceptors")
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    elif not isinstance(raw_paths, list):
        if raw_paths is not None:
            target_logger.warning(
                "mcpInterceptors must be a list of strings, got %s; skipping",
                type(raw_paths).__name__,
            )
        raw_paths = []

    for interceptor_path in raw_paths:
        try:
            builder = resolver(interceptor_path)
            interceptor = builder()
            if callable(interceptor):
                interceptors.append(interceptor)
                target_logger.info("Loaded MCP interceptor: %s", interceptor_path)
            elif interceptor is not None:
                target_logger.warning(
                    "Builder %s returned non-callable %s; skipping",
                    interceptor_path,
                    type(interceptor).__name__,
                )
        except Exception:
            target_logger.warning(
                f"Failed to load MCP interceptor {interceptor_path}",
                exc_info=True,
            )
    return interceptors


def compose_tool_interceptors(interceptors: list[Any], base_handler: Any) -> Any:
    """Compose interceptors onion-style around ``base_handler``: first = outermost.

    The later-registered interceptor runs closer to the transport, so its
    header writes win over earlier ones — the property user-scoped auth relies
    on to override an OAuth-injected credential. This is the single wrap
    convention; the session-pool tool path composes through here so tests that
    pin the override property exercise the production composition.
    """
    handler = base_handler
    for interceptor in reversed(interceptors):
        outer = handler

        async def wrapped(req: Any, _i: Any = interceptor, _h: Any = outer) -> Any:
            return await _i(req, _h)

        handler = wrapped
    return handler

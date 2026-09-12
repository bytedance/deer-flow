"""MCP interceptor that injects the current DeerFlow user identity as the
AnyConnect ``userId`` on ``execute_action`` calls.

When enabled (listed in ``extensions_config.json`` → ``mcpInterceptors``),
every ``execute_action`` request routed to the ``connectors`` MCP server
automatically receives a ``userId`` argument set to the current
DeerFlow user id.  This lets a single AnyConnect instance serve multiple
DeerFlow users, each with their own OAuth connections and API keys.

Usage — add to ``extensions_config.json``:

.. code-block:: json

    {
      "mcpInterceptors": [
        "deerflow.mcp.connector_interceptor:build_interceptor"
      ],
      "mcpServers": {
        "connectors": {
          "enabled": true,
          "type": "http",
          "url": "http://localhost:3000/mcp",
          "headers": {
            "Authorization": "Bearer oct_..."
          },
          "description": "AnyConnect — 1000+ SaaS integrations"
        }
      }
    }
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The server *name* in extensions_config.json → mcpServers that this
# interceptor should apply to.  Only ``execute_action`` calls routed to
# this server are augmented.
_CONNECTORS_SERVER_NAME = "connectors"


def build_interceptor():
    """Return an async ``(request, handler) → result`` interceptor callable.

    The interceptor is a plain async function so it matches the existing
    ``tool_interceptors`` convention in :mod:`deerflow.mcp.tools` and does
    not require any extra builder protocol.
    """

    async def inject_user_id(request, handler):
        """Inject ``userId`` into AnyConnect ``execute_action`` calls."""

        # Only touch our own server's execute_action.
        if request.server_name != _CONNECTORS_SERVER_NAME or request.name != "execute_action":
            return await handler(request)

        # Resolve the current user from the runtime context.
        # Always overwrite — never trust a model-supplied userId.
        from deerflow.runtime.user_context import resolve_runtime_user_id

        runtime = getattr(request, "runtime", None)
        user_id = resolve_runtime_user_id(runtime)
        if user_id:
            request.args["userId"] = user_id
            logger.debug(
                "Injected userId=%s for %s.%s",
                user_id,
                request.server_name,
                request.name,
            )

        return await handler(request)

    return inject_user_id

"""No-argument custom MCP interceptor for trusted native task submissions."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from langchain_core.tools import ToolException

from deerflow.config.extensions_config import get_extensions_config
from deerflow.mcp_scope import runtime_thread_incarnation
from deerflow.runtime.user_context import resolve_runtime_user_id
from ecs_executor.scope import SCOPE_HEADER, mint_execution_scope


def _current_runtime() -> Any | None:
    try:
        from langgraph.config import get_config
        from langgraph.runtime import get_runtime

        runtime = get_runtime()
        # Ambient Runtime lacks ToolRuntime.config. Supply the native config
        # view only for lifecycle metadata validation; identity stays on the
        # current runtime context/server_info, never config.context.
        return SimpleNamespace(context=runtime.context, server_info=getattr(runtime, "server_info", None), config=get_config())
    except RuntimeError:
        return None


def build_execution_scope_interceptor() -> Any:
    """Build through native ``mcpInterceptors`` using operator environment config.

    Only exact selected raw submit calls are signed. Background status/cancel
    remain in the normal driver and require persisted-owner authorization on
    the remote service. Configuration errors contain no secret values.
    """
    server_name = os.environ.get("ECS_EXECUTOR_SCOPE_SERVER", "")
    submit_tool = os.environ.get("ECS_EXECUTOR_SCOPE_SUBMIT_TOOL", "")
    audience = os.environ.get("ECS_EXECUTOR_SCOPE_AUDIENCE", "")
    secret = os.environ.get("ECS_EXECUTOR_SCOPE_SECRET", "").encode("utf-8")
    if not all((server_name, submit_tool, audience)) or len(secret) < 32:
        raise ValueError("Execution scope requires server, submit tool, audience and a >=32-byte operator secret")
    server = get_extensions_config().get_enabled_mcp_servers().get(server_name)
    if server is None or server.type != "http":
        raise ValueError("Execution scope requires an enabled HTTP MCP server")
    # The ordinary adapter merges static headers case-sensitively. Reserved
    # fields must have only this interceptor as their source, including discovery.
    if any(name.lower() == SCOPE_HEADER.lower() for name in (server.headers or {})):
        raise ValueError("Execution scope header must not be configured statically")

    async def execution_scope_interceptor(request: Any, handler: Any) -> Any:
        if request.server_name != server_name or request.name != submit_tool:
            return await handler(request)
        try:
            runtime = getattr(request, "runtime", None)
            if runtime is None:
                runtime = _current_runtime()
            context = getattr(runtime, "context", None)
            # Require the gateway's actual user context before using the native
            # resolver; its legacy unauthenticated default must never sign work.
            if not isinstance(context, dict) or not isinstance(context.get("user_id"), str) or not context["user_id"]:
                raise ValueError("Missing authenticated runtime context")
            token = mint_execution_scope(
                secret=secret,
                audience=audience,
                user_id=resolve_runtime_user_id(runtime),
                thread_id=context.get("thread_id"),
                incarnation=runtime_thread_incarnation(runtime),
                run_id=context.get("run_id"),
                operation="submit",
                arguments=request.args,
            )
        except (ValueError, RuntimeError, TypeError):
            raise ToolException("MCP submit requires a valid trusted execution scope") from None
        headers = {name: value for name, value in (request.headers or {}).items() if name.lower() != SCOPE_HEADER.lower()}
        headers[SCOPE_HEADER] = token
        return await handler(request.override(headers=headers))

    return execution_scope_interceptor

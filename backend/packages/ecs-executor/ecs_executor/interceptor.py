"""No-argument custom MCP interceptor for trusted native task submissions."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from langchain_core.tools import ToolException

from deerflow.authz.workspace import get_current_workspace
from deerflow.config.extensions_config import get_extensions_config
from deerflow.mcp_scope import runtime_thread_incarnation
from deerflow.runtime.user_context import require_current_user, resolve_runtime_user_id
from ecs_executor.scope import SCOPE_HEADER, mint_execution_scope, mint_management_scope


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

    Exact submit calls bind trusted runtime context. Background status/cancel
    stay in the native driver and sign only authenticated persisted owner/task
    identity; the remote service rechecks its stored owner. Configuration errors contain no secret values.
    """
    server_name = os.environ.get("ECS_EXECUTOR_SCOPE_SERVER", "")
    submit_tool = os.environ.get("ECS_EXECUTOR_SCOPE_SUBMIT_TOOL", "")
    status_tool = os.environ.get("ECS_EXECUTOR_SCOPE_STATUS_TOOL", "")
    cancel_tool = os.environ.get("ECS_EXECUTOR_SCOPE_CANCEL_TOOL", "")
    audience = os.environ.get("ECS_EXECUTOR_SCOPE_AUDIENCE", "")
    secret = os.environ.get("ECS_EXECUTOR_SCOPE_SECRET", "").encode("utf-8")
    if not all((server_name, submit_tool, audience)) or len(secret) < 32:
        raise ValueError("Execution scope requires server, submit tool, audience and a >=32-byte operator secret")
    server = get_extensions_config().get_enabled_mcp_servers().get(server_name)
    if server is None or server.type != "http":
        raise ValueError("Execution scope requires an enabled HTTP MCP server")
    management = {status_tool: "status", cancel_tool: "cancel"} if status_tool and cancel_tool else {}
    if bool(status_tool) != bool(cancel_tool):
        raise ValueError("Both status and cancel tool names must be configured")
    if management:
        if len({submit_tool, status_tool, cancel_tool}) != 3 or not server.user_auth or not server.user_auth.enabled or server.user_auth.on_missing != "deny":
            raise ValueError("Execution management requires exact tools and enabled fail-closed user_auth")
        if not any(group.submit_tool == submit_tool and group.status_tool == status_tool and group.cancel_tool == cancel_tool for group in server.task_toolsets):
            raise ValueError("Execution management must match a native task_toolsets binding")
    # The ordinary adapter merges static headers case-sensitively. Reserved
    # fields must have only this interceptor as their source, including discovery.
    if any(name.lower() == SCOPE_HEADER.lower() for name in (server.headers or {})):
        raise ValueError("Execution scope header must not be configured statically")

    async def execution_scope_interceptor(request: Any, handler: Any) -> Any:
        if request.server_name != server_name or request.name not in {submit_tool, *management}:
            return await handler(request)
        if request.name in management:
            try:
                if set(request.args) != {"task_id"}:
                    raise ValueError("Invalid task identity")
                token = mint_management_scope(secret=secret, audience=audience, user_id=require_current_user().id, task_id=request.args["task_id"], operation=management[request.name])
            except (ValueError, RuntimeError, TypeError):
                raise ToolException("MCP management requires a valid authenticated task owner") from None
            headers = {name: value for name, value in (request.headers or {}).items() if name.lower() != SCOPE_HEADER.lower()}
            headers[SCOPE_HEADER] = token
            return await handler(request.override(headers=headers))
        try:
            runtime = getattr(request, "runtime", None)
            if runtime is None:
                runtime = _current_runtime()
            context = getattr(runtime, "context", None)
            # Require the gateway's actual user context before using the native
            # resolver; its legacy unauthenticated default must never sign work.
            if not isinstance(context, dict) or not isinstance(context.get("user_id"), str) or not context["user_id"]:
                raise ValueError("Missing authenticated runtime context")
            workspace_context = context.get("workspace_context")
            if workspace_context is None and (get_current_workspace() is not None or any(key in context for key in ("workspace_id", "actor_user_id", "membership_version", "policy_version"))):
                raise ValueError("Missing trusted workspace execution identity")
            token = mint_execution_scope(
                secret=secret,
                audience=audience,
                user_id=resolve_runtime_user_id(runtime),
                thread_id=context.get("thread_id"),
                incarnation=runtime_thread_incarnation(runtime),
                run_id=context.get("run_id"),
                operation="submit",
                arguments=request.args,
                workspace_context=workspace_context,
            )
        except (ValueError, RuntimeError, TypeError):
            raise ToolException("MCP submit requires a valid trusted execution scope") from None
        headers = {name: value for name, value in (request.headers or {}).items() if name.lower() != SCOPE_HEADER.lower()}
        headers[SCOPE_HEADER] = token
        return await handler(request.override(headers=headers))

    return execution_scope_interceptor

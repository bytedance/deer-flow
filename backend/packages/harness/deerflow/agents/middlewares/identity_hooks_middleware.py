"""Optional identity-provider MCP hooks at thread/session start.

Fires configured ``sessionStart`` tool calls against an external MCP server
(e.g. Lithtrix) without importing provider code into DeerFlow core. Failures
are logged and ignored so research is not blocked by substrate outages.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import get_session_pool
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


def _resolve_thread_id(runtime: Runtime) -> str | None:
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is not None:
        return str(thread_id)
    try:
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        return str(thread_id) if thread_id is not None else None
    except RuntimeError:
        return None


async def run_session_start_hooks(
    *,
    config: ExtensionsConfig,
    thread_id: str,
    user_id: str,
) -> None:
    """Invoke configured sessionStart MCP tools (non-fatal on errors)."""
    hooks = config.identity_hooks
    if hooks is None or not hooks.enabled:
        return

    enabled_servers = config.get_enabled_mcp_servers()
    server_config = enabled_servers.get(hooks.mcp_server_ref)
    if server_config is None:
        logger.warning(
            "identity_hooks_skip server=%s reason=disabled_or_missing",
            hooks.mcp_server_ref,
        )
        return

    if not hooks.session_start:
        return

    try:
        connection = build_server_params(hooks.mcp_server_ref, server_config)
    except Exception:
        logger.exception(
            "identity_hooks_connection_failed server=%s",
            hooks.mcp_server_ref,
        )
        return

    scope_key = f"{user_id}:{thread_id}"
    pool = get_session_pool()
    try:
        session = await pool.get_session(hooks.mcp_server_ref, scope_key, connection)
    except Exception:
        logger.exception(
            "identity_hooks_session_failed server=%s",
            hooks.mcp_server_ref,
        )
        return

    call_kwargs: dict[str, Any] = {}
    if server_config.tool_call_timeout:
        call_kwargs["read_timeout_seconds"] = timedelta(seconds=server_config.tool_call_timeout)

    for call in hooks.session_start:
        try:
            await session.call_tool(call.tool, call.args, **call_kwargs)
        except Exception:
            logger.exception("identity_hooks_call_failed tool=%s", call.tool)
            # non-fatal — research continues


class IdentityHooksMiddleware(AgentMiddleware[AgentState]):
    """Fire optional identity-provider MCP hooks once per thread."""

    def __init__(self, extensions_config: ExtensionsConfig | None = None) -> None:
        super().__init__()
        self._extensions_config = extensions_config
        self._fired_threads: BoundedDict[str, bool] = BoundedDict(1000)

    def _config(self) -> ExtensionsConfig:
        return self._extensions_config or get_extensions_config()

    async def _maybe_run_hooks(self, runtime: Runtime) -> None:
        thread_id = _resolve_thread_id(runtime)
        if thread_id is None:
            logger.debug("identity_hooks_skip reason=missing_thread_id")
            return
        if self._fired_threads.get(thread_id):
            return

        self._fired_threads[thread_id] = True
        user_id = get_effective_user_id() or "default"
        await run_session_start_hooks(
            config=self._config(),
            thread_id=thread_id,
            user_id=user_id,
        )

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._maybe_run_hooks(runtime))
            return None
        # Event loop is running — abefore_agent handles async path.
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        await self._maybe_run_hooks(runtime)
        return None

"""Load only the caller's personal tools; never publish them in the global cache."""

from __future__ import annotations

import asyncio
import functools

from langchain_core.tools import ToolException

from deerflow.mcp.user_config import load_user_mcp_config
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.mcp_metadata import get_mcp_source
from deerflow.tools.sync import make_sync_tool_wrapper


def _guard(tool, owner: str, server_name: str):
    original = tool.coroutine

    @functools.wraps(original)
    async def invoke(*args, **kwargs):
        if resolve_runtime_user_id(kwargs.get("runtime")) != owner:
            raise ToolException("This MCP connection belongs to another user")
        current = await asyncio.to_thread(load_user_mcp_config, owner)
        if server_name not in current.get_enabled_mcp_servers():
            raise ToolException("This personal MCP connection was changed, disabled or removed; start a new run")
        return await original(*args, **kwargs)

    return tool.model_copy(update={"coroutine": invoke, "func": make_sync_tool_wrapper(invoke, tool.name)})


async def _load(owner: str, config):
    from deerflow.mcp.tools import get_mcp_tools

    tools = await get_mcp_tools(config, personal_user_id=owner)
    return [_guard(tool, owner, source["server_name"]) for tool in tools if (source := get_mcp_source(tool))]


def get_user_mcp_tools():
    """Discover from one literal snapshot, with an ownership check on every call.

    Deliberately keep personal discovery out of the deployment's singleton
    cache. Stdio session reuse remains owner/thread/revision-scoped.
    """
    owner = resolve_runtime_user_id(None)
    config = load_user_mcp_config(owner)
    if not config.get_enabled_mcp_servers():
        return [], config
    tools = make_sync_tool_wrapper(_load, "personal MCP discovery")(owner, config)
    return tools, config

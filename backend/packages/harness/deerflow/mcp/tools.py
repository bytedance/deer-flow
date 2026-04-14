"""Load MCP tools using langchain-mcp-adapters."""

import asyncio
import atexit
import concurrent.futures
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers

logger = logging.getLogger(__name__)

# Global thread pool for sync tool invocation in async environments
_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="mcp-sync-tool")

# Register shutdown hook for the global executor
atexit.register(lambda: _SYNC_TOOL_EXECUTOR.shutdown(wait=False))

_SERVER_TOOL_SEPARATOR = "_"


def _make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    """Build a synchronous wrapper for an asynchronous tool coroutine.

    Args:
        coro: The tool's asynchronous coroutine.
        tool_name: Name of the tool (for logging).

    Returns:
        A synchronous function that correctly handles nested event loops.
    """

    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                # Use global executor to avoid nested loop issues and improve performance
                future = _SYNC_TOOL_EXECUTOR.submit(asyncio.run, coro(*args, **kwargs))
                return future.result()
            else:
                return asyncio.run(coro(*args, **kwargs))
        except Exception as e:
            logger.error(f"Error invoking MCP tool '{tool_name}' via sync wrapper: {e}", exc_info=True)
            raise

    return sync_wrapper


def split_prefixed_mcp_tool_name(
    tool_name: str,
    server_names: list[str],
) -> tuple[str, str] | None:
    """Split a prefixed MCP tool name into server + raw tool name."""
    for server_name in sorted(server_names, key=len, reverse=True):
        prefix = f"{server_name}{_SERVER_TOOL_SEPARATOR}"
        if tool_name.startswith(prefix):
            return server_name, tool_name[len(prefix) :]
    return None


def _filter_tools_for_extensions_config(
    tools: list[BaseTool],
    extensions_config: ExtensionsConfig,
) -> list[BaseTool]:
    server_names = list(extensions_config.get_enabled_mcp_servers().keys())
    if not server_names:
        return []

    filtered: list[BaseTool] = []
    for tool in tools:
        split_name = split_prefixed_mcp_tool_name(tool.name, server_names)
        if split_name is None:
            filtered.append(tool)
            continue

        server_name, raw_tool_name = split_name
        if extensions_config.is_mcp_tool_enabled(server_name, raw_tool_name):
            filtered.append(tool)
        else:
            logger.info(
                "Skipping disabled MCP tool '%s' from server '%s'",
                raw_tool_name,
                server_name,
            )

    return filtered


async def discover_mcp_tools_by_server(
    extensions_config: ExtensionsConfig,
) -> dict[str, dict[str, str]]:
    """Discover currently exposed MCP tools grouped by server."""
    tools = await _load_mcp_tools(extensions_config, apply_tool_filters=False)
    discovered: dict[str, dict[str, str]] = {
        server_name: {} for server_name in extensions_config.get_enabled_mcp_servers()
    }
    server_names = list(discovered.keys())

    for tool in tools:
        split_name = split_prefixed_mcp_tool_name(tool.name, server_names)
        if split_name is None:
            continue

        server_name, raw_tool_name = split_name
        discovered[server_name][raw_tool_name] = tool.description or ""

    return {
        server_name: dict(sorted(tool_map.items()))
        for server_name, tool_map in discovered.items()
    }


async def _load_mcp_tools(
    extensions_config: ExtensionsConfig,
    *,
    apply_tool_filters: bool,
) -> list[BaseTool]:
    """Load tools from all enabled MCP servers for the provided config."""
    servers_config = build_servers_config(extensions_config)

    if not servers_config:
        logger.info("No enabled MCP servers configured")
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning(
            "langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters",
        )
        return []

    # Inject initial OAuth headers for server connections (tool discovery/session init)
    initial_oauth_headers = await get_initial_oauth_headers(extensions_config)
    for server_name, auth_header in initial_oauth_headers.items():
        if server_name not in servers_config:
            continue
        if servers_config[server_name].get("transport") in ("sse", "http"):
            existing_headers = dict(servers_config[server_name].get("headers", {}))
            existing_headers["Authorization"] = auth_header
            servers_config[server_name]["headers"] = existing_headers

    tool_interceptors = []
    oauth_interceptor = build_oauth_tool_interceptor(extensions_config)
    if oauth_interceptor is not None:
        tool_interceptors.append(oauth_interceptor)

    client = MultiServerMCPClient(
        servers_config,
        tool_interceptors=tool_interceptors,
        tool_name_prefix=True,
    )
    tools = await client.get_tools()

    if apply_tool_filters:
        tools = _filter_tools_for_extensions_config(tools, extensions_config)

    return tools


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when initializing MCP tools.
    extensions_config = ExtensionsConfig.from_file()

    try:
        logger.info(
            "Initializing MCP client with %s server(s)",
            len(extensions_config.get_enabled_mcp_servers()),
        )

        tools = await _load_mcp_tools(
            extensions_config,
            apply_tool_filters=True,
        )
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

        # Patch tools to support sync invocation, as deerflow client streams synchronously
        for tool in tools:
            if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
                tool.func = _make_sync_tool_wrapper(tool.coroutine, tool.name)

        return tools

    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}", exc_info=True)
        return []

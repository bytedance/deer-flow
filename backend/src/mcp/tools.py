"""Load MCP tools using langchain-mcp-adapters."""

import asyncio
import logging

from langchain_core.tools import BaseTool

from src.config.extensions_config import ExtensionsConfig
from src.mcp.client import build_servers_config
from src.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers

logger = logging.getLogger(__name__)


async def _load_server_tools(
    server_name: str,
    server_params: dict,
    tool_interceptors: list,
) -> list[BaseTool]:
    """Load tools from a single MCP server."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    try:
        client = MultiServerMCPClient({server_name: server_params}, tool_interceptors=tool_interceptors)
        tools = await client.get_tools()
        logger.info(f"Loaded {len(tools)} tool(s) from MCP server '{server_name}'")
        return tools
    except Exception as e:
        logger.error(f"Failed to load tools from MCP server '{server_name}': {e}")
        return []


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Loads tools from each server independently and in parallel so that one
    failing server does not prevent tools from other servers from being loaded.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: F401
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters")
        return []

    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when initializing MCP tools.
    extensions_config = ExtensionsConfig.from_file()
    servers_config = build_servers_config(extensions_config)

    if not servers_config:
        logger.info("No enabled MCP servers configured")
        return []

    logger.info(f"Initializing MCP tools from {len(servers_config)} server(s)")

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

    # Load all servers in parallel for faster initialization
    results = await asyncio.gather(
        *[
            _load_server_tools(server_name, server_params, tool_interceptors)
            for server_name, server_params in servers_config.items()
        ]
    )

    all_tools: list[BaseTool] = []
    for tools in results:
        all_tools.extend(tools)

    logger.info(f"Successfully loaded {len(all_tools)} tool(s) from MCP servers")
    return all_tools


async def get_mcp_tools_by_server() -> dict[str, list[BaseTool]]:
    """Get tools from enabled MCP servers, grouped by server name.

    Same loading logic as ``get_mcp_tools`` but returns a dict mapping each
    server name to its list of tools instead of a flat list.

    Returns:
        Dict mapping server_name to list of tools from that server.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: F401
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters")
        return {}

    extensions_config = ExtensionsConfig.from_file()
    servers_config = build_servers_config(extensions_config)

    if not servers_config:
        logger.info("No enabled MCP servers configured")
        return {}

    logger.info(f"Initializing MCP tools (by server) from {len(servers_config)} server(s)")

    # Inject initial OAuth headers
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

    server_names = list(servers_config.keys())
    results = await asyncio.gather(
        *[
            _load_server_tools(name, servers_config[name], tool_interceptors)
            for name in server_names
        ]
    )

    by_server: dict[str, list[BaseTool]] = {}
    for name, tools in zip(server_names, results):
        if tools:
            by_server[name] = tools

    total = sum(len(t) for t in by_server.values())
    logger.info(f"Successfully loaded {total} tool(s) from {len(by_server)} MCP server(s) (by-server)")
    return by_server

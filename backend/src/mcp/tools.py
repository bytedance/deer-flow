"""Load MCP tools using langchain-mcp-adapters."""

import logging

from langchain_core.tools import BaseTool

from src.config.extensions_config import ExtensionsConfig
from src.mcp.client import build_servers_config
from src.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers

logger = logging.getLogger(__name__)


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Loads tools from each server independently so that one failing server
    does not prevent tools from other servers from being loaded.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
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

    all_tools: list[BaseTool] = []
    for server_name, server_params in servers_config.items():
        try:
            client = MultiServerMCPClient({server_name: server_params}, tool_interceptors=tool_interceptors)
            tools = await client.get_tools()
            all_tools.extend(tools)
            logger.info(f"Loaded {len(tools)} tool(s) from MCP server '{server_name}'")
        except Exception as e:
            logger.error(f"Failed to load tools from MCP server '{server_name}': {e}")

    logger.info(f"Successfully loaded {len(all_tools)} tool(s) from MCP servers")
    return all_tools

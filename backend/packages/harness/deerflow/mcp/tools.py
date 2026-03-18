"""Load MCP tools using langchain-mcp-adapters."""

import asyncio
import logging

from langchain_core.tools import BaseTool

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers

# Timeout for fetching all MCP tools (seconds). To prevent slow/unreachable
# servers from blocking agent initialization indefinitely.
MCP_SERVER_CONNECT_TIMEOUT = 20

logger = logging.getLogger(__name__)


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

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

    try:
        # Create the multi-server MCP client
        logger.info(f"Initializing MCP client with {len(servers_config)} server(s)")

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

        client = MultiServerMCPClient(servers_config, tool_interceptors=tool_interceptors, tool_name_prefix=True)

        # Get all tools from all servers, with a hard timeout to prevent a
        # slow/unreachable server from blocking agent initialization indefinitely.
        try:
            tools = await asyncio.wait_for(client.get_tools(), timeout=MCP_SERVER_CONNECT_TIMEOUT)
        except TimeoutError:
            logger.error(
                f"MCP get_tools() timed out after {MCP_SERVER_CONNECT_TIMEOUT}s. "
                "One or more configured MCP servers may be unreachable. Returning empty tool list."
            )
            return []
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

        # Filter out disabled tools per server
        disabled_tool_names: set[str] = set()
        for server_config in extensions_config.get_enabled_mcp_servers().values():
            disabled_tool_names.update(server_config.disabled_tools)

        if disabled_tool_names:
            tools = [t for t in tools if t.name not in disabled_tool_names]
            logger.info(f"After filtering disabled tools, {len(tools)} tool(s) remain")

        return tools

    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}", exc_info=True)
        return []

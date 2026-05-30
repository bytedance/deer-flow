"""Load MCP tools using langchain-mcp-adapters with stdio session pooling."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_config

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers
from deerflow.mcp.session_pool import get_session_pool
from deerflow.reflection import resolve_variable
from deerflow.tools.sync import make_sync_tool_wrapper
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


def _extract_thread_id(runtime: Runtime | None) -> str:
    """Extract thread_id from the injected tool runtime or LangGraph config."""
    if runtime is not None:
        tid = runtime.context.get("thread_id") if runtime.context else None
        if tid is not None:
            return str(tid)
        config = runtime.config or {}
        tid = config.get("configurable", {}).get("thread_id")
        if tid is not None:
            return str(tid)

    try:
        tid = get_config().get("configurable", {}).get("thread_id")
        return str(tid) if tid is not None else "default"
    except RuntimeError:
        return "default"


def _convert_call_tool_result(call_tool_result: Any) -> Any:
    """Convert an MCP CallToolResult to the LangChain ``content_and_artifact`` format.

    Implements the same conversion logic as the adapter without relying on
    the private ``langchain_mcp_adapters.tools._convert_call_tool_result`` symbol.
    """
    from langchain_core.messages import ToolMessage
    from langchain_core.messages.content import create_file_block, create_image_block, create_text_block
    from langchain_core.tools import ToolException
    from mcp.types import EmbeddedResource, ImageContent, ResourceLink, TextContent, TextResourceContents

    # Pass ToolMessage through directly (interceptor short-circuit).
    if isinstance(call_tool_result, ToolMessage):
        return call_tool_result, None

    # Pass LangGraph Command through directly when langgraph is installed.
    try:
        from langgraph.types import Command

        if isinstance(call_tool_result, Command):
            return call_tool_result, None
    except ImportError:
        # langgraph is optional; if unavailable, continue with standard MCP content conversion.
        pass

    # Convert MCP content blocks to LangChain content blocks.
    lc_content = []
    for item in call_tool_result.content:
        if isinstance(item, TextContent):
            lc_content.append(create_text_block(text=item.text))
        elif isinstance(item, ImageContent):
            lc_content.append(create_image_block(base64=item.data, mime_type=item.mimeType))
        elif isinstance(item, ResourceLink):
            mime = item.mimeType or None
            if mime and mime.startswith("image/"):
                lc_content.append(create_image_block(url=str(item.uri), mime_type=mime))
            else:
                lc_content.append(create_file_block(url=str(item.uri), mime_type=mime))
        elif isinstance(item, EmbeddedResource):
            from mcp.types import BlobResourceContents

            res = item.resource
            if isinstance(res, TextResourceContents):
                lc_content.append(create_text_block(text=res.text))
            elif isinstance(res, BlobResourceContents):
                mime = res.mimeType or None
                if mime and mime.startswith("image/"):
                    lc_content.append(create_image_block(base64=res.blob, mime_type=mime))
                else:
                    lc_content.append(create_file_block(base64=res.blob, mime_type=mime))
            else:
                lc_content.append(create_text_block(text=str(res)))
        else:
            lc_content.append(create_text_block(text=str(item)))

    if call_tool_result.isError:
        error_parts = [item["text"] for item in lc_content if isinstance(item, dict) and item.get("type") == "text"]
        raise ToolException("\n".join(error_parts) if error_parts else str(lc_content))

    artifact = None
    if call_tool_result.structuredContent is not None:
        artifact = {"structured_content": call_tool_result.structuredContent}

    return lc_content, artifact


def _make_session_pool_tool(
    tool: BaseTool,
    server_name: str,
    connection: dict[str, Any],
    tool_interceptors: list[Any] | None = None,
) -> BaseTool:
    """Wrap an MCP tool so it reuses a persistent session from the pool.

    Replaces the per-call session creation with pool-managed sessions scoped
    by ``(server_name, thread_id)``.  This ensures stateful MCP servers (e.g.
    Playwright) keep their state across tool calls within the same thread.

    The configured ``tool_interceptors`` (OAuth, custom) are preserved and
    applied on every call before invoking the pooled session.
    """
    # Strip the server-name prefix to recover the original MCP tool name.
    original_name = tool.name
    prefix = f"{server_name}_"
    if original_name.startswith(prefix):
        original_name = original_name[len(prefix) :]

    pool = get_session_pool()

    async def call_with_persistent_session(
        runtime: Runtime | None = None,
        **arguments: Any,
    ) -> Any:
        thread_id = _extract_thread_id(runtime)
        session = await pool.get_session(server_name, thread_id, connection)

        if tool_interceptors:
            from langchain_mcp_adapters.interceptors import MCPToolCallRequest

            async def base_handler(request: MCPToolCallRequest) -> Any:
                return await session.call_tool(request.name, request.args)

            handler = base_handler
            for interceptor in reversed(tool_interceptors):
                outer = handler

                async def wrapped(req: Any, _i: Any = interceptor, _h: Any = outer) -> Any:
                    return await _i(req, _h)

                handler = wrapped

            request = MCPToolCallRequest(
                name=original_name,
                args=arguments,
                server_name=server_name,
                runtime=runtime,
            )
            call_tool_result = await handler(request)
        else:
            call_tool_result = await session.call_tool(original_name, arguments)

        return _convert_call_tool_result(call_tool_result)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=call_with_persistent_session,
        response_format="content_and_artifact",
        metadata=tool.metadata,
    )


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Tools using stdio transport are wrapped with persistent-session logic so
    consecutive calls within the same thread reuse the same MCP session.
    HTTP/SSE tools are returned unwrapped to avoid cross-task TaskGroup
    cleanup errors.

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

        tool_interceptors: list[Any] = []
        oauth_interceptor = build_oauth_tool_interceptor(extensions_config)
        if oauth_interceptor is not None:
            tool_interceptors.append(oauth_interceptor)

        # Load custom interceptors declared in extensions_config.json
        # Format: "mcpInterceptors": ["pkg.module:builder_func", ...]
        raw_interceptor_paths = (extensions_config.model_extra or {}).get("mcpInterceptors")
        if isinstance(raw_interceptor_paths, str):
            raw_interceptor_paths = [raw_interceptor_paths]
        elif not isinstance(raw_interceptor_paths, list):
            if raw_interceptor_paths is not None:
                logger.warning(f"mcpInterceptors must be a list of strings, got {type(raw_interceptor_paths).__name__}; skipping")
            raw_interceptor_paths = []
        for interceptor_path in raw_interceptor_paths:
            try:
                builder = resolve_variable(interceptor_path)
                interceptor = builder()
                if callable(interceptor):
                    tool_interceptors.append(interceptor)
                    logger.info(f"Loaded MCP interceptor: {interceptor_path}")
                elif interceptor is not None:
                    logger.warning(f"Builder {interceptor_path} returned non-callable {type(interceptor).__name__}; skipping")
            except Exception as e:
                logger.warning(
                    f"Failed to load MCP interceptor {interceptor_path}: {e}",
                    exc_info=True,
                )

        client = MultiServerMCPClient(
            servers_config,
            tool_interceptors=tool_interceptors,
            tool_name_prefix=True,
        )

        # Get all tools from all servers (discovers tool definitions via
        # temporary sessions – the persistent-session wrapping is applied below).
        tools = await client.get_tools()
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

        # Wrap each tool with persistent-session logic.
        # Only pool stdio sessions. HTTP/SSE transports use anyio TaskGroups
        # internally which cannot be closed from a different async task, so
        # pooling them causes RuntimeError on cleanup (see #3203).
        wrapped_tools: list[BaseTool] = []
        for tool in tools:
            tool_server: str | None = None
            for name in servers_config:
                if tool.name.startswith(f"{name}_"):
                    tool_server = name
                    break

            if tool_server is not None:
                transport = servers_config[tool_server].get("transport", "stdio")
                if transport == "stdio":
                    wrapped_tools.append(_make_session_pool_tool(tool, tool_server, servers_config[tool_server], tool_interceptors))
                else:
                    wrapped_tools.append(tool)
            else:
                wrapped_tools.append(tool)

        # Patch tools to support sync invocation, as deerflow client streams synchronously
        for tool in wrapped_tools:
            if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
                tool.func = make_sync_tool_wrapper(tool.coroutine, tool.name)

        return wrapped_tools

    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}", exc_info=True)
        return []

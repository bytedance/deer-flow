"""Load MCP tools via langchain-mcp-adapters; every MCP tool call uses a per-call session."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers
from deerflow.reflection import resolve_variable
from deerflow.tools.sync import make_sync_tool_wrapper
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


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


def _make_per_call_mcp_tool(
    tool: BaseTool,
    server_name: str,
    connection: dict[str, Any],
    tool_interceptors: list[Any] | None = None,
) -> BaseTool:
    """Wrap a stdio MCP tool so each call uses a fresh, self-contained session.

    Every invocation opens a session, calls the tool, and closes the session
    inside a single coroutine — i.e. a single asyncio task. This respects
    anyio's invariant that a stdio ``ClientSession``/``stdio_client`` task group
    must be entered (``__aenter__``) and exited (``__aexit__``) in the same task
    (issue #3379). A shared/pooled session created in one task and torn down
    from another raised ``RuntimeError: Attempted to exit cancel scope in a
    different task than it was entered in``.

    Why wrap stdio at all when HTTP/SSE tools are returned unwrapped? Only to
    forward interceptor-injected headers: ``langchain-mcp-adapters`` forwards
    modified headers to HTTP/SSE connections natively but drops them for stdio,
    so we forward them via MCP call ``meta`` (PR #3294). The session lifecycle
    itself is identical to the library's default per-call behavior.
    """
    # Strip the server-name prefix to recover the original MCP tool name.
    original_name = tool.name
    prefix = f"{server_name}_"
    if original_name.startswith(prefix):
        original_name = original_name[len(prefix) :]

    async def call_with_per_call_session(
        runtime: Runtime | None = None,
        **arguments: Any,
    ) -> Any:
        from langchain_mcp_adapters.sessions import create_session

        # Open + call + close within this one coroutine (one task) so the stdio
        # cancel scope is entered and exited in the same task.
        # Only Exception is captured: BaseException (e.g. CancelledError) must
        # propagate through the session context as-is.
        captured_exc: Exception | None = None
        call_tool_result: Any = None
        async with create_session(connection) as session:
            await session.initialize()
            try:
                if tool_interceptors:
                    from langchain_mcp_adapters.interceptors import MCPToolCallRequest

                    async def base_handler(request: MCPToolCallRequest) -> Any:
                        # Preserve interceptor-injected headers for stdio MCP calls
                        # by forwarding them through MCP call meta.
                        call_kwargs: dict[str, Any] = {}
                        if request.headers:
                            if isinstance(request.headers, Mapping):
                                call_kwargs["meta"] = {"headers": dict(request.headers)}
                            else:
                                logger.warning("Ignoring MCP interceptor headers with unsupported type: %s", type(request.headers).__name__)
                        return await session.call_tool(request.name, request.args, **call_kwargs)

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
            except Exception as exc:  # noqa: BLE001
                # Re-raise outside the session context: the MCP SDK task group can
                # otherwise re-wrap the error into an ExceptionGroup on exit.
                captured_exc = exc

        if captured_exc is not None:
            raise captured_exc
        return _convert_call_tool_result(call_tool_result)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=call_with_per_call_session,
        response_format="content_and_artifact",
        metadata=tool.metadata,
    )


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Each MCP tool call opens, uses, and closes its own session inside a single
    task — no pooling/sharing across tasks (issue #3379). stdio tools get a thin
    per-call wrapper ONLY to forward interceptor-injected headers via MCP call
    ``meta`` (PR #3294); HTTP/SSE tools forward headers natively and are returned
    unwrapped.

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
        # temporary, in-task sessions; the returned tools create a fresh session
        # per call on their own).
        tools = await client.get_tools()
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

        # stdio tools are wrapped ONLY to forward interceptor-injected headers via
        # MCP call meta (langchain-mcp-adapters forwards headers to HTTP/SSE
        # natively but drops them for stdio — PR #3294). The wrapper keeps the
        # library's per-call session lifecycle: open + call + close inside one
        # task, so the anyio cancel scope is entered and exited in the same task.
        # Sessions are NOT pooled/shared across tasks — doing so raised
        # "Attempted to exit cancel scope in a different task" on cleanup (#3379).
        # HTTP/SSE tools already forward headers natively, so they pass through.
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
                    wrapped_tools.append(_make_per_call_mcp_tool(tool, tool_server, servers_config[tool_server], tool_interceptors))
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

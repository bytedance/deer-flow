"""PTC (Programmatic Tool Calling) proxy router.

Receives HTTP requests from sandbox Python code and forwards them to
the appropriate MCP server.  API keys and secrets stay on the host —
they never enter the sandbox environment.

Flow:
    Sandbox code  →  POST /api/ptc/call  →  Gateway validates HMAC token
                                          →  Connects to target MCP server
                                          →  Invokes tool, returns result
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ptc.session_token import validate_session_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ptc", tags=["ptc"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PTCCallRequest(BaseModel):
    """Request body for a PTC tool invocation."""

    token: str = Field(description="HMAC session token for authentication")
    server_name: str = Field(description="MCP server name (e.g. 'postgres', 'ncbi')")
    tool_name: str = Field(description="Tool name on the MCP server")
    arguments: dict = Field(default_factory=dict, description="Tool call arguments")


class PTCCallResponse(BaseModel):
    """Response body for a PTC tool invocation."""

    success: bool
    result: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/call", response_model=PTCCallResponse)
async def ptc_call(request: PTCCallRequest) -> PTCCallResponse:
    """Execute a tool on an MCP server on behalf of sandbox code.

    Validates the HMAC session token, connects to the specified MCP server,
    invokes the requested tool, and returns the result.
    """
    # 1. Validate session token
    thread_id = validate_session_token(request.token)
    if thread_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired PTC session token")

    # 2. Load MCP server configuration
    try:
        from src.config.extensions_config import ExtensionsConfig
        from src.mcp.client import build_servers_config

        extensions_config = ExtensionsConfig.from_file()
        servers_config = build_servers_config(extensions_config)
    except Exception as e:
        logger.error("PTC: failed to load MCP server config: %s", e)
        return PTCCallResponse(success=False, error=f"Failed to load server configuration: {e}")

    if request.server_name not in servers_config:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown MCP server: '{request.server_name}'. "
            f"Available servers: {', '.join(sorted(servers_config.keys())) or 'none'}",
        )

    server_params = servers_config[request.server_name]

    # 3. Connect to the MCP server and invoke the tool
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        async with MultiServerMCPClient({request.server_name: server_params}) as client:
            tools = await client.get_tools()
            tool_map = {t.name: t for t in tools}

            if request.tool_name not in tool_map:
                available = ", ".join(sorted(tool_map.keys())) or "none"
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown tool '{request.tool_name}' on server '{request.server_name}'. "
                    f"Available tools: {available}",
                )

            tool = tool_map[request.tool_name]
            result = await tool.ainvoke(request.arguments)

            # Convert result to string
            if isinstance(result, str):
                result_str = result
            else:
                import json

                result_str = json.dumps(result, default=str)

            logger.info(
                "PTC: thread=%s server=%s tool=%s → success (%d chars)",
                thread_id,
                request.server_name,
                request.tool_name,
                len(result_str),
            )
            return PTCCallResponse(success=True, result=result_str)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "PTC: thread=%s server=%s tool=%s → error: %s",
            thread_id,
            request.server_name,
            request.tool_name,
            e,
        )
        return PTCCallResponse(success=False, error=str(e))

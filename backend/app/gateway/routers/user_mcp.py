"""Authenticated users' tenant-private MCP server configuration API."""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, status

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.mcp import (
    McpConfigResponse,
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    McpServerStateUpdateRequest,
    _mask_server_config,
    _merge_preserving_secrets,
    _validate_mcp_update_request,
)
from deerflow.config.extensions_config import McpServerConfig, extensions_config_write_lock
from deerflow.mcp.cache import reset_user_mcp_tools_cache
from deerflow.mcp.user_config import load_user_mcp_config, save_user_mcp_config

router = APIRouter(prefix="/api/user/mcp", tags=["user-mcp"])


def validate_user_mcp_update(body: McpConfigUpdateRequest) -> None:
    """Apply the shared command checks plus tenant-safe remote URL rules."""
    _validate_mcp_update_request(body)
    for name, server in body.mcp_servers.items():
        if (server.type or "stdio").lower() == "stdio":
            continue
        parsed = urlparse(server.url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP server '{name}' requires an absolute HTTP(S) URL.",
            )
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"MCP server '{name}' cannot target private or local addresses.",
                ) from None
        else:
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"MCP server '{name}' cannot target private or local addresses.",
                )


def _serialize(servers: dict[str, McpServerConfig]) -> McpConfigResponse:
    return McpConfigResponse(mcp_servers={name: _mask_server_config(McpServerConfigResponse(**server.model_dump())) for name, server in servers.items()})


def _replace_user_servers(user_id: str, body: McpConfigUpdateRequest) -> dict[str, McpServerConfig]:
    with extensions_config_write_lock:
        existing = load_user_mcp_config(user_id).mcp_servers
        merged: dict[str, McpServerConfig] = {}
        for name, incoming in body.mcp_servers.items():
            prior = existing.get(name)
            if prior is not None:
                incoming = _merge_preserving_secrets(incoming, McpServerConfigResponse(**prior.model_dump()))
            merged[name] = McpServerConfig.model_validate(incoming.model_dump())
        return save_user_mcp_config(user_id, merged).mcp_servers


def _set_user_server_state(user_id: str, body: McpServerStateUpdateRequest) -> dict[str, McpServerConfig]:
    with extensions_config_write_lock:
        config = load_user_mcp_config(user_id)
        server = config.mcp_servers.get(body.server_name)
        if server is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MCP server '{body.server_name}' not found",
            )
        if body.enabled:
            validate_user_mcp_update(McpConfigUpdateRequest(mcp_servers={body.server_name: McpServerConfigResponse(**server.model_dump())}))
        server.enabled = body.enabled
        return save_user_mcp_config(user_id, config.mcp_servers).mcp_servers


@router.get("/config", response_model=McpConfigResponse)
async def get_user_mcp_config(request: Request) -> McpConfigResponse:
    user = await get_current_user_from_request(request)
    return _serialize(load_user_mcp_config(str(user.id)).mcp_servers)


@router.put("/config", response_model=McpConfigResponse)
async def update_user_mcp_config(request: Request, body: McpConfigUpdateRequest) -> McpConfigResponse:
    user = await get_current_user_from_request(request)
    validate_user_mcp_update(body)
    servers = await asyncio.to_thread(_replace_user_servers, str(user.id), body)
    reset_user_mcp_tools_cache(str(user.id))
    return _serialize(servers)


@router.patch("/config", response_model=McpConfigResponse)
async def update_user_mcp_server_state(request: Request, body: McpServerStateUpdateRequest) -> McpConfigResponse:
    user = await get_current_user_from_request(request)
    servers = await asyncio.to_thread(_set_user_server_state, str(user.id), body)
    reset_user_mcp_tools_cache(str(user.id))
    return _serialize(servers)

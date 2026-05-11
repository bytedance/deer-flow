"""CRUD API for tenant-level MCP server configurations (admin only)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_tenant_mcp_repo
from deerflow.persistence.agent.auth import is_tenant_admin
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants/{tenant_id}/mcp-servers", tags=["tenant-mcp-servers"])


class McpServerCreateRequest(BaseModel):
    server_name: str = Field(..., description="Unique server name within the tenant")
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    config: dict = Field(..., description="MCP server config (type, command/url, args, env, etc.)")
    enabled: bool = Field(default=True)


class McpServerUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    config: dict | None = Field(default=None)
    enabled: bool | None = Field(default=None)


class EnableRequest(BaseModel):
    enabled: bool


def _get_current_user_role(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "user"
    return getattr(user, "system_role", "user") or "user"


def _get_current_user_tenant(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "default"
    return getattr(user, "tenant_id", "default") or "default"


def _require_tenant_admin(request: Request, tenant_id: str) -> None:
    role = _get_current_user_role(request)
    if not is_tenant_admin(role):
        raise HTTPException(status_code=403, detail="Tenant admin privileges required")
    user_tenant = _get_current_user_tenant(request)
    if role == "tenant_admin" and user_tenant != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot manage MCP servers for a different tenant")


MCP_CONFIG_REQUIRED_FIELDS = {"type"}
MCP_CONFIG_VALID_TYPES = {"stdio", "sse", "http"}


def _validate_mcp_config(config: dict) -> None:
    """Basic validation of MCP server config structure."""
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="config must be a JSON object")
    server_type = config.get("type")
    if server_type not in MCP_CONFIG_VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"config.type must be one of: {', '.join(MCP_CONFIG_VALID_TYPES)}")
    if server_type == "stdio" and not config.get("command"):
        raise HTTPException(status_code=422, detail="stdio type requires 'command' field")
    if server_type in ("sse", "http") and not config.get("url"):
        raise HTTPException(status_code=422, detail=f"{server_type} type requires 'url' field")


@router.post("", summary="Create Tenant MCP Server")
async def create_tenant_mcp_server(
    tenant_id: str,
    body: McpServerCreateRequest,
    request: Request,
    repo=Depends(get_tenant_mcp_repo),
):
    _require_tenant_admin(request, tenant_id)
    if repo is None:
        raise HTTPException(status_code=503, detail="MCP server repository not available")

    _validate_mcp_config(body.config)

    user_id = get_effective_user_id()
    existing = await repo.get_by_name(tenant_id, body.server_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"MCP server '{body.server_name}' already exists in this tenant")

    return await repo.create(
        tenant_id=tenant_id,
        server_name=body.server_name,
        config=body.config,
        created_by=user_id,
        display_name=body.display_name,
        description=body.description,
        enabled=body.enabled,
    )


@router.get("", summary="List Tenant MCP Servers")
async def list_tenant_mcp_servers(
    tenant_id: str,
    request: Request,
    repo=Depends(get_tenant_mcp_repo),
):
    _require_tenant_admin(request, tenant_id)
    if repo is None:
        raise HTTPException(status_code=503, detail="MCP server repository not available")
    return await repo.list_by_tenant(tenant_id, include_disabled=True)


@router.get("/{server_name}", summary="Get Tenant MCP Server")
async def get_tenant_mcp_server(
    tenant_id: str,
    server_name: str,
    request: Request,
    repo=Depends(get_tenant_mcp_repo),
):
    _require_tenant_admin(request, tenant_id)
    if repo is None:
        raise HTTPException(status_code=503, detail="MCP server repository not available")
    server = await repo.get_by_name(tenant_id, server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
    return server


@router.put("/{server_name}", summary="Update Tenant MCP Server")
async def update_tenant_mcp_server(
    tenant_id: str,
    server_name: str,
    body: McpServerUpdateRequest,
    request: Request,
    repo=Depends(get_tenant_mcp_repo),
):
    _require_tenant_admin(request, tenant_id)
    if repo is None:
        raise HTTPException(status_code=503, detail="MCP server repository not available")

    existing = await repo.get_by_name(tenant_id, server_name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")

    update_fields = {k: v for k, v in body.model_dump().items() if v is not None}

    if "config" in update_fields:
        _validate_mcp_config(update_fields["config"])

    if update_fields:
        return await repo.update(tenant_id, server_name, **update_fields)
    return existing


@router.delete("/{server_name}", summary="Delete Tenant MCP Server")
async def delete_tenant_mcp_server(
    tenant_id: str,
    server_name: str,
    request: Request,
    repo=Depends(get_tenant_mcp_repo),
):
    _require_tenant_admin(request, tenant_id)
    if repo is None:
        raise HTTPException(status_code=503, detail="MCP server repository not available")

    deleted = await repo.delete(tenant_id, server_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
    return {"deleted": True}


@router.put("/{server_name}/enabled", summary="Enable/Disable Tenant MCP Server")
async def set_tenant_mcp_server_enabled(
    tenant_id: str,
    server_name: str,
    body: EnableRequest,
    request: Request,
    repo=Depends(get_tenant_mcp_repo),
):
    _require_tenant_admin(request, tenant_id)
    if repo is None:
        raise HTTPException(status_code=503, detail="MCP server repository not available")

    result = await repo.set_enabled(tenant_id, server_name, body.enabled)
    if not result:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
    return result

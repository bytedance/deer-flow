"""CRUD API for tenant-level agents (admin only)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_agent_permission_repo, get_agent_repo
from deerflow.persistence.agent.auth import is_tenant_admin
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants/{tenant_id}/agents", tags=["tenant-agents"])


class TenantAgentCreateRequest(BaseModel):
    name: str = Field(..., description="Agent name (hyphen-case)")
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    icon: str | None = Field(default=None)
    visibility: str = Field(default="tenant_public")
    model: str | None = Field(default=None)
    tool_groups: list[str] | None = Field(default=None)
    skills: list[str] | None = Field(default=None)
    mcp_servers: list[str] | None = Field(default=None)
    tags: list[str] | None = Field(default=None)
    soul: str = Field(default="")


class TenantAgentUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    icon: str | None = Field(default=None)
    visibility: str | None = Field(default=None)
    model: str | None = Field(default=None)
    tool_groups: list[str] | None = Field(default=None)
    skills: list[str] | None = Field(default=None)
    mcp_servers: list[str] | None = Field(default=None)
    tags: list[str] | None = Field(default=None)
    soul: str | None = Field(default=None)


class EnableRequest(BaseModel):
    enabled: bool


class PermissionsRequest(BaseModel):
    permissions: list[dict] = Field(..., description="List of {principal_type, principal_id}")


def _get_current_user_role(request: Request) -> str:
    """Extract system_role from the current authenticated user."""
    user = getattr(request.state, "user", None)
    if user is None:
        return "user"
    return getattr(user, "system_role", "user") or "user"


def _get_current_user_tenant(request: Request) -> str:
    """Extract tenant_id from the current authenticated user."""
    user = getattr(request.state, "user", None)
    if user is None:
        return "default"
    return getattr(user, "tenant_id", "default") or "default"


def _require_tenant_admin(request: Request, tenant_id: str) -> None:
    """Verify the current user is a tenant admin for the given tenant."""
    role = _get_current_user_role(request)
    if not is_tenant_admin(role):
        raise HTTPException(status_code=403, detail="Tenant admin privileges required")
    user_tenant = _get_current_user_tenant(request)
    if role == "tenant_admin" and user_tenant != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot manage agents for a different tenant")


@router.post("", summary="Create Tenant Agent")
async def create_tenant_agent(
    tenant_id: str,
    body: TenantAgentCreateRequest,
    request: Request,
    agent_repo=Depends(get_agent_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")

    user_id = get_effective_user_id()
    existing = await agent_repo.get_by_name(tenant_id, body.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists in this tenant")

    result = await agent_repo.create(
        tenant_id=tenant_id,
        name=body.name,
        created_by=user_id,
        display_name=body.display_name,
        description=body.description,
        icon=body.icon,
        visibility=body.visibility,
        model=body.model,
        tool_groups=body.tool_groups,
        skills=body.skills,
        mcp_servers=body.mcp_servers,
        tags=body.tags,
    )

    # Store SOUL.md to filesystem
    if body.soul:
        _write_tenant_agent_soul(tenant_id, body.name, body.soul)

    # Write config.yaml for filesystem-based discovery
    _write_tenant_agent_config(
        tenant_id, body.name,
        display_name=body.display_name,
        description=body.description,
        icon=body.icon,
        visibility=body.visibility,
        model=body.model,
        tool_groups=body.tool_groups,
        skills=body.skills,
        mcp_servers=body.mcp_servers,
        tags=body.tags,
    )

    return result


@router.get("", summary="List Tenant Agents")
async def list_tenant_agents(
    tenant_id: str,
    request: Request,
    agent_repo=Depends(get_agent_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")
    return await agent_repo.list_by_tenant(tenant_id, include_disabled=True)


@router.get("/{name}", summary="Get Tenant Agent")
async def get_tenant_agent(
    tenant_id: str,
    name: str,
    request: Request,
    agent_repo=Depends(get_agent_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")
    agent = await agent_repo.get_by_name(tenant_id, name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    agent["soul"] = _read_tenant_agent_soul(tenant_id, name)
    return agent


@router.put("/{name}", summary="Update Tenant Agent")
async def update_tenant_agent(
    tenant_id: str,
    name: str,
    body: TenantAgentUpdateRequest,
    request: Request,
    agent_repo=Depends(get_agent_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")

    existing = await agent_repo.get_by_name(tenant_id, name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    update_fields = {k: v for k, v in body.model_dump().items() if v is not None and k != "soul"}
    if update_fields:
        result = await agent_repo.update(tenant_id, name, **update_fields)
    else:
        result = existing

    if body.soul is not None:
        _write_tenant_agent_soul(tenant_id, name, body.soul)

    # Rewrite config.yaml with merged fields for filesystem-based discovery
    merged = {**existing, **update_fields}
    _write_tenant_agent_config(
        tenant_id, name,
        display_name=merged.get("display_name"),
        description=merged.get("description"),
        icon=merged.get("icon"),
        visibility=merged.get("visibility", "tenant_public"),
        model=merged.get("model"),
        tool_groups=merged.get("tool_groups"),
        skills=merged.get("skills"),
        mcp_servers=merged.get("mcp_servers"),
        tags=merged.get("tags"),
    )

    return result


@router.delete("/{name}", summary="Delete Tenant Agent")
async def delete_tenant_agent(
    tenant_id: str,
    name: str,
    request: Request,
    agent_repo=Depends(get_agent_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")

    deleted = await agent_repo.delete(tenant_id, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Clean up filesystem (config.yaml + SOUL.md)
    _delete_tenant_agent_dir(tenant_id, name)

    return {"deleted": True}


@router.put("/{name}/enabled", summary="Enable/Disable Tenant Agent")
async def set_tenant_agent_enabled(
    tenant_id: str,
    name: str,
    body: EnableRequest,
    request: Request,
    agent_repo=Depends(get_agent_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")

    result = await agent_repo.set_enabled(tenant_id, name, body.enabled)
    if not result:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return result


@router.post("/{name}/permissions", summary="Set Agent Permissions")
async def set_agent_permissions(
    tenant_id: str,
    name: str,
    body: PermissionsRequest,
    request: Request,
    agent_repo=Depends(get_agent_repo),
    perm_repo=Depends(get_agent_permission_repo),
):
    _require_tenant_admin(request, tenant_id)
    if agent_repo is None or perm_repo is None:
        raise HTTPException(status_code=503, detail="Agent repository not available")

    agent = await agent_repo.get_by_name(tenant_id, name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    return await perm_repo.set_permissions(agent["id"], body.permissions)


def _write_tenant_agent_soul(tenant_id: str, name: str, content: str) -> None:
    from deerflow.config.paths import get_paths

    paths = get_paths()
    soul_dir = paths.base_dir / "tenants" / tenant_id / "agents" / name
    soul_dir.mkdir(parents=True, exist_ok=True)
    (soul_dir / "SOUL.md").write_text(content, encoding="utf-8")


def _write_tenant_agent_config(tenant_id: str, name: str, *, display_name: str | None = None, description: str | None = None, icon: str | None = None, visibility: str = "tenant_public", model: str | None = None, tool_groups: list[str] | None = None, skills: list[str] | None = None, mcp_servers: list[str] | None = None, tags: list[str] | None = None) -> None:
    """Write a config.yaml for the tenant agent so filesystem-based discovery works."""
    import yaml

    from deerflow.config.paths import get_paths

    paths = get_paths()
    agent_dir = paths.base_dir / "tenants" / tenant_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    data: dict = {"name": name}
    if display_name:
        data["display_name"] = display_name
    if description:
        data["description"] = description
    if icon:
        data["icon"] = icon
    if visibility:
        data["visibility"] = visibility
    if model:
        data["model"] = model
    if tool_groups:
        data["tool_groups"] = tool_groups
    if skills:
        data["skills"] = skills
    if mcp_servers:
        data["mcp_servers"] = mcp_servers
    if tags:
        data["tags"] = tags

    (agent_dir / "config.yaml").write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


def _read_tenant_agent_soul(tenant_id: str, name: str) -> str | None:
    from deerflow.config.paths import get_paths

    paths = get_paths()
    soul_path = paths.base_dir / "tenants" / tenant_id / "agents" / name / "SOUL.md"
    if not soul_path.exists():
        return None
    return soul_path.read_text(encoding="utf-8").strip() or None


def _delete_tenant_agent_dir(tenant_id: str, name: str) -> None:
    """Remove the tenant agent's filesystem directory (config.yaml + SOUL.md)."""
    import shutil

    from deerflow.config.paths import get_paths

    paths = get_paths()
    agent_dir = paths.base_dir / "tenants" / tenant_id / "agents" / name
    if agent_dir.exists():
        shutil.rmtree(agent_dir, ignore_errors=True)

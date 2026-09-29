"""Capability discovery is public to authenticated users; mutations reuse existing policy."""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.capabilities import AdapterContext, InstallationList, list_installations, registry
from app.gateway.deps import get_config, get_current_user_from_request, require_admin_user
from deerflow.capabilities.catalog import PluginManifest, load_catalog
from deerflow.config.app_config import AppConfig
from deerflow.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_id: str
    name: str = Field(default="", max_length=128)
    configuration: dict[str, Any] = Field(default_factory=dict)
    scope: Literal["deployment", "user"] = "deployment"


@router.get("/catalog", response_model=list[PluginManifest])
async def catalog() -> list[PluginManifest]:
    return await asyncio.to_thread(load_catalog)


@router.get("/installations/{adapter}", response_model=InstallationList)
async def installations(adapter: str, request: Request, config: AppConfig = Depends(get_config), scope: Literal["deployment", "user", "all"] = "deployment") -> InstallationList:
    return await list_installations(adapter, request, config, scope)


@router.post("/installations", response_model=InstallationList)
async def install(body: InstallRequest, request: Request, config: AppConfig = Depends(get_config)) -> InstallationList:
    user_id = get_effective_user_id()
    if body.scope == "deployment":
        await require_admin_user(request, detail="Admin privileges required to install capabilities.")
    else:
        user_id = str((await get_current_user_from_request(request)).id)
    entries = await asyncio.to_thread(load_catalog)
    manifest = next((entry for entry in entries if entry.id == body.plugin_id), None)
    if manifest is None:
        raise HTTPException(404, "Plugin not found")
    if body.scope == "user" and manifest.adapter not in {"mcp", "business"}:
        await require_admin_user(request, detail="Admin privileges required to install this capability.")
    context = AdapterContext(request, config, user_id, body.scope)
    await registry.get(manifest.adapter).install(context, manifest, body.name, body.configuration)
    return await list_installations(manifest.adapter, request, config, body.scope)

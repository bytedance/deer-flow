"""Adapters over existing integration services; no duplicate credential/config store."""

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app.gateway.deps import is_admin_user
from app.gateway.routers import integrations, mcp, skills
from deerflow.capabilities.business import connection_config
from deerflow.capabilities.catalog import PluginManifest
from deerflow.capabilities.runtime import ambiguous_installation_ids, installation_id
from deerflow.config.app_config import AppConfig
from deerflow.integrations.lark_cli import get_lark_integration_status
from deerflow.runtime.user_context import get_effective_user_id


class CapabilityInstallation(BaseModel):
    id: str
    plugin_id: str | None = None
    adapter: str
    name: str
    description: str = ""
    selectable: bool = True
    installed: bool = True
    enabled: bool | None = None
    version: str | None = None
    scope: str = "deployment"
    auth_status: str = "unknown"
    health: str = "unknown"
    reference: str
    category: str | None = None
    icon: str | None = None


class InstallationList(BaseModel):
    items: list[CapabilityInstallation] = Field(default_factory=list)
    can_manage: bool = False


@dataclass(frozen=True)
class AdapterContext:
    request: Request
    config: AppConfig
    user_id: str


class CapabilityAdapter(Protocol):
    async def list_installations(self, context: AdapterContext) -> list[CapabilityInstallation]: ...

    async def install(self, context: AdapterContext, manifest: PluginManifest, name: str, configuration: dict[str, Any]) -> None: ...


def validate_mcp_connection(configuration: dict[str, Any]) -> None:
    """Validate the normalized transport definition, not manifest form fields."""
    from urllib.parse import urlsplit

    transport = configuration.get("type", configuration.get("transport", "stdio"))
    if not isinstance(transport, str):
        raise HTTPException(422, "Supply a supported MCP transport")
    if transport in {"http", "sse"}:
        url = configuration.get("url")
        valid = False
        try:
            if isinstance(url, str):
                parsed = urlsplit(url)
                _ = parsed.port  # Validate malformed ports too.
                has_http_scheme = parsed.scheme in {"https", "http"}
                has_host = bool(parsed.hostname)
                has_credentials = parsed.username is not None or parsed.password is not None
                has_whitespace = any(c.isspace() for c in url)
                valid = has_http_scheme and has_host and not has_credentials and not parsed.fragment and not has_whitespace
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(422, "Supply an HTTP(S) MCP server URL without embedded credentials")
        return
    if transport != "stdio":
        raise HTTPException(422, "Supply a supported MCP transport and its required connection fields")
    command = configuration.get("command")
    if not isinstance(command, str) or not command.strip():
        raise HTTPException(422, "Supply a supported MCP transport and its required connection fields")


class MCPAdapter:
    async def list_installations(self, context: AdapterContext) -> list[CapabilityInstallation]:
        servers = await asyncio.to_thread(mcp._load_raw_mcp_server_responses)
        result = []
        ambiguous = ambiguous_installation_ids({name: server.model_dump() for name, server in servers.items()})
        for name, server in servers.items():
            raw = server.model_dump()
            metadata = raw.get("capability") or {}
            metadata = metadata if isinstance(metadata, dict) else {}
            auth = server.user_auth
            if auth and auth.enabled:
                auth_status = "configured" if auth.users.get(context.user_id) else "required"
            elif server.oauth or server.headers or server.env:
                auth_status = "configured"
            else:
                auth_status = "not_required"
            presentation = raw.get("presentation")
            icon = presentation.get("icon") if isinstance(presentation, dict) else None
            # Public discovery projects explicit safe fields, never connection
            # URLs, commands, env, OAuth configuration, or another user's IDs.
            identity = installation_id(name, raw)
            result.append(
                CapabilityInstallation(
                    id=f"ambiguous:{installation_id(name, {})}" if identity in ambiguous else identity,
                    selectable=identity not in ambiguous,
                    health="ambiguous" if identity in ambiguous else "unknown",
                    plugin_id=metadata.get("plugin_id") if isinstance(metadata.get("plugin_id"), str) else None,
                    adapter="mcp",
                    name=name,
                    reference=name,
                    description=server.description or "",
                    enabled=server.enabled,
                    version=metadata.get("version") if isinstance(metadata.get("version"), str) else None,
                    auth_status=auth_status,
                    icon=icon if isinstance(icon, str) and icon.startswith("data:image/png;base64,") and len(icon) <= 100_000 else None,
                )
            )
        return result

    async def install(self, context: AdapterContext, manifest: PluginManifest, name: str, configuration: dict[str, Any]) -> None:
        if not name.strip():
            raise HTTPException(422, "Installation name is required")
        if manifest.adapter == "mcp":
            validate_mcp_connection(configuration)
        definition = {**configuration, "capability": {"id": str(uuid4()), "plugin_id": manifest.id, "version": manifest.version}}
        try:
            body = mcp.McpConfigUpdateRequest(mcp_servers={name: mcp.McpServerConfigResponse.model_validate(definition)})
        except ValidationError as error:
            raise HTTPException(422, "Invalid MCP configuration") from error
        await mcp.create_mcp_servers(context.request, body)


class BusinessAdapter(MCPAdapter):
    """Build only bundled providers; reuse the MCP store, lifecycle and discovery."""

    async def list_installations(self, context: AdapterContext) -> list[CapabilityInstallation]:
        from deerflow.capabilities.business import CREDENTIALS

        return [item for item in await super().list_installations(context) if item.plugin_id in CREDENTIALS]

    async def install(self, context: AdapterContext, manifest: PluginManifest, name: str, configuration: dict[str, Any]) -> None:
        try:
            definition = connection_config(manifest.id, configuration)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        definition["description"] = manifest.description.get("en-US", "")
        await super().install(context, manifest, name, definition)


class LarkAdapter:
    async def list_installations(self, context: AdapterContext) -> list[CapabilityInstallation]:
        status = await asyncio.to_thread(get_lark_integration_status, context.user_id, context.config)
        return [
            CapabilityInstallation(
                id="lark",
                plugin_id="lark",
                adapter="lark",
                name="Lark / Feishu",
                reference="lark",
                installed=status.installed,
                version=status.manifest_version,
                scope="user",
                auth_status="connected" if status.auth.status == "authenticated" and status.auth.verified else "configured" if status.auth.status == "authenticated" else "required",
                health="unknown",
            )
        ]

    async def install(self, context: AdapterContext, manifest: PluginManifest, name: str, configuration: dict[str, Any]) -> None:
        await integrations.install_lark(context.request, context.config)


class SkillAdapter:
    async def list_installations(self, context: AdapterContext) -> list[CapabilityInstallation]:
        response = await asyncio.to_thread(lambda: skills._get_user_skill_storage(context.config).load_skills(enabled_only=False))
        response = await skills._filter_visible_skills(context.request, context.config, response)
        return [
            CapabilityInstallation(
                id=f"skill:{skill.category}:{skill.name}",
                adapter="skills",
                name=skill.name,
                reference=skill.name,
                description=skill.description,
                category=str(skill.category),
                enabled=skill.enabled,
                scope="user" if str(skill.category) == "custom" else "deployment",
                auth_status="not_required",
            )
            for skill in response
        ]

    async def install(self, context: AdapterContext, manifest: PluginManifest, name: str, configuration: dict[str, Any]) -> None:
        raise HTTPException(422, "Use the existing skill archive upload API")


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}

    def register(self, name: str, adapter: CapabilityAdapter) -> None:
        if name in self._adapters:
            raise ValueError(f"Adapter already registered: {name}")
        self._adapters[name] = adapter

    def get(self, name: str) -> CapabilityAdapter:
        adapter = self._adapters.get(name)
        if adapter is None:
            raise HTTPException(422, "This capability only has a setup guide; no installation adapter is available")
        return adapter


registry = AdapterRegistry()
registry.register("mcp", MCPAdapter())
registry.register("business", BusinessAdapter())
registry.register("lark", LarkAdapter())
registry.register("skills", SkillAdapter())


async def list_installations(adapter: str, request: Request, config: AppConfig) -> InstallationList:
    context = AdapterContext(request, config, get_effective_user_id())
    items = await registry.get(adapter).list_installations(context)
    return InstallationList(items=items, can_manage=await is_admin_user(request))

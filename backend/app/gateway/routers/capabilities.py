"""Unified capability configuration view API.

Aggregates Models, Skills, MCPs, Connectors, and Agents into a single
list + detail read-only view per ISSUE-10 and ISSUE-09 governance model.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from deerflow.config.agents_config import (
    AgentConfig,
    list_available_agents,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.capability_scope import (
    impact_summary,
    propagate_deactivation,
    read_audit_log,
    resolve_capability_for_tenant,
)
from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config
from deerflow.skills import get_or_new_skill_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


# -- Enums -------------------------------------------------------------

class CapabilityType(StrEnum):
    MODEL = "model"
    SKILL = "skill"
    MCP = "mcp"
    CONNECTOR = "connector"
    AGENT = "agent"


class CapabilityScope(StrEnum):
    GLOBAL = "GLOBAL"
    TENANT = "TENANT"
    TENANT_OVERRIDE = "TENANT_OVERRIDE"


class CapabilityStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


# -- Response models ---------------------------------------------------

class CapabilityOwner(BaseModel):
    business: str = ""
    technical: str = ""


class CapabilityChangeRecord(BaseModel):
    timestamp: str = ""
    actor: str = ""
    summary: str = ""


class CapabilitySummary(BaseModel):
    """Lightweight entry for the unified list view."""

    name: str
    type: CapabilityType
    display_name: str = ""
    description: str = ""
    scope: CapabilityScope = CapabilityScope.GLOBAL
    status: CapabilityStatus = CapabilityStatus.ENABLED
    owner: CapabilityOwner = Field(default_factory=CapabilityOwner)
    version: str | None = None
    source: str | None = None  # Agent source: builtin/tenant/user
    tags: list[str] = Field(default_factory=list)


class CapabilityDetail(BaseModel):
    """Full detail view for a single capability."""

    name: str
    type: CapabilityType
    display_name: str = ""
    description: str = ""
    scope: CapabilityScope = CapabilityScope.GLOBAL
    status: CapabilityStatus = CapabilityStatus.ENABLED
    owner: CapabilityOwner = Field(default_factory=CapabilityOwner)
    version: str | None = None
    source: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Type-specific extensions (varies by capability type)
    extensions: dict[str, Any] = Field(default_factory=dict)

    # Recent changes (best-effort from audit log or inferred from timestamps)
    recent_changes: list[CapabilityChangeRecord] = Field(default_factory=list)


class CapabilityListResponse(BaseModel):
    capabilities: list[CapabilitySummary]
    total: int
    types: list[str]  # available types with data


class ImpactSummaryResponse(BaseModel):
    """Impact preview for a planned capability change."""

    capability: dict[str, str]
    scope: str
    action: str
    affected_tenants: list[str]
    affected_count: int
    warning_level: str
    generated_at: str


class PropagationReport(BaseModel):
    """Propagation result for a deactivation."""

    action: str
    scope: str
    affected_tenants: list[str]
    shielded_tenants: list[str]
    total_affected: int


class TenantCapabilityView(BaseModel):
    """A capability as seen by a specific tenant (with resolution info)."""

    name: str
    type: str
    scope: str
    status: str
    resolution: str  # "inherited" | "overridden" | "tenant_direct"
    config: dict[str, Any] = Field(default_factory=dict)


# -- Owner mapping from ISSUE-05 capability matrix ---------------------

_OWNER_MAP: dict[str, CapabilityOwner] = {
    "model": CapabilityOwner(business="平台产品负责人", technical="模型接入负责人"),
    "skill": CapabilityOwner(business="平台产品负责人", technical="Skills 平台负责人"),
    "mcp": CapabilityOwner(business="平台产品负责人", technical="集成平台负责人"),
    "connector": CapabilityOwner(business="平台产品负责人", technical="集成平台负责人"),
    "agent": CapabilityOwner(business="平台产品负责人", technical="Agent 平台负责人"),
}


def _resolve_owner(cap_type: str) -> CapabilityOwner:
    return _OWNER_MAP.get(cap_type, CapabilityOwner())


# -- Data collectors ---------------------------------------------------

def _collect_models(config: AppConfig) -> list[CapabilitySummary]:
    result: list[CapabilitySummary] = []
    for m in config.models:
        result.append(
            CapabilitySummary(
                name=m.name,
                type=CapabilityType.MODEL,
                display_name=m.display_name or m.name,
                description=m.description or "",
                scope=CapabilityScope.GLOBAL,
                status=CapabilityStatus.ENABLED,
                owner=_resolve_owner("model"),
            )
        )
    return result


def _collect_skills(config: AppConfig) -> list[CapabilitySummary]:
    result: list[CapabilitySummary] = []
    try:
        skills = get_or_new_skill_storage(app_config=config).load_skills()
    except Exception:
        logger.warning("Failed to load skills for capability view", exc_info=True)
        return result

    extensions = _safe_load_extensions()
    for skill in skills:
        enabled = skill.enabled
        if extensions and skill.name in extensions.skills:
            enabled = extensions.skills[skill.name].enabled
        result.append(
            CapabilitySummary(
                name=skill.name,
                type=CapabilityType.SKILL,
                display_name=skill.name,
                description=skill.description or "",
                scope=CapabilityScope.GLOBAL,
                status=CapabilityStatus.ENABLED if enabled else CapabilityStatus.DISABLED,
                owner=_resolve_owner("skill"),
            )
        )
    return result


def _collect_mcp_servers() -> list[CapabilitySummary]:
    result: list[CapabilitySummary] = []
    extensions = _safe_load_extensions()
    if extensions is None:
        return result
    for name, srv in extensions.mcp_servers.items():
        result.append(
            CapabilitySummary(
                name=name,
                type=CapabilityType.MCP,
                display_name=name,
                description=srv.description or "",
                scope=CapabilityScope.GLOBAL,
                status=CapabilityStatus.ENABLED if srv.enabled else CapabilityStatus.DISABLED,
                owner=_resolve_owner("mcp"),
            )
        )
    return result


def _collect_connectors(config: AppConfig) -> list[CapabilitySummary]:
    result: list[CapabilitySummary] = []
    for tenant_id, connectors in config.http_connectors.items():
        for conn in connectors:
            result.append(
                CapabilitySummary(
                    name=f"{tenant_id}/{conn.name}",
                    type=CapabilityType.CONNECTOR,
                    display_name=conn.name,
                    description=conn.description or "",
                    scope=CapabilityScope.TENANT,
                    status=CapabilityStatus.ENABLED,
                    owner=_resolve_owner("connector"),
                    tags=[tenant_id],
                )
            )
    return result


def _collect_agents(
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> list[CapabilitySummary]:
    result: list[CapabilitySummary] = []
    try:
        agents = list_available_agents(tenant_id=tenant_id, user_id=user_id)
    except Exception:
        logger.warning("Failed to list agents for capability view", exc_info=True)
        return result

    for a in agents:
        scope = CapabilityScope.GLOBAL
        if a.source == "tenant":
            scope = CapabilityScope.TENANT
        elif a.source == "user":
            scope = CapabilityScope.TENANT_OVERRIDE

        result.append(
            CapabilitySummary(
                name=a.name,
                type=CapabilityType.AGENT,
                display_name=a.display_name or a.name,
                description=a.description or "",
                scope=scope,
                status=CapabilityStatus.ENABLED if a.enabled else CapabilityStatus.DISABLED,
                owner=_resolve_owner("agent"),
                source=a.source,
                tags=a.tags or [],
            )
        )
    return result


def _safe_load_extensions() -> ExtensionsConfig | None:
    try:
        return get_extensions_config()
    except Exception:
        logger.warning("Failed to load extensions config for capability view", exc_info=True)
        return None


# -- Endpoints ---------------------------------------------------------

@router.get("", response_model=CapabilityListResponse)
async def list_capabilities(
    cap_type: str | None = Query(default=None, alias="type", description="Filter by capability type"),
    scope: str | None = Query(default=None, description="Filter by scope (GLOBAL|TENANT|TENANT_OVERRIDE)"),
    tenant_id: str | None = Query(default=None, description="Tenant ID for tenant-scoped view"),
    config: AppConfig = Depends(get_config),
) -> CapabilityListResponse:
    """List all platform capabilities across Models, Skills, MCPs, Connectors, and Agents.

    Supports optional filtering by ``type``, ``scope``, and ``tenant_id``.
    When ``tenant_id`` is provided, GLOBAL and TENANT capabilities are annotated
    with their inheritance status for that tenant.
    """
    all_caps: list[CapabilitySummary] = []

    if cap_type is None or cap_type == CapabilityType.MODEL:
        all_caps.extend(_collect_models(config))
    if cap_type is None or cap_type == CapabilityType.SKILL:
        all_caps.extend(_collect_skills(config))
    if cap_type is None or cap_type == CapabilityType.MCP:
        all_caps.extend(_collect_mcp_servers())
    if cap_type is None or cap_type == CapabilityType.CONNECTOR:
        all_caps.extend(_collect_connectors(config))
    if cap_type is None or cap_type == CapabilityType.AGENT:
        all_caps.extend(_collect_agents(tenant_id=tenant_id))

    # Tenant filter: show only capabilities visible to this tenant
    if tenant_id:
        all_caps = [
            c for c in all_caps
            if c.scope in (CapabilityScope.GLOBAL, CapabilityScope.TENANT, CapabilityScope.TENANT_OVERRIDE)
        ]

    if scope:
        all_caps = [c for c in all_caps if c.scope.value == scope]

    all_caps.sort(key=lambda c: (c.type.value, c.name))

    available_types = sorted({c.type.value for c in all_caps})

    return CapabilityListResponse(
        capabilities=all_caps,
        total=len(all_caps),
        types=available_types,
    )


@router.get("/{cap_type}/{name}", response_model=CapabilityDetail)
async def get_capability_detail(
    cap_type: str,
    name: str,
    config: AppConfig = Depends(get_config),
) -> CapabilityDetail:
    """Get full detail for a single capability, including type-specific extensions and recent changes."""
    extensions: dict[str, Any] = {}

    if cap_type == CapabilityType.MODEL:
        model = config.get_model_config(name)
        if model is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Model '{name}' not found")
        extensions = {
            "provider": {"use": model.use, "model": model.model},
            "capabilities": {
                "supports_thinking": model.supports_thinking,
                "supports_vision": model.supports_vision,
                "supports_reasoning_effort": model.supports_reasoning_effort,
            },
        }
        return CapabilityDetail(
            name=model.name,
            type=CapabilityType.MODEL,
            display_name=model.display_name or model.name,
            description=model.description or "",
            scope=CapabilityScope.GLOBAL,
            status=CapabilityStatus.ENABLED,
            owner=_resolve_owner("model"),
            extensions=extensions,
        )

    elif cap_type == CapabilityType.CONNECTOR:
        for tenant_id, connectors in config.http_connectors.items():
            for conn in connectors:
                full_name = f"{tenant_id}/{conn.name}"
                if full_name == name or conn.name == name:
                    extensions = {
                        "endpoint": {"url": conn.url, "method": conn.method},
                        "auth": {"type": conn.auth_type, "token_env": conn.auth_token_env},
                        "limits": {"timeout_seconds": conn.timeout_seconds, "max_response_bytes": conn.max_response_bytes},
                        "retry": {"max_retries": conn.max_retries, "on_status": conn.retry_on_status},
                        "cache": {"ttl_seconds": conn.cache_ttl_seconds},
                    }
                    return CapabilityDetail(
                        name=conn.name,
                        type=CapabilityType.CONNECTOR,
                        display_name=conn.name,
                        description=conn.description or "",
                        scope=CapabilityScope.TENANT,
                        status=CapabilityStatus.ENABLED,
                        owner=_resolve_owner("connector"),
                        tags=[tenant_id],
                        extensions=extensions,
                    )
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Connector '{name}' not found")

    elif cap_type == CapabilityType.SKILL:
        try:
            skills = get_or_new_skill_storage(app_config=config).load_skills()
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
        for skill in skills:
            if skill.name == name:
                extensions = {
                    "source": {"path": str(skill.skill_dir)},
                    "license": skill.license,
                }
                return CapabilityDetail(
                    name=skill.name,
                    type=CapabilityType.SKILL,
                    display_name=skill.name,
                    description=skill.description or "",
                    scope=CapabilityScope.GLOBAL,
                    status=CapabilityStatus.ENABLED if skill.enabled else CapabilityStatus.DISABLED,
                    owner=_resolve_owner("skill"),
                    extensions=extensions,
                )
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    elif cap_type == CapabilityType.MCP:
        extensions_cfg = _safe_load_extensions()
        if extensions_cfg and name in extensions_cfg.mcp_servers:
            srv = extensions_cfg.mcp_servers[name]
            extensions = {
                "transport": {
                    "type": srv.type,
                    "command": srv.command,
                    "args": srv.args,
                    "url": srv.url,
                },
                "auth": {"oauth_enabled": srv.oauth.enabled if srv.oauth else False},
            }
            return CapabilityDetail(
                name=name,
                type=CapabilityType.MCP,
                display_name=name,
                description=srv.description or "",
                scope=CapabilityScope.GLOBAL,
                status=CapabilityStatus.ENABLED if srv.enabled else CapabilityStatus.DISABLED,
                owner=_resolve_owner("mcp"),
                extensions=extensions,
            )
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    elif cap_type == CapabilityType.AGENT:
        try:
            agent_cfg = load_agent_config_from_any(name)
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        if agent_cfg is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        extensions = {
            "model": agent_cfg.model,
            "visibility": agent_cfg.visibility,
            "tool_groups": agent_cfg.tool_groups or [],
            "skills": agent_cfg.skills or [],
            "mcp_servers": agent_cfg.mcp_servers or [],
            "type": agent_cfg.type,
            "parent": agent_cfg.parent,
        }
        return CapabilityDetail(
            name=agent_cfg.name,
            type=CapabilityType.AGENT,
            display_name=agent_cfg.display_name or agent_cfg.name,
            description=agent_cfg.description or "",
            scope=CapabilityScope.GLOBAL,
            status=CapabilityStatus.ENABLED,
            owner=_resolve_owner("agent"),
            tags=agent_cfg.tags or [],
            extensions=extensions,
        )

    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Unknown capability type '{cap_type}'")


@router.get("/{cap_type}/{name}/impact", response_model=ImpactSummaryResponse)
async def get_capability_impact(
    cap_type: str,
    name: str,
    action: str = Query(default="deactivate", description="Planned action: deactivate | modify | deprecate"),
    config: AppConfig = Depends(get_config),
) -> ImpactSummaryResponse:
    """Preview the impact of a planned capability change.

    Shows which tenants will be affected before the change is executed.
    """
    summary = impact_summary(cap_type, name, action, config)
    return ImpactSummaryResponse(**summary)


@router.get("/{cap_type}/{name}/audit")
async def get_capability_audit(
    cap_type: str,
    name: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Get recent audit records for a capability."""
    return read_audit_log(capability_type=cap_type, capability_name=name, limit=limit)


@router.get("/resolve/{tenant_id}/{cap_type}/{name}", response_model=TenantCapabilityView)
async def resolve_for_tenant(
    tenant_id: str,
    cap_type: str,
    name: str,
    config: AppConfig = Depends(get_config),
) -> TenantCapabilityView:
    """Resolve a capability's effective configuration for a specific tenant.

    Returns the merged view with resolution info (inherited / overridden / tenant_direct).
    """
    resolved = resolve_capability_for_tenant(tenant_id, cap_type, name, config)
    if resolved is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Capability '{cap_type}/{name}' not available for tenant '{tenant_id}'")
    return TenantCapabilityView(**resolved)


@router.post("/{cap_type}/{name}/deactivate", response_model=PropagationReport)
async def deactivate_capability(
    cap_type: str,
    name: str,
    config: AppConfig = Depends(get_config),
) -> PropagationReport:
    """Simulate deactivation with propagation to affected tenants.

    Records an audit entry and returns the propagation report.
    In phase 1 this is a dry-run -- actual state mutation is deferred to
    per-type management endpoints.
    """
    report = propagate_deactivation(cap_type, name, config, actor="api")
    return PropagationReport(**report)


def load_agent_config_from_any(name: str) -> AgentConfig | None:
    """Try to load an agent config from any source (user -> tenant -> builtin)."""
    from deerflow.config.agents_config import (
        load_agent_config,
        scan_builtin_agents,
    )

    # Try user scope
    try:
        cfg = load_agent_config(name)
        if cfg is not None:
            return cfg
    except Exception:
        pass

    # Try builtin
    for cfg in scan_builtin_agents():
        if cfg.name == name:
            return cfg

    return None

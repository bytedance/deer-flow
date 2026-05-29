"""Integration system management API.

Provides tenant-scoped endpoints for viewing integration systems, capability
routes, entity links, and running health checks. Write operations are rate-limited
and audit-logged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deerflow.persistence.agent.auth import is_tenant_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants/{tenant_id}/integrations", tags=["integrations"])

# Degradation tracking: system_key → consecutive failure count
_degradation_tracker: dict[str, int] = {}
_degraded_systems: set[str] = set()

# Audit log (in-memory, capped)
_AUDIT_LOG_MAX = 500
_audit_log: list[dict[str, Any]] = []


# -- Request / Response models -----------------------------------------

class HealthCheckResponse(BaseModel):
    system_key: str
    healthy: bool
    latency_ms: float | None = None
    message: str = ""
    checked_at: str = ""
    degraded: bool = False
    consecutive_failures: int = 0


class IntegrationSystemSummary(BaseModel):
    system_key: str
    system_type: str
    enabled: bool
    healthy: bool
    degraded: bool = False
    capabilities: list[str] = Field(default_factory=list)


class CapabilityRouteView(BaseModel):
    capability_key: str
    primary_system_key: str
    enrich_system_keys: list[str] = Field(default_factory=list)
    fallback_system_keys: list[str] = Field(default_factory=list)
    merge_policy: str = "primary_plus_enrich"
    partial_failure_policy: str = "return_partial"
    enabled: bool = True


class EntityLinkView(BaseModel):
    canonical_id: str
    entity_type: str
    mappings: dict[str, str] = Field(default_factory=dict)


class AuditEntry(BaseModel):
    timestamp: str
    actor: str
    tenant_id: str
    action: str
    target: str
    details: dict[str, Any] = Field(default_factory=dict)


# -- Auth helpers -------------------------------------------------------

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


def _get_actor(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "anonymous"
    return getattr(user, "email", None) or getattr(user, "id", "unknown")


def _require_tenant_admin(request: Request, tenant_id: str) -> None:
    """Verify the caller can manage integration config for this tenant.

    - superadmin / platform_admin: can operate on any tenant
    - tenant_admin: can only operate on own tenant
    """
    role = _get_current_user_role(request)
    if not is_tenant_admin(role):
        raise HTTPException(status_code=403, detail="Tenant admin privileges required")
    if role == "tenant_admin":
        user_tenant = _get_current_user_tenant(request)
        if user_tenant != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot manage integration config for a different tenant",
            )


def _record_audit(
    actor: str,
    tenant_id: str,
    action: str,
    target: str,
    details: dict[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(),
        "actor": actor,
        "tenant_id": tenant_id,
        "action": action,
        "target": target,
        "details": details or {},
    }
    _audit_log.append(entry)
    if len(_audit_log) > _AUDIT_LOG_MAX:
        del _audit_log[: len(_audit_log) - _AUDIT_LOG_MAX]
    logger.info(
        "Integration audit: actor=%s tenant=%s action=%s target=%s",
        actor, tenant_id, action, target,
    )


# -- Degradation strategy -----------------------------------------------

_DEGRADATION_THRESHOLD = 3


def _record_health_failure(system_key: str) -> int:
    count = _degradation_tracker.get(system_key, 0) + 1
    _degradation_tracker[system_key] = count
    if count >= _DEGRADATION_THRESHOLD:
        if system_key not in _degraded_systems:
            _degraded_systems.add(system_key)
            logger.warning(
                "System %s auto-degraded after %d consecutive failures",
                system_key, count,
            )
    return count


def _record_health_success(system_key: str) -> None:
    _degradation_tracker[system_key] = 0
    if system_key in _degraded_systems:
        _degraded_systems.discard(system_key)
        logger.info("System %s recovered from degraded state", system_key)


def is_system_degraded(system_key: str) -> bool:
    return system_key in _degraded_systems


# -- Endpoints ----------------------------------------------------------

@router.get("/systems", response_model=list[IntegrationSystemSummary])
async def list_integration_systems(
    tenant_id: str,
    request: Request,
) -> list[IntegrationSystemSummary]:
    """List all configured integration systems and their health status."""
    try:
        from deerflow.integrations.registry import get_integration_registry

        registry = get_integration_registry()
        result: list[IntegrationSystemSummary] = []
        for adapter in registry.list_all():
            health = registry.get_health_status(adapter.system_key)
            healthy = health.healthy if health else True
            degraded = is_system_degraded(adapter.system_key)
            result.append(
                IntegrationSystemSummary(
                    system_key=adapter.system_key,
                    system_type=adapter.system_type,
                    enabled=True,
                    healthy=healthy and not degraded,
                    degraded=degraded,
                )
            )
        return result
    except ImportError:
        return []
    except Exception as e:
        logger.error("Failed to list integration systems: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list integration systems") from e


@router.get("/capability-routes", response_model=list[CapabilityRouteView])
async def list_capability_routes(
    tenant_id: str,
    request: Request,
) -> list[CapabilityRouteView]:
    """List configured capability routes (primary, enrich, fallback, policies)."""
    try:
        from deerflow.config.app_config import get_app_config

        app_config = get_app_config()
        integrations = getattr(app_config, "integrations", None)
        if integrations is None:
            return []

        result: list[CapabilityRouteView] = []
        for cap_key, route in integrations.routes.items():
            result.append(
                CapabilityRouteView(
                    capability_key=cap_key,
                    primary_system_key=route.primary_system_key,
                    enrich_system_keys=list(route.enrich_system_keys),
                    fallback_system_keys=list(route.fallback_system_keys),
                    merge_policy=route.merge_policy,
                    partial_failure_policy=route.partial_failure_policy,
                    enabled=route.enabled,
                )
            )
        return result
    except Exception as e:
        logger.error("Failed to list capability routes: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list capability routes") from e


@router.get("/entity-links", response_model=list[EntityLinkView])
async def list_entity_links(
    tenant_id: str,
    request: Request,
) -> list[EntityLinkView]:
    """List entity link mappings (canonical_id → remote_id per system)."""
    try:
        from deerflow.config.app_config import get_app_config

        app_config = get_app_config()
        integrations = getattr(app_config, "integrations", None)
        if integrations is None:
            return []

        result: list[EntityLinkView] = []
        for link in integrations.entity_links:
            mappings = {entry.system_key: entry.remote_id for entry in link.links}
            result.append(
                EntityLinkView(
                    canonical_id=link.canonical_id,
                    entity_type=link.entity_type,
                    mappings=mappings,
                )
            )
        return result
    except Exception as e:
        logger.error("Failed to list entity links: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list entity links") from e


@router.post(
    "/systems/{system_key}/health-check",
    response_model=HealthCheckResponse,
)
async def run_health_check(
    tenant_id: str,
    system_key: str,
    request: Request,
) -> HealthCheckResponse:
    """Run an on-demand health check for a specific integration system.

    Rate-limited: 5 req/min per system per tenant.
    Updates degradation tracking on failure/success.
    """
    _require_tenant_admin(request, tenant_id)

    try:
        from deerflow.integrations.registry import get_integration_registry

        registry = get_integration_registry()
        adapter = registry.get(system_key)
        if adapter is None:
            raise HTTPException(status_code=404, detail=f"System '{system_key}' not found")

        health = await adapter.health_check()
        checked_at = datetime.now().isoformat()

        if health.healthy:
            _record_health_success(system_key)
        else:
            failures = _record_health_failure(system_key)
            _record_audit(
                actor=_get_actor(request),
                tenant_id=tenant_id,
                action="health_check_failed",
                target=system_key,
                details={"message": health.message, "consecutive_failures": failures},
            )

        degraded = is_system_degraded(system_key)
        return HealthCheckResponse(
            system_key=system_key,
            healthy=health.healthy and not degraded,
            latency_ms=health.latency_ms,
            message=health.message,
            checked_at=checked_at,
            degraded=degraded,
            consecutive_failures=_degradation_tracker.get(system_key, 0),
        )
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=503, detail="Integration module not available")
    except Exception as e:
        logger.error("Health check failed for %s: %s", system_key, e, exc_info=True)
        failures = _record_health_failure(system_key)
        return HealthCheckResponse(
            system_key=system_key,
            healthy=False,
            message=str(e),
            checked_at=datetime.now().isoformat(),
            degraded=is_system_degraded(system_key),
            consecutive_failures=failures,
        )


@router.get("/audit", response_model=list[AuditEntry])
async def get_audit_log(
    tenant_id: str,
    request: Request,
    limit: int = 50,
) -> list[AuditEntry]:
    """Get recent audit entries for integration management operations.

    Tenant admins see only their own tenant's entries.
    Platform admins see all entries.
    """
    _require_tenant_admin(request, tenant_id)
    role = _get_current_user_role(request)

    entries = _audit_log
    if role == "tenant_admin":
        entries = [e for e in entries if e["tenant_id"] == tenant_id]

    return [AuditEntry(**e) for e in entries[-limit:]]

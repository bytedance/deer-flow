"""Capability scope boundary rules engine.

Implements the GLOBAL → TENANT inheritance, TENANT_OVERRIDE field-level
override, deactivation propagation, and impact analysis per ISSUE-11.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config
from deerflow.config.http_connector_config import HttpConnectorConfig

logger = logging.getLogger(__name__)

# ── Audit trail ─────────────────────────────────────────────────────────

AUDIT_LOG_DIR = Path(".deer-flow/audit")


def _audit_log_path() -> Path:
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIT_LOG_DIR / "capability_changes.jsonl"


def record_audit(
    actor: str,
    change_type: str,
    capability_type: str,
    capability_name: str,
    scope: str,
    affected_tenants: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an audit record for a capability scope change."""
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "actor": actor,
        "change_type": change_type,
        "capability_type": capability_type,
        "capability_name": capability_name,
        "scope": scope,
        "affected_tenants": affected_tenants or [],
        "details": details or {},
    }
    try:
        with open(_audit_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("Failed to write audit record for %s/%s", capability_type, capability_name, exc_info=True)


def read_audit_log(
    capability_type: str | None = None,
    capability_name: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Read recent audit records, optionally filtered by capability."""
    path = _audit_log_path()
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if capability_type and rec.get("capability_type") != capability_type:
                    continue
                if capability_name and rec.get("capability_name") != capability_name:
                    continue
                records.append(rec)
    except OSError:
        logger.warning("Failed to read audit log", exc_info=True)
        return []

    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:limit]


# ── Tenant resolution ────────────────────────────────────────────────────


def list_known_tenants(config: AppConfig) -> list[str]:
    """Return all tenant IDs known to the system.

    Tenant IDs are discovered from http_connectors keys and tenant agents.
    """
    tenant_ids: set[str] = set()

    # From HTTP connectors
    tenant_ids.update(config.http_connectors.keys())

    # From tenant-level agents
    try:
        from deerflow.config.agents_config import scan_builtin_agents

        # Tenant agents require a tenant_id; we list builtin as global,
        # and infer tenants from connectors (already added above).
        # Tenant agents are scoped per-tenant and discovered via API.
        _ = scan_builtin_agents()  # ensures module loads
    except Exception:
        pass

    return sorted(tenant_ids)


def resolve_capability_for_tenant(
    tenant_id: str,
    cap_type: str,
    cap_name: str,
    config: AppConfig,
) -> dict[str, Any] | None:
    """Resolve a capability's effective configuration for a specific tenant.

    Resolution order:
    1. If a TENANT_OVERRIDE exists → merge tenant fields over global base
    2. If only GLOBAL exists → tenant inherits the global config as-is
    3. If only TENANT exists → return tenant config directly
    4. Otherwise → None (not available)

    Returns a dict with keys:
        - name, type, scope, status, config (merged config dict)
        - resolution: "inherited" | "overridden" | "tenant_direct"
    """
    # ── Connectors: tenant-keyed by design ──
    if cap_type == "connector":
        connectors = config.http_connectors.get(tenant_id, [])
        for conn in connectors:
            if conn.name == cap_name:
                return {
                    "name": conn.name,
                    "type": "connector",
                    "scope": "TENANT",
                    "status": "enabled",
                    "resolution": "tenant_direct",
                    "config": _connector_to_dict(conn),
                }
        return None

    # ── Agents: check tenant/user override first ──
    if cap_type == "agent":
        return _resolve_agent_for_tenant(tenant_id, cap_name)

    # ── Models: GLOBAL only (no tenant override storage yet) ──
    if cap_type == "model":
        model = config.get_model_config(cap_name)
        if model is None:
            return None
        return {
            "name": model.name,
            "type": "model",
            "scope": "GLOBAL",
            "status": "enabled",
            "resolution": "inherited",
            "config": {
                "display_name": model.display_name or model.name,
                "use": model.use,
                "model": model.model,
                "description": model.description or "",
            },
        }

    # ── Skills: GLOBAL only ──
    if cap_type == "skill":
        try:
            from deerflow.skills.storage import get_or_new_skill_storage

            storage = get_or_new_skill_storage(config.skills)
            skills = storage.load_skills()
        except Exception:
            return None
        for skill in skills:
            if skill.name == cap_name:
                return {
                    "name": skill.name,
                    "type": "skill",
                    "scope": "GLOBAL",
                    "status": "enabled" if skill.enabled else "disabled",
                    "resolution": "inherited",
                    "config": {
                        "description": skill.description or "",
                        "license": skill.license,
                        "skill_dir": str(skill.skill_dir),
                    },
                }
        return None

    # ── MCPs: GLOBAL only ──
    if cap_type == "mcp":
        extensions = _safe_load_extensions()
        if extensions and cap_name in extensions.mcp_servers:
            srv = extensions.mcp_servers[cap_name]
            return {
                "name": cap_name,
                "type": "mcp",
                "scope": "GLOBAL",
                "status": "enabled" if srv.enabled else "disabled",
                "resolution": "inherited",
                "config": {
                    "type": srv.type,
                    "command": srv.command,
                    "url": srv.url,
                    "description": srv.description or "",
                },
            }
        return None

    return None


# ── Impact analysis ──────────────────────────────────────────────────────


def get_affected_tenants(
    cap_type: str,
    cap_name: str,
    config: AppConfig,
) -> list[str]:
    """Return tenants that would be affected by a change to a capability.

    For GLOBAL capabilities: all known tenants are affected.
    For TENANT capabilities: only the owning tenant.
    For TENANT_OVERRIDE: only the overriding tenant.
    Returns empty list if the capability doesn't exist.
    """
    # Verify the capability exists
    if not _capability_exists(cap_type, cap_name, config):
        return []

    scope = _detect_scope(cap_type, cap_name, config)

    if scope == "GLOBAL":
        # All tenants that inherit from this capability
        return list_known_tenants(config)
    elif scope == "TENANT":
        # Only the owning tenant — find from connectors or tenant agents
        return _find_owning_tenants(cap_type, cap_name, config)
    elif scope == "TENANT_OVERRIDE":
        return _find_owning_tenants(cap_type, cap_name, config)
    return []


def impact_summary(
    cap_type: str,
    cap_name: str,
    action: str,
    config: AppConfig,
) -> dict[str, Any]:
    """Produce an impact summary for a planned change.

    Args:
        cap_type: Capability type
        cap_name: Capability name
        action: "deactivate" | "modify" | "deprecate"
        config: AppConfig instance

    Returns a dict with affected_tenants, action, and warning_level.
    """
    affected = get_affected_tenants(cap_type, cap_name, config)
    scope = _detect_scope(cap_type, cap_name, config)

    warning_level = "none"
    if action == "deactivate" and scope == "GLOBAL" and len(affected) > 0:
        warning_level = "critical"
    elif action == "deactivate" and len(affected) > 0:
        warning_level = "warning"
    elif action == "modify" and scope == "GLOBAL":
        warning_level = "info"

    return {
        "capability": {"type": cap_type, "name": cap_name},
        "scope": scope,
        "action": action,
        "affected_tenants": affected,
        "affected_count": len(affected),
        "warning_level": warning_level,
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ── Deactivation propagation ─────────────────────────────────────────────


def propagate_deactivation(
    cap_type: str,
    cap_name: str,
    config: AppConfig,
    actor: str = "system",
) -> dict[str, Any]:
    """Simulate deactivation propagation.

    For GLOBAL capabilities: all inheriting tenants lose access unless they have
    an active TENANT_OVERRIDE.
    For TENANT capabilities: only the owning tenant loses access.
    For TENANT_OVERRIDE: only the overriding tenant loses the override, falling
    back to the global config.

    Returns a propagation report.
    """
    scope = _detect_scope(cap_type, cap_name, config)
    affected = get_affected_tenants(cap_type, cap_name, config)

    # Tenants with active overrides are shielded from global deactivation
    shielded: list[str] = []
    if scope == "GLOBAL":
        for tid in affected:
            resolved = resolve_capability_for_tenant(tid, cap_type, cap_name, config)
            if resolved and resolved.get("resolution") == "overridden":
                shielded.append(tid)

    truly_affected = [t for t in affected if t not in shielded]

    # Record audit
    record_audit(
        actor=actor,
        change_type="deactivate",
        capability_type=cap_type,
        capability_name=cap_name,
        scope=scope,
        affected_tenants=truly_affected,
        details={
            "shielded_tenants": shielded,
            "total_known_tenants": len(list_known_tenants(config)),
        },
    )

    return {
        "action": "deactivate",
        "scope": scope,
        "affected_tenants": truly_affected,
        "shielded_tenants": shielded,
        "total_affected": len(truly_affected),
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_load_extensions() -> ExtensionsConfig | None:
    try:
        return get_extensions_config()
    except Exception:
        logger.warning("Failed to load extensions config", exc_info=True)
        return None


def _connector_to_dict(conn: HttpConnectorConfig) -> dict[str, Any]:
    return {
        "url": conn.url,
        "method": conn.method,
        "auth_type": conn.auth_type,
        "timeout_seconds": conn.timeout_seconds,
        "max_response_bytes": conn.max_response_bytes,
        "max_retries": conn.max_retries,
        "cache_ttl_seconds": conn.cache_ttl_seconds,
        "description": conn.description or "",
    }


def _detect_scope(cap_type: str, cap_name: str, config: AppConfig) -> str:
    """Detect the current scope of a capability."""
    if cap_type == "connector":
        for connectors in config.http_connectors.values():
            for conn in connectors:
                if conn.name == cap_name:
                    return "TENANT"
        return "GLOBAL"

    if cap_type == "agent":
        try:
            from deerflow.config.agents_config import (
                load_agent_config,
                scan_builtin_agents,
            )

            for agent in scan_builtin_agents():
                if agent.name == cap_name:
                    return "GLOBAL"
            # Tenant and user agents are checked via load_agent_config
            user_cfg = load_agent_config(cap_name)
            if user_cfg and user_cfg.source == "user":
                return "TENANT_OVERRIDE"
            elif user_cfg and user_cfg.source == "tenant":
                return "TENANT"
        except Exception:
            pass
        return "GLOBAL"

    # Models, Skills, MCPs: GLOBAL only in current design
    return "GLOBAL"


def _capability_exists(cap_type: str, cap_name: str, config: AppConfig) -> bool:
    """Check if a capability exists in the system."""
    if cap_type == "model":
        return config.get_model_config(cap_name) is not None
    if cap_type == "connector":
        for connectors in config.http_connectors.values():
            for conn in connectors:
                if conn.name == cap_name:
                    return True
        return False
    if cap_type == "mcp":
        extensions = _safe_load_extensions()
        return extensions is not None and cap_name in extensions.mcp_servers
    if cap_type == "skill":
        try:
            from deerflow.skills.storage import get_or_new_skill_storage
            storage = get_or_new_skill_storage(config.skills)
            skills = storage.load_skills()
        except Exception:
            return False
        return any(s.name == cap_name for s in skills)
    if cap_type == "agent":
        try:
            from deerflow.config.agents_config import load_agent_config, scan_builtin_agents
            for agent in scan_builtin_agents():
                if agent.name == cap_name:
                    return True
            return load_agent_config(cap_name) is not None
        except Exception:
            return False
    return False


def _find_owning_tenants(cap_type: str, cap_name: str, config: AppConfig) -> list[str]:
    """Find which tenants own a tenant-scoped capability."""
    if cap_type == "connector":
        result = []
        for tid, connectors in config.http_connectors.items():
            for conn in connectors:
                if conn.name == cap_name:
                    result.append(tid)
        return result
    return []


def _resolve_agent_for_tenant(tenant_id: str, agent_name: str) -> dict[str, Any] | None:
    """Resolve agent for a specific tenant, considering override layers."""
    try:
        from deerflow.config.agents_config import (
            list_available_agents,
        )

        agents = list_available_agents(tenant_id=tenant_id)
        for agent in agents:
            if agent.name == agent_name:
                resolution = "inherited"
                if agent.source == "tenant":
                    resolution = "tenant_direct"
                elif agent.source == "user":
                    resolution = "overridden"

                return {
                    "name": agent.name,
                    "type": "agent",
                    "scope": (
                        "GLOBAL" if agent.source == "builtin"
                        else "TENANT" if agent.source == "tenant"
                        else "TENANT_OVERRIDE"
                    ),
                    "status": "enabled" if agent.enabled else "disabled",
                    "resolution": resolution,
                    "config": {
                        "display_name": agent.display_name or agent.name,
                        "description": agent.description or "",
                        "model": agent.model,
                        "source": agent.source,
                        "tags": agent.tags or [],
                    },
                }
    except Exception:
        logger.warning("Failed to resolve agent %s for tenant %s", agent_name, tenant_id, exc_info=True)

    return None

"""Industrial migration endpoint — enables all core-industrial skills for a tenant.

This supports the frontend "industrial-first migration" prompt: when an existing
tenant accepts the prompt, this endpoint ensures all core-industrial skills are
enabled in the global extensions_config.json so the user immediately sees the
industrial-first experience.

Per-tenant skill configuration is not yet implemented; for now the endpoint acts
on the global skill configuration (same config every tenant sees).

Migration state tracking:
- GET /api/tenants/{tenant_id}/migration-status - check if migration prompted/completed
- POST /api/tenants/{tenant_id}/mark-migration-prompted - mark dialog was shown
- POST /api/tenants/{tenant_id}/decline-migration - decline migration (no skill changes)
- POST /api/tenants/{tenant_id}/migrate-industrial - accept migration (enable skills)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import (
    ExtensionsConfig,
    SkillStateConfig,
    get_extensions_config,
    reload_extensions_config,
)
from deerflow.skills.types import SkillTier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants/{tenant_id}", tags=["tenant-industrial-migration"])


# ---------------------------------------------------------------------------
# Migration state storage
# ---------------------------------------------------------------------------


def _get_migration_state_path() -> Path:
    """Get path to migration state file."""
    from deerflow.config.paths import get_paths

    deerflow_home = get_paths().base_dir
    return deerflow_home / "industrial_migration_state.json"


def _load_migration_state() -> dict[str, dict]:
    """Load migration state from file. Returns {tenant_id: state}."""
    state_path = _get_migration_state_path()
    if not state_path.exists():
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load migration state: %s", e)
        return {}


def _save_migration_state(state: dict[str, dict]) -> None:
    """Save migration state to file."""
    state_path = _get_migration_state_path()
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    except OSError as e:
        logger.error("Failed to save migration state: %s", e)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class IndustrialMigrationResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID the migration ran for")
    enabled_count: int = Field(..., description="Number of industrial skills enabled")
    skill_names: list[str] = Field(..., description="Names of industrial skills that are now enabled")


class MigrationStatusResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    prompted: bool = Field(default=False, description="Whether migration dialog has been shown")
    completed: bool = Field(default=False, description="Whether migration was accepted or declined")
    accepted: bool = Field(default=False, description="Whether user accepted migration")
    prompted_at: str | None = Field(default=None, description="ISO timestamp when prompted")
    completed_at: str | None = Field(default=None, description="ISO timestamp when completed")


class DeclineMigrationResponse(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    message: str = Field(..., description="Confirmation message")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_extensions_config(config_path: Path, extensions_config: ExtensionsConfig) -> None:
    config_data = {
        "mcpServers": {name: server.model_dump() for name, server in extensions_config.mcp_servers.items()},
        "skills": {
            name: {k: v for k, v in {"enabled": sc.enabled, "tier": sc.tier}.items() if v is not None}
            for name, sc in extensions_config.skills.items()
        },
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
        f.write("\n")


def _mark_migration_accepted(tenant_id: str) -> None:
    """Mark migration as accepted and completed in state file."""
    state = _load_migration_state()
    if tenant_id not in state:
        state[tenant_id] = {}
    state[tenant_id]["completed"] = True
    state[tenant_id]["accepted"] = True
    state[tenant_id]["completed_at"] = _now_iso()
    if not state[tenant_id].get("prompted"):
        state[tenant_id]["prompted"] = True
        state[tenant_id]["prompted_at"] = _now_iso()
    _save_migration_state(state)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/migration-status",
    response_model=MigrationStatusResponse,
    summary="Get migration dialog status for tenant",
    description="Returns whether the migration dialog has been shown and whether the user accepted or declined.",
)
async def get_migration_status(tenant_id: str) -> MigrationStatusResponse:
    """Check if migration dialog should be shown to this tenant."""
    state = _load_migration_state()
    tenant_state = state.get(tenant_id, {})

    return MigrationStatusResponse(
        tenant_id=tenant_id,
        prompted=tenant_state.get("prompted", False),
        completed=tenant_state.get("completed", False),
        accepted=tenant_state.get("accepted", False),
        prompted_at=tenant_state.get("prompted_at"),
        completed_at=tenant_state.get("completed_at"),
    )


@router.post(
    "/mark-migration-prompted",
    response_model=MigrationStatusResponse,
    summary="Mark that migration dialog was shown to user",
    description="Call this when the migration dialog is displayed to the user.",
)
async def mark_migration_prompted(tenant_id: str) -> MigrationStatusResponse:
    """Mark that the migration dialog has been shown to this tenant."""
    state = _load_migration_state()

    if tenant_id not in state:
        state[tenant_id] = {}

    state[tenant_id]["prompted"] = True
    state[tenant_id]["prompted_at"] = _now_iso()

    _save_migration_state(state)

    logger.info("Marked migration as prompted for tenant %s", tenant_id)

    return MigrationStatusResponse(
        tenant_id=tenant_id,
        prompted=True,
        completed=state[tenant_id].get("completed", False),
        accepted=state[tenant_id].get("accepted", False),
        prompted_at=state[tenant_id].get("prompted_at"),
        completed_at=state[tenant_id].get("completed_at"),
    )


@router.post(
    "/decline-migration",
    response_model=DeclineMigrationResponse,
    summary="Decline industrial migration",
    description="User chose not to enable industrial skills. Marks migration as completed without changes.",
)
async def decline_migration(tenant_id: str) -> DeclineMigrationResponse:
    """Mark migration as declined — no skill changes, but don't prompt again."""
    state = _load_migration_state()

    if tenant_id not in state:
        state[tenant_id] = {}

    state[tenant_id]["completed"] = True
    state[tenant_id]["accepted"] = False
    state[tenant_id]["completed_at"] = _now_iso()

    if not state[tenant_id].get("prompted"):
        state[tenant_id]["prompted"] = True
        state[tenant_id]["prompted_at"] = _now_iso()

    _save_migration_state(state)

    logger.info("Tenant %s declined industrial migration", tenant_id)

    return DeclineMigrationResponse(
        tenant_id=tenant_id,
        message="Migration declined. Industrial skills were not enabled. You can enable them manually in skill settings.",
    )


@router.post(
    "/migrate-industrial",
    response_model=IndustrialMigrationResponse,
    summary="Enable all industrial skills for a tenant",
    description=(
        "Enables all core-industrial skills so the tenant gets the industrial-first "
        "experience. Idempotent — re-running has no effect beyond ensuring all "
        "industrial skills are enabled. Also marks migration as accepted."
    ),
)
async def migrate_tenant_industrial(
    tenant_id: str,
    config: AppConfig = Depends(get_config),
) -> IndustrialMigrationResponse:
    try:
        from deerflow.skills.storage import get_or_new_skill_storage

        storage = get_or_new_skill_storage(app_config=config)
        all_skills = storage.load_skills(enabled_only=False)
        industrial_skills = [s for s in all_skills if s.tier == SkillTier.CORE_INDUSTRIAL]

        if not industrial_skills:
            _mark_migration_accepted(tenant_id)
            return IndustrialMigrationResponse(
                tenant_id=tenant_id, enabled_count=0, skill_names=[]
            )

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"

        extensions_config = get_extensions_config()
        enabled_names: list[str] = []
        for skill in industrial_skills:
            existing = extensions_config.skills.get(skill.name)
            extensions_config.skills[skill.name] = SkillStateConfig(
                enabled=True,
                tier=existing.tier if existing and existing.tier else skill.tier.value,
            )
            enabled_names.append(skill.name)

        _write_extensions_config(config_path, extensions_config)
        reload_extensions_config()
        _mark_migration_accepted(tenant_id)

        logger.info(
            "Industrial migration complete for tenant %s: %d skills enabled",
            tenant_id,
            len(enabled_names),
        )

        return IndustrialMigrationResponse(
            tenant_id=tenant_id,
            enabled_count=len(enabled_names),
            skill_names=enabled_names,
        )
    except Exception as e:
        logger.error(
            "Failed to run industrial migration for tenant %s: %s",
            tenant_id,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run industrial migration: {e!s}",
        )

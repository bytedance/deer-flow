"""Read-only module feature flags."""

from __future__ import annotations

from fastapi import APIRouter

from app.gateway.deps import get_config

router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.get("")
async def get_modules() -> dict:
    """Return public feature gates for optional DeerFlow modules."""
    modules = get_config().modules
    return {
        "durable_workflows": modules.durable_workflows.model_dump(),
    }

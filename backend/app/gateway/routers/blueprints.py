"""REST API for template blueprints.

Provides endpoints for listing blueprints, getting details, and creating
new templates from blueprints. Read-only operations require authentication
only; creating from blueprint requires template write access.

    GET  /api/blueprints                       list all blueprints
    GET  /api/blueprints/{id}                  blueprint detail
    POST /api/blueprints/{id}/create-template  create template from blueprint
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deerflow.config.tenant import get_current_tenant_id
from deerflow.report_templates.blueprint_repository import (
    BlueprintNotFoundError,
    BlueprintRepositoryError,
    get_blueprint_repository,
)
from deerflow.report_templates.service import get_repository as get_template_repository
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blueprints", tags=["blueprints"])


# --------------------------------------------------------- Request/Response models


class BlueprintSummaryResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    icon: Optional[str] = None
    tags: list[str] = []
    executor_type: str = "direct"


class BlueprintDetailResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    icon: Optional[str] = None
    tags: list[str] = []
    executor_type: str = "direct"
    base_dsl: dict[str, Any]
    user_configurable: list[dict[str, Any]] = []
    recommended_scripts: list[str] = []
    preview_sections: list[dict[str, Any]] = []


class CreateFromBlueprintRequest(BaseModel):
    name: str = Field(..., description="Name for the new template")
    visibility: str = Field(default="private", description="private or tenant")


class CreateFromBlueprintResponse(BaseModel):
    template_id: str
    message: str


# --------------------------------------------------------- Routes


@router.get("", response_model=list[BlueprintSummaryResponse])
async def list_blueprints(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by category"),
) -> list[BlueprintSummaryResponse]:
    """List all available blueprints."""
    try:
        repo = get_blueprint_repository()
        blueprints = repo.list_blueprints(category=category)
        return [
            BlueprintSummaryResponse(
                id=bp.id,
                name=bp.name,
                description=bp.description,
                category=bp.category,
                icon=bp.icon,
                tags=bp.tags,
                executor_type=bp.executor_type,
            )
            for bp in blueprints
        ]
    except BlueprintRepositoryError as e:
        logger.error(f"Failed to list blueprints: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load blueprints: {e}")


@router.get("/{blueprint_id}", response_model=BlueprintDetailResponse)
async def get_blueprint(
    blueprint_id: str,
    request: Request,
) -> BlueprintDetailResponse:
    """Get full details of a blueprint including its base DSL."""
    try:
        repo = get_blueprint_repository()
        bp = repo.get_blueprint(blueprint_id)
        return BlueprintDetailResponse(
            id=bp.id,
            name=bp.name,
            description=bp.description,
            category=bp.category,
            icon=bp.icon,
            tags=bp.tags,
            executor_type=bp.executor_type,
            base_dsl=bp.base_dsl.model_dump(mode="json"),
            user_configurable=[f.model_dump(mode="json") for f in bp.user_configurable],
            recommended_scripts=bp.recommended_scripts,
            preview_sections=[s.model_dump(mode="json") for s in bp.preview_sections],
        )
    except BlueprintNotFoundError:
        raise HTTPException(status_code=404, detail=f"Blueprint '{blueprint_id}' not found")


@router.post("/{blueprint_id}/create-template", response_model=CreateFromBlueprintResponse)
async def create_from_blueprint(
    blueprint_id: str,
    body: CreateFromBlueprintRequest,
    request: Request,
) -> CreateFromBlueprintResponse:
    """Create a new template draft from a blueprint.

    Copies the blueprint's base DSL into a new private/tenant template
    that the user can then customize in the visual editor.
    """
    try:
        bp_repo = get_blueprint_repository()
        bp = bp_repo.get_blueprint(blueprint_id)
    except BlueprintNotFoundError:
        raise HTTPException(status_code=404, detail=f"Blueprint '{blueprint_id}' not found")

    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id()

    from deerflow.report_templates.repository import Scope

    if body.visibility == "private":
        scope = Scope.private(user_id)
    elif body.visibility == "tenant":
        scope = Scope.tenant(tenant_id)
    else:
        raise HTTPException(status_code=400, detail=f"unsupported visibility: {body.visibility}")

    template_repo = get_template_repository()
    try:
        record = template_repo.create_template(
            scope=scope,
            name=body.name,
            display_name=body.name,
            owner_user_id=user_id,
            tenant_id=tenant_id,
            description=bp.description,
        )

        dsl_dict = bp.base_dsl.model_dump(mode="json")
        dsl_dict["name"] = body.name
        dsl_dict["display_name"] = body.name
        dsl_dict["visibility"] = body.visibility

        import yaml
        dsl_yaml = yaml.dump(dsl_dict, default_flow_style=False, allow_unicode=True)
        template_repo.save_draft(
            scope=scope,
            template_id=record.id,
            dsl=dsl_dict,
            dsl_yaml=dsl_yaml,
            expected_etag=record.etag,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create template from blueprint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create template: {e}")

    return CreateFromBlueprintResponse(
        template_id=record.id,
        message=f"Created template '{body.name}' from blueprint '{bp.name}'",
    )

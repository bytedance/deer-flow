"""REST API for report templates (Phase 5 — §8.3 of the design).

Endpoints mirror the 6 lifecycle tools that already exist for LLM use, but
expose them as authenticated HTTP routes so the frontend management UI can
operate on templates without going through a chat session.

    GET    /api/report-templates                 list (filter by visibility)
    GET    /api/report-templates/{id}             metadata only
    GET    /api/report-templates/{id}/versions    list version numbers
    GET    /api/report-templates/{id}/versions/{n}  one version snapshot
    POST   /api/report-templates                  create draft
    PUT    /api/report-templates/{id}             update draft
    POST   /api/report-templates/{id}/validate    pre-flight validate
    POST   /api/report-templates/{id}/publish     publish new immutable version
    POST   /api/report-templates/{id}/fork        fork into caller's drafts
    POST   /api/report-templates/{id}/archive     soft-archive
    DELETE /api/report-templates/{id}             hard-delete

Permissions reuse ``deerflow.report_templates.permissions.check_permission``
so the matrix stays single-source-of-truth with the LLM tool path.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deerflow.config.tenant import get_current_tenant_id
from deerflow.persistence.agent.auth import is_tenant_admin
from deerflow.report_templates.permissions import Principal, check_permission
from deerflow.report_templates.repository import (
    BuiltinNotWritableError,
    EtagMismatchError,
    ImmutablePublishedError,
    RepositoryError,
    Scope,
    TemplateNotFoundError,
    VersionNotFoundError,
)
from deerflow.report_templates.script_registry import get_registry
from deerflow.report_templates.service import get_repository
from deerflow.report_templates.validator import validate_dsl
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/report-templates", tags=["report-templates"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _principal_from_request(request: Request) -> Principal:
    """Build a ``Principal`` from FastAPI session state.

    Falls back to context-vars when the request has no attached user (no-auth mode).
    """
    user = getattr(request.state, "user", None)
    role = getattr(user, "system_role", "") if user is not None else ""
    user_id = (
        getattr(user, "id", None) if user is not None else None
    ) or get_effective_user_id()
    tenant_id = (
        getattr(user, "tenant_id", None) if user is not None else None
    ) or get_current_tenant_id()
    return Principal(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        is_superadmin=(role == "superadmin"),
        is_tenant_admin=is_tenant_admin(role),
    )


def _scope_from_visibility(visibility: str, principal: Principal) -> Scope:
    if visibility == "private":
        return Scope.private(principal.user_id)
    if visibility == "tenant":
        return Scope.tenant(principal.tenant_id)
    if visibility == "builtin":
        return Scope.builtin()
    raise HTTPException(status_code=400, detail=f"unknown visibility {visibility!r}")


def _resolve_template(template_id: str, principal: Principal):
    """Look up a template across private → tenant → builtin and return (scope, record)."""
    repo = get_repository()
    for scope_factory in (
        lambda: Scope.private(principal.user_id),
        lambda: Scope.tenant(principal.tenant_id),
        Scope.builtin,
    ):
        try:
            scope = scope_factory()
            record = repo.get_template(scope, template_id)
            return scope, record
        except (TemplateNotFoundError, BuiltinNotWritableError, ValueError):
            continue
    raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")


def _enforce(operation: str, principal: Principal, record) -> None:
    decision = check_permission(
        principal=principal, operation=operation, template=record  # type: ignore[arg-type]
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    description: str = ""
    visibility: str = Field(default="private")
    tags: list[str] | None = None
    dsl: dict[str, Any]
    dsl_yaml: str = ""


class UpdateTemplateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    dsl: dict[str, Any]
    dsl_yaml: str = ""
    expected_etag: str


class ValidateRequest(BaseModel):
    dsl: dict[str, Any]


class PublishRequest(BaseModel):
    expected_current_version: int
    changelog: str = ""


class ForkRequest(BaseModel):
    source_version: int = Field(..., ge=1)
    new_name: str
    new_display_name: str


class ArchiveRequest(BaseModel):
    expected_etag: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", summary="List report templates")
async def list_templates(
    request: Request,
    visibility: str = Query("private"),
):
    principal = _principal_from_request(request)
    scope = _scope_from_visibility(visibility, principal)
    repo = get_repository()
    entries = repo.list_templates(scope)
    return {"templates": [e.model_dump() for e in entries]}


@router.get("/{template_id}", summary="Get template metadata")
async def get_template(template_id: str, request: Request):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("view", principal, record)
    return {"template": record.model_dump(), "scope": record.visibility}


@router.get("/{template_id}/versions", summary="List version numbers")
async def list_versions(template_id: str, request: Request):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("view", principal, record)
    return {"versions": get_repository().list_versions(scope, template_id)}


@router.get("/{template_id}/versions/{version}", summary="Get version snapshot")
async def get_version(template_id: str, version: int, request: Request):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("view", principal, record)
    try:
        snapshot = get_repository().get_version(scope, template_id, version)
    except VersionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"version": snapshot.model_dump()}


@router.post("", status_code=201, summary="Create draft template")
async def create_template(body: CreateTemplateRequest, request: Request):
    principal = _principal_from_request(request)

    # Validate DSL before any write.
    report = validate_dsl(body.dsl, registry=get_registry())
    if not report.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_DSL",
                "errors": [e.to_dict() for e in report.errors],
                "warnings": [w.to_dict() for w in report.warnings],
            },
        )

    # Permission check: private always OK; tenant requires tenant_admin;
    # builtin requires superadmin.
    if body.visibility == "tenant" and not (
        principal.is_tenant_admin or principal.is_superadmin
    ):
        raise HTTPException(status_code=403, detail="tenant templates require tenant_admin")
    if body.visibility == "builtin" and not principal.is_superadmin:
        raise HTTPException(status_code=403, detail="builtin templates require superadmin")

    repo = get_repository()
    scope = _scope_from_visibility(body.visibility, principal)
    created = repo.create_template(
        scope=scope,
        name=body.name,
        display_name=body.display_name,
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        description=body.description,
        tags=body.tags,
    )
    updated = repo.save_draft(
        scope=scope,
        template_id=created.id,
        dsl=body.dsl,
        dsl_yaml=body.dsl_yaml,
        display_name=body.display_name,
        description=body.description,
        tags=body.tags,
        expected_etag=created.etag,
    )
    return {"template": updated.model_dump()}


@router.put("/{template_id}", summary="Update draft template")
async def update_template(
    template_id: str, body: UpdateTemplateRequest, request: Request
):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("edit_draft", principal, record)

    report = validate_dsl(body.dsl, registry=get_registry())
    if not report.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_DSL",
                "errors": [e.to_dict() for e in report.errors],
                "warnings": [w.to_dict() for w in report.warnings],
            },
        )

    try:
        updated = get_repository().save_draft(
            scope=scope,
            template_id=template_id,
            dsl=body.dsl,
            dsl_yaml=body.dsl_yaml,
            display_name=body.display_name,
            description=body.description,
            tags=body.tags,
            expected_etag=body.expected_etag,
        )
    except EtagMismatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ImmutablePublishedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"template": updated.model_dump()}


@router.post("/{template_id}/validate", summary="Validate template DSL pre-save")
async def validate_template(template_id: str, body: ValidateRequest, request: Request):
    principal = _principal_from_request(request)
    _resolve_template(template_id, principal)  # 404 if missing / hidden
    report = validate_dsl(body.dsl, registry=get_registry())
    return report.to_dict()


@router.post("/{template_id}/publish", summary="Publish a new version")
async def publish_template(
    template_id: str, body: PublishRequest, request: Request
):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("publish", principal, record)
    try:
        published = get_repository().publish(
            scope=scope,
            template_id=template_id,
            expected_current_version=body.expected_current_version,
            changelog=body.changelog,
        )
    except EtagMismatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"template": published.model_dump()}


@router.post("/{template_id}/fork", summary="Fork a readable template")
async def fork_template(template_id: str, body: ForkRequest, request: Request):
    principal = _principal_from_request(request)
    source_scope, source_record = _resolve_template(template_id, principal)
    _enforce("fork", principal, source_record)
    try:
        forked = get_repository().fork(
            source_scope=source_scope,
            source_template_id=template_id,
            source_version=body.source_version,
            target_scope=Scope.private(principal.user_id),
            target_owner_user_id=principal.user_id,
            target_tenant_id=principal.tenant_id,
            new_name=body.new_name,
            new_display_name=body.new_display_name,
        )
    except VersionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"template": forked.model_dump()}


@router.post("/{template_id}/archive", summary="Archive (soft-disable) a template")
async def archive_template(
    template_id: str, body: ArchiveRequest, request: Request
):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("archive", principal, record)
    try:
        archived = get_repository().archive(
            scope=scope, template_id=template_id, expected_etag=body.expected_etag
        )
    except EtagMismatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"template": archived.model_dump()}


@router.delete("/{template_id}", summary="Hard-delete a template")
async def delete_template(
    template_id: str,
    request: Request,
    expected_etag: str = Query(...),
):
    principal = _principal_from_request(request)
    scope, record = _resolve_template(template_id, principal)
    _enforce("delete", principal, record)
    try:
        get_repository().delete(
            scope=scope, template_id=template_id, expected_etag=expected_etag
        )
    except EtagMismatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"deleted": True}

"""REST API for template marketplace.

Endpoints for browsing, installing, reviewing, and publishing templates.

    GET  /api/template-marketplace                          list listings (search/filter/sort)
    GET  /api/template-marketplace/{id}                     listing detail with reviews
    POST /api/template-marketplace/{id}/reviews             submit rating + review
    POST /api/template-marketplace/{id}/install             install to private/tenant space
    POST /api/report-templates/{id}/publish-to-marketplace  create marketplace listing
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_auth, require_permission
from deerflow.config.tenant import get_current_tenant_id
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.marketplace.repository import MarketplaceRepository
from deerflow.report_templates.permissions import Principal, check_permission
from deerflow.report_templates.repository import (
    RepositoryError,
    Scope,
    TemplateNotFoundError,
    VersionNotFoundError,
)
from deerflow.report_templates.service import get_repository
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/template-marketplace", tags=["template-marketplace"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _principal_from_request(request: Request):
    """Build Principal from request state."""
    from deerflow.persistence.agent.auth import is_tenant_admin

    user = getattr(request.state, "user", None)
    # Fallback to auth context user (set by @require_permission decorator)
    if user is None:
        auth = getattr(request.state, "auth", None)
        user = getattr(auth, "user", None) if auth is not None else None
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


def _resolve_template(template_id: str, principal: Principal):
    """Look up a template across private → tenant → builtin."""
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
        except (TemplateNotFoundError, Exception):
            continue
    raise HTTPException(status_code=404, detail=f"template {template_id!r} not found")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ListingResponse(BaseModel):
    id: str
    tenant_id: str
    template_id: str
    template_version: int
    display_name: str
    description: str
    visibility: str
    category: str | None
    tags: list[str] | None
    icon: str | None
    avg_rating: float
    review_count: int
    install_count: int
    status: str
    created_by: str
    created_at: str
    updated_at: str


class ReviewResponse(BaseModel):
    id: str
    listing_id: str
    tenant_id: str
    user_id: str
    rating: int
    comment: str | None
    created_at: str


class InstallResponse(BaseModel):
    id: str
    listing_id: str
    tenant_id: str
    user_id: str
    target_template_id: str
    source_version: int
    installed_at: str


class CreateReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


class InstallRequest(BaseModel):
    target_visibility: str = Field(default="private", pattern="^(private|tenant)$")
    target_name: str | None = None


class PublishToMarketplaceRequest(BaseModel):
    display_name: str = Field(..., min_length=1)
    description: str
    visibility: str = Field(default="tenant", pattern="^(tenant|builtin)$")
    category: str | None = None
    tags: list[str] | None = None
    icon: str | None = None
    requires_approval: bool = True


class ApprovalRequest(BaseModel):
    approved: bool
    reason: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ListingResponse])
@require_permission("marketplace", "read")
async def list_listings(
    request: Request,
    search: str | None = Query(None, description="Search in display_name and description"),
    category: str | None = Query(None, description="Filter by category"),
    visibility: str | None = Query(None, description="Filter by visibility (tenant/builtin)"),
    sort_by: str = Query(default="created_at", pattern="^(created_at|avg_rating|install_count)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[ListingResponse]:
    """List marketplace listings with search, filter, and sort."""
    principal = _principal_from_request(request)
    repo = MarketplaceRepository(get_session_factory())

    # Only show tenant or builtin listings (not other tenants' private ones)
    listings, _ = await repo.list_listings(
        tenant_id=principal.tenant_id if visibility is None else None,
        visibility=visibility,
        category=category,
        search=search,
        status="active",
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )

    return [ListingResponse(**listing) for listing in listings]


@router.get("/{listing_id}", response_model=ListingResponse)
@require_permission("marketplace", "read")
async def get_listing(
    listing_id: str,
    request: Request,
) -> ListingResponse:
    """Get listing detail."""
    repo = MarketplaceRepository(get_session_factory())
    listing = await repo.get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id!r} not found")
    return ListingResponse(**listing)


@router.get("/{listing_id}/reviews", response_model=list[ReviewResponse])
@require_permission("marketplace", "read")
async def list_reviews(
    listing_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[ReviewResponse]:
    """List reviews for a listing."""
    repo = MarketplaceRepository(get_session_factory())
    reviews, _ = await repo.list_reviews(listing_id, limit=limit, offset=offset)
    return [ReviewResponse(**review) for review in reviews]


@router.post("/{listing_id}/reviews", response_model=ReviewResponse)
@require_permission("marketplace", "write")
async def create_review(
    listing_id: str,
    body: CreateReviewRequest,
    request: Request,
) -> ReviewResponse:
    """Submit a rating and review for a listing."""
    principal = _principal_from_request(request)
    repo = MarketplaceRepository(get_session_factory())

    # Check if listing exists
    listing = await repo.get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id!r} not found")

    # Check if user already reviewed
    existing = await repo.get_user_review(listing_id, principal.user_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="you have already reviewed this listing")

    review = await repo.create_review(
        listing_id=listing_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        rating=body.rating,
        comment=body.comment,
    )

    return ReviewResponse(**review)


@router.post("/{listing_id}/install", response_model=InstallResponse)
@require_permission("marketplace", "write")
async def install_template(
    listing_id: str,
    body: InstallRequest,
    request: Request,
) -> InstallResponse:
    """Install a marketplace template to private/tenant space.

    Forks the template and records the installation.
    """
    principal = _principal_from_request(request)
    marketplace_repo = MarketplaceRepository(get_session_factory())
    template_repo = get_repository()

    # Get listing
    listing = await marketplace_repo.get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id!r} not found")

    # Resolve source template — search installer scopes first, then listing
    # publisher's private scope and listing tenant (cross-user/tenant installs).
    source_scope = None
    source_record = None
    try:
        source_scope, source_record = _resolve_template(listing["template_id"], principal)
    except HTTPException:
        for fallback_scope in (
            Scope.private(listing.get("created_by", "")),
            Scope.tenant(listing.get("tenant_id", "")),
        ):
            try:
                record = template_repo.get_template(fallback_scope, listing["template_id"])
                source_scope, source_record = fallback_scope, record
                break
            except (TemplateNotFoundError, ValueError, Exception):
                continue
        if source_record is None:
            raise HTTPException(
                status_code=404,
                detail=f"source template {listing['template_id']!r} has been removed from marketplace",
            )

    # Determine target scope
    if body.target_visibility == "private":
        target_scope = Scope.private(principal.user_id)
    elif body.target_visibility == "tenant":
        if not principal.is_tenant_admin and not principal.is_superadmin:
            raise HTTPException(status_code=403, detail="installing to tenant space requires tenant_admin")
        target_scope = Scope.tenant(principal.tenant_id)
    else:
        raise HTTPException(status_code=400, detail=f"unsupported target_visibility {body.target_visibility!r}")

    # Fork the template
    target_name = body.target_name or source_record.name
    target_display_name = (
        listing.get("display_name")
        or getattr(source_record, "display_name", None)
        or target_name
    )
    try:
        forked = template_repo.fork(
            source_scope=source_scope,
            source_template_id=listing["template_id"],
            source_version=int(listing["template_version"]),
            target_scope=target_scope,
            target_owner_user_id=principal.user_id,
            target_tenant_id=principal.tenant_id,
            new_name=target_name,
            new_display_name=target_display_name,
        )
    except VersionNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"source version not found: {e}")
    except RepositoryError as e:
        raise HTTPException(status_code=500, detail=f"fork failed: {e}")

    # Record installation
    install_record = await marketplace_repo.record_install(
        listing_id=listing_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        target_template_id=forked.id,
        source_version=listing["template_version"],
    )

    return InstallResponse(**install_record)


# ---------------------------------------------------------------------------
# Publish to marketplace (on report-templates router)
# ---------------------------------------------------------------------------

publish_router = APIRouter(tags=["report-templates"])


@publish_router.post("/api/report-templates/{template_id}/publish-to-marketplace")
@require_auth
@require_permission("marketplace", "publish")
async def publish_to_marketplace(
    template_id: str,
    body: PublishToMarketplaceRequest,
    request: Request,
) -> dict[str, Any]:
    """Publish a template to the marketplace.

    If requires_approval=True and user is not tenant_admin/superadmin,
    creates a pending listing that needs approval.
    """
    principal = _principal_from_request(request)
    get_repository()
    marketplace_repo = MarketplaceRepository(get_session_factory())

    # Resolve template
    try:
        scope, record = _resolve_template(template_id, principal)
    except HTTPException:
        raise

    # Check permission to publish

    decision = check_permission(principal=principal, operation="publish", template=record)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    # Determine if approval is needed
    needs_approval = body.requires_approval and not (principal.is_tenant_admin or principal.is_superadmin)

    # Get latest version
    if record.current_version == 0:
        raise HTTPException(status_code=400, detail="template has no published versions")
    latest_version = record.current_version

    # Check if already published
    existing = await marketplace_repo.get_listing_by_template(template_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"template {template_id!r} is already in marketplace")

    # Create listing
    listing = await marketplace_repo.create_listing(
        tenant_id=principal.tenant_id,
        template_id=template_id,
        template_version=latest_version,
        display_name=body.display_name,
        description=body.description,
        visibility=body.visibility,
        category=body.category,
        tags=body.tags,
        icon=body.icon,
        created_by=principal.user_id,
    )

    # Update status if pending
    if needs_approval:
        await marketplace_repo.update_listing(listing["id"], status="pending_approval")

    return {
        "listing_id": listing["id"],
        "status": listing["status"],
        "message": "submitted for approval" if needs_approval else "published",
    }


@publish_router.post("/api/template-marketplace/{listing_id}/approve")
@require_auth
@require_permission("marketplace", "publish")
async def approve_listing(
    listing_id: str,
    body: ApprovalRequest,
    request: Request,
) -> dict[str, Any]:
    """Approve or reject a pending marketplace listing (tenant_admin/superadmin only)."""
    principal = _principal_from_request(request)

    if not (principal.is_tenant_admin or principal.is_superadmin):
        raise HTTPException(status_code=403, detail="approval requires tenant_admin or superadmin")

    marketplace_repo = MarketplaceRepository(get_session_factory())
    listing = await marketplace_repo.get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id!r} not found")

    if listing["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail=f"listing is not pending approval (status: {listing['status']})")

    # Check tenant ownership
    if listing["tenant_id"] != principal.tenant_id and not principal.is_superadmin:
        raise HTTPException(status_code=403, detail="cannot approve listings from other tenants")

    new_status = "active" if body.approved else "rejected"
    await marketplace_repo.update_listing(listing_id, status=new_status)

    return {
        "listing_id": listing_id,
        "status": new_status,
        "message": "approved" if body.approved else f"rejected: {body.reason or 'no reason provided'}",
    }


# publish_router is registered separately in app.py (no prefix)
# so that /api/report-templates/{id}/publish-to-marketplace and
# /api/template-marketplace/{id}/approve are not nested under
# the /api/template-marketplace prefix.

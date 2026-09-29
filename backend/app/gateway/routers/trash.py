"""Trash API (Projects Phase 2 Slice D): recoverable shelf deletion.

Routes under ``/api/trash``: list trashed documents (lazily triggering the
retention sweep first, §8.3), restore one into an active project, purge one
permanently, and empty the trash (purge every trashed row of the caller,
regardless of age — retention expiry is the sweep's job alone). Fail closed
everywhere: a missing or foreign document/project is a 404 (never a 403 that
leaks existence), restoring into an archived or foreign target is the same
404 (§8.4), and a memory-backend deployment answers 503 ``"Projects"`` through
the shared ``_require`` accessor convention (§11). Purge carries no
confirmation parameter — the "this cannot be undone" step is a UI contract,
not a server-enforced handshake (§11).
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_project_document_repo, get_project_repo
from app.gateway.routers.project_documents import ProjectDocumentResponse, _to_response
from deerflow.config.paths import get_paths
from deerflow.config.projects_config import ProjectsConfig
from deerflow.projects.trash import make_purge_file_remover, purge_all_trashed, restore_document, run_trash_retention_sweep
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trash", tags=["trash"])

# The reconciliation half of the retention sweep walks every row and every
# file of the caller (``list_all_for_sweep`` + a stat per row + a walk of
# ``projects/**``), while the expiry purge is an indexed candidate scan. Since
# reconciliation only bounds external interference and orphaned staging — both
# already behind the 24-hour guard — the lazy listing trigger throttles it to
# one run per user per interval. The retention guarantee is unaffected: expiry
# purging still runs on every trigger, and the startup sweep reconciles
# unconditionally.
_RECONCILIATION_MIN_INTERVAL_SECONDS = 900
_LAST_RECONCILIATION: dict[str, float] = {}


def _reconciliation_due(user_key: str) -> bool:
    now = time.monotonic()
    last = _LAST_RECONCILIATION.get(user_key)
    if last is not None and now - last < _RECONCILIATION_MIN_INTERVAL_SECONDS:
        return False
    _LAST_RECONCILIATION[user_key] = now
    return True


class TrashOrigin(BaseModel):
    """``{project_id, project_name}`` snapshot taken when the row was trashed."""

    project_id: str
    project_name: str


class TrashDocumentResponse(BaseModel):
    """One trashed shelf row plus its trash-tier display fields (§6.5)."""

    id: str
    name: str
    size_bytes: int
    sha256: str
    source_thread_id: str | None = None
    source_kind: str | None = None
    source_name: str | None = None
    created_at: str
    updated_at: str
    trashed_at: str
    trash_origin: TrashOrigin | None = None


class TrashListResponse(BaseModel):
    documents: list[TrashDocumentResponse]
    total: int
    limit: int
    offset: int


class RestoreRequest(BaseModel):
    """Optional target; required only when the origin project is gone/archived."""

    project_id: str | None = None


class RestoreResponse(BaseModel):
    """``merged`` when the target already served identical bytes: the trash row
    is gone and ``document`` is the surviving active row (§8.2)."""

    outcome: Literal["restored", "merged"]
    document: ProjectDocumentResponse


class PurgeResponse(BaseModel):
    purged: int


def _projects_config() -> ProjectsConfig:
    """Projects config, falling back to defaults when the app config is unavailable."""
    from deerflow.config.app_config import get_app_config

    try:
        return get_app_config().projects
    except Exception:
        return ProjectsConfig()


def _not_found() -> HTTPException:
    # Fail closed: foreign documents/projects are indistinguishable from missing.
    return HTTPException(status_code=404, detail="Trash document not found")


def _to_trash_response(row: dict) -> TrashDocumentResponse:
    origin = row.get("trash_origin") or None
    return TrashDocumentResponse(
        id=row["id"],
        name=row.get("name", ""),
        size_bytes=row.get("size_bytes", 0),
        sha256=row.get("sha256", ""),
        source_thread_id=row.get("source_thread_id"),
        source_kind=row.get("source_kind"),
        source_name=row.get("source_name"),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
        trashed_at=row.get("trashed_at", ""),
        trash_origin=TrashOrigin(project_id=origin["project_id"], project_name=origin["project_name"]) if origin else None,
    )


@router.get("/documents", response_model=TrashListResponse)
@require_permission("projects", "read")
async def list_trash_documents(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> TrashListResponse:
    """List the caller's trashed documents (most recently trashed first).

    Triggers the retention sweep lazily before listing (§8.3); a sweep
    failure is logged and never blocks the listing.
    """
    repo = get_project_document_repo(request)
    user_id = get_effective_user_id()
    try:
        await run_trash_retention_sweep(
            repo,
            get_paths(),
            retention_days=_projects_config().trash_retention_days,
            user_id=user_id,
            include_reconciliation=_reconciliation_due(user_id),
        )
    except Exception:
        logger.warning("Lazy trash retention sweep failed; listing trash anyway", exc_info=True)
    rows = await repo.list_trashed(limit=limit, offset=offset)
    total = await repo.count_trashed()
    return TrashListResponse(
        documents=[_to_trash_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/documents/{document_id}/restore", response_model=RestoreResponse)
@require_permission("projects", "write")
async def restore_trash_document(document_id: str, request: Request, body: RestoreRequest | None = None) -> RestoreResponse:
    """Restore one trashed document into an active project (§8.2).

    Target = the body's ``project_id``, else ``trash_origin.project_id`` when
    that project still exists, is owned, and is active; otherwise 404 (the UI
    offers the project picker). A foreign or archived target is the same 404
    as a missing one. A merge into an active row with identical bytes reports
    ``merged``; missing or size-mismatched content answers 409
    ``content_missing`` and leaves the row trashed (§11).
    """
    repo = get_project_document_repo(request)
    user_id = get_effective_user_id()
    target = body.project_id if body is not None else None
    if not target:
        # Read-only probe for the origin hint; restore revalidates everything
        # under its locks, so this decides nothing (§15.5).
        row = await repo.get(document_id, include_trashed=True)
        if row is None:
            raise _not_found()
        origin_id = (row.get("trash_origin") or {}).get("project_id")
        if origin_id:
            origin = await get_project_repo(request).get(origin_id)
            if origin is not None and origin.get("status") == "active":
                target = origin_id
        if not target:
            raise _not_found()
    outcome, restored = await restore_document(repo, get_paths(), user_id=user_id, document_id=document_id, target_project_id=target)
    if outcome in ("not_found", "no_target"):
        raise _not_found()
    if outcome == "content_missing":
        raise HTTPException(status_code=409, detail="content_missing")
    assert restored is not None
    return RestoreResponse(outcome=outcome, document=_to_response(restored))


@router.post("/documents/{document_id}/purge", status_code=204)
@require_permission("projects", "delete")
async def purge_trash_document(document_id: str, request: Request) -> None:
    """Permanently purge one trashed document: bytes first, then the row (§8.3).

    A file-cleanup failure other than already-absent content rolls the
    transaction back, keeps the trashed row, and answers 500 with a retryable
    message (§11); ``False`` from the repository is the fail-closed 404.
    """
    repo = get_project_document_repo(request)
    try:
        purged = await repo.purge(document_id, remove_files=make_purge_file_remover(get_paths(), user_id=get_effective_user_id()))
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Purge failed during file cleanup; the document remains in trash and the purge can be retried") from exc
    if not purged:
        raise _not_found()


@router.post("/purge", response_model=PurgeResponse)
@require_permission("projects", "delete")
async def empty_trash(request: Request) -> PurgeResponse:
    """Empty the trash: purge every trashed document of the caller (§8.3).

    Age-independent by design — the confirmation covers the whole listing, so
    the retention cutoff plays no part here; the retention sweep (the lazy one
    on ``GET /api/trash/documents`` and the startup one) stays the only
    age-gated purge. Removals go through the same guarded per-row transaction
    as a single delete: bytes first, then the row. A filesystem failure other
    than already-absent content answers 500 with a retryable message; that row
    and every row not yet visited stay trashed.
    """
    repo = get_project_document_repo(request)
    try:
        purged = await purge_all_trashed(repo, get_paths(), user_id=get_effective_user_id())
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Purge failed during file cleanup; the remaining documents stay in trash and the purge can be retried") from exc
    return PurgeResponse(purged=purged)

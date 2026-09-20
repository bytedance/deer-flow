"""Project document shelf API (Projects Phase 2 Slice B).

Routes under ``/api/projects/{project_id}/documents``: upload one file,
list the shelf, read/download a document's content, and move a document to
trash. Trashed rows are invisible to every endpoint. Fail closed everywhere:
a missing or foreign project/document is a 404 (never a 403 that leaks
existence), an archived project rejects uploads and individual trash with the
same 404 (§8.4), and a memory-backend deployment answers 503 ``"Projects"``
through the shared ``_require`` accessor convention (§11).
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_project_document_repo, get_project_repo, get_thread_store
from app.gateway.routers.uploads import DEFAULT_MAX_FILE_SIZE, UPLOAD_CHUNK_SIZE, _get_upload_limit
from app.gateway.upload_ingestion import ThreadUploadIngestionService, UnsafeFilenameError, UnsafeUploadDestinationError
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths, get_paths
from deerflow.projects.documents import (
    ShelfContentMissingError,
    ShelfUploadTooLargeError,
    _content_intact_batch,
    add_staged_document,
    check_document_content,
    read_file_chunks,
    resolve_document_paths,
    stage_document_bytes,
    stage_document_copy_for_attach,
    validate_shelf_filename,
)
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import normalize_filename
from deerflow.utils.file_io import run_file_io
from deerflow.utils.text_detection import _is_active_content_mime_type, is_text_file_by_content
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["project-documents"])


class ProjectDocumentResponse(BaseModel):
    """One active shelf row. Internal columns (``user_id``, ``stored_relpath``,
    trash fields) never leave the server; trashed rows never reach it."""

    id: str
    name: str
    size_bytes: int
    sha256: str
    source_thread_id: str | None = None
    source_kind: str | None = None
    source_name: str | None = None
    created_at: str
    updated_at: str
    #: Read-time truth (never a persisted column): the immutable original is
    #: missing or size-mismatched — external interference, §8.3/§11. The
    #: derived companion is not the integrity anchor; the original is.
    content_missing: bool = False


class ProjectDocumentListResponse(BaseModel):
    documents: list[ProjectDocumentResponse]
    total: int
    limit: int
    offset: int


class ProjectDocumentUploadResponse(BaseModel):
    """``deduplicated`` distinguishes the 200 hit (existing row, first name

    wins, §10.9) from the 201 created row."""

    document: ProjectDocumentResponse
    deduplicated: bool


def _to_response(row: dict, *, content_missing: bool = False) -> ProjectDocumentResponse:
    return ProjectDocumentResponse(
        id=row["id"],
        name=row.get("name", ""),
        size_bytes=row.get("size_bytes", 0),
        sha256=row.get("sha256", ""),
        source_thread_id=row.get("source_thread_id"),
        source_kind=row.get("source_kind"),
        source_name=row.get("source_name"),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
        content_missing=content_missing,
    )


def _not_found() -> HTTPException:
    # Fail closed: foreign projects/documents are indistinguishable from missing.
    return HTTPException(status_code=404, detail="Project document not found")


#: Non-text MIME families a browser renders inline WITHOUT executing script
#: on the application origin (the sandboxed preview iframe navigates to the
#: content endpoint). Active content (HTML/XML family) is never viewable.
_INLINE_VIEWABLE_MIME_PREFIXES = ("image/", "audio/", "video/")


def _is_inline_viewable_mime_type(media_type: str) -> bool:
    """Whether *media_type* may be served ``inline`` when ``download=false``.

    Passive text and browser-viewable binaries (PDF, image, audio, video)
    are inline-able; active content — HTML or any XML family type, including
    ``+xml`` subtypes such as SVG — never is (same rule as the artifacts
    router), regardless of the ``download`` flag.
    """
    if _is_active_content_mime_type(media_type):
        return False
    return media_type.startswith("text/") or media_type == "application/pdf" or media_type.startswith(_INLINE_VIEWABLE_MIME_PREFIXES)


async def _require_project(request: Request, project_id: str) -> dict:
    """Owned project row in any status (archived keeps read access, §8.4), else 404."""
    row = await get_project_repo(request).get(project_id)
    if row is None:
        raise _not_found()
    return row


async def _stream_upload(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        yield chunk


@router.get("", response_model=ProjectDocumentListResponse)
@require_permission("projects", "read")
async def list_project_documents(
    project_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ProjectDocumentListResponse:
    await _require_project(request, project_id)
    repo = get_project_document_repo(request)
    rows = await repo.list_active(project_id, limit=limit, offset=offset)
    total = await repo.count_active(project_id)
    # Read-time integrity truth for the whole page in ONE offloaded pass:
    # files can only change via external interference, so the list surfaces
    # content_missing without a schema column (§8.3/§11).
    intact = await run_file_io(_content_intact_batch, get_paths(), user_id=get_effective_user_id(), rows=rows)
    return ProjectDocumentListResponse(
        documents=[_to_response(row, content_missing=not ok) for row, ok in zip(rows, intact, strict=True)],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ProjectDocumentUploadResponse, status_code=201)
@require_permission("projects", "write")
async def upload_project_document(
    project_id: str,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    config: AppConfig = Depends(get_config),
) -> ProjectDocumentUploadResponse:
    """Shelf exactly one file (§17.2): 201 created, or 200 on a content dedup hit.

    Active projects only — the shelf insert locks the project row with
    ``status='active'`` inside its transaction, so an archived/foreign/missing
    project is the same 404 (§8.4, §11). The display name defaults to the
    multipart filename; both go through the same validation (400 when empty,
    separator-bearing, or over 255 UTF-8 bytes). Size reuses
    ``uploads.max_file_size`` (413, mirroring the uploads router).
    """
    try:
        display_name = validate_shelf_filename(name) if name is not None else validate_shelf_filename(normalize_filename(file.filename or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = get_effective_user_id()
    paths = get_paths()
    max_file_size = _get_upload_limit(config, "max_file_size", DEFAULT_MAX_FILE_SIZE, legacy_key="max_single_file_size")
    try:
        staged = await stage_document_bytes(paths, user_id=user_id, project_id=project_id, chunks=_stream_upload(file), max_bytes=max_file_size)
    except ShelfUploadTooLargeError:
        raise HTTPException(status_code=413, detail=f"File too large: {display_name}")
    except ValueError:
        # Unsafe project_id charset — fail closed, indistinguishable from missing.
        raise _not_found()
    if staged.size_bytes == 0:
        await run_file_io(staged.staging_path.unlink, True)
        raise HTTPException(status_code=400, detail="Empty file")

    result = await add_staged_document(
        get_project_document_repo(request),
        paths,
        user_id=user_id,
        project_id=project_id,
        name=display_name,
        staged=staged,
        source_kind="upload",
    )
    if result is None:
        raise _not_found()
    row, created = result
    if not created:
        # Dedup hit: same body, 200 instead of 201 — the first writer's name
        # and provenance win (§10.9).
        response.status_code = 200
    return ProjectDocumentUploadResponse(document=_to_response(row), deduplicated=not created)


class PromoteThreadFileRequest(BaseModel):
    """Save-to-shelf body (§7.4): locate one thread file, optional shelf rename."""

    thread_id: str
    kind: Literal["upload", "output"]
    name: str
    shelf_name: str | None = None


class AttachDocumentResponse(BaseModel):
    """The completed thread attachment — returned only after ingestion succeeds (§7.3 item 3)."""

    filename: str
    size_bytes: int
    virtual_path: str
    artifact_url: str


def _resolve_thread_source(paths: Paths, *, user_id: str, thread_id: str, kind: str, name: str) -> Path | None:
    """Resolve the source file inside the thread's own uploads/outputs dir.

    Confinement failure is indistinguishable from absence (§11): a separator-
    bearing or dot name, an escape of the thread directory (a symlink is
    followed and re-checked), a missing file, or an unsafe thread id all
    return ``None`` → 404. The boundary is the TRUSTED thread storage root —
    established unresolved from the server-owned base (resolving it would let
    a planted symlink turn an external directory into the trusted base and
    break user-bucket isolation): the resolved kind directory must live under
    that root, and the resolved candidate under the kind directory, so a
    symlinked uploads/outputs dir escaping thread storage is ``None`` while
    an in-root symlink keeps working (same behavior as virtual-path
    resolution). Runs in the file-IO worker (called via ``run_file_io``).
    """
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    try:
        thread_root = paths.thread_dir(thread_id, user_id=user_id)
        kind_dir = (paths.sandbox_uploads_dir(thread_id, user_id=user_id) if kind == "upload" else paths.sandbox_outputs_dir(thread_id, user_id=user_id)).resolve()
        kind_dir.relative_to(thread_root)
        candidate = (kind_dir / name).resolve()
        candidate.relative_to(kind_dir)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


@router.post("/from-thread", response_model=ProjectDocumentUploadResponse, status_code=201)
@require_permission("projects", "write")
@require_permission("threads", "read")
async def promote_thread_file_to_shelf(
    project_id: str,
    body: PromoteThreadFileRequest,
    request: Request,
    response: Response,
    config: AppConfig = Depends(get_config),
) -> ProjectDocumentUploadResponse:
    """Copy one thread file (upload or output) into the shelf (§7.4).

    The source is never moved — the shelf gets a project-owned snapshot with
    provenance (``source_thread_id``/``source_kind``/``source_name``), so
    deleting the thread cannot affect it. ``shelf_name`` defaults to the
    source name and follows upload-name validation. The shelf insert locks
    the project row with ``status='active'``, so an archived/foreign/missing
    project is the same 404 as a source that fails confinement (§8.4, §11).
    Response mirrors upload: 201 created, 200 on a content dedup hit (the
    existing row keeps its own name and provenance, §10.9).
    """
    if await get_thread_store(request).get(body.thread_id) is None:
        raise _not_found()
    repo = get_project_document_repo(request)
    try:
        display_name = validate_shelf_filename(body.shelf_name) if body.shelf_name is not None else validate_shelf_filename(normalize_filename(body.name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = get_effective_user_id()
    paths = get_paths()
    source = await run_file_io(_resolve_thread_source, paths, user_id=user_id, thread_id=body.thread_id, kind=body.kind, name=body.name)
    if source is None:
        raise _not_found()

    max_file_size = _get_upload_limit(config, "max_file_size", DEFAULT_MAX_FILE_SIZE, legacy_key="max_single_file_size")
    try:
        staged = await stage_document_bytes(paths, user_id=user_id, project_id=project_id, chunks=read_file_chunks(source, chunk_size=UPLOAD_CHUNK_SIZE), max_bytes=max_file_size)
    except ShelfUploadTooLargeError:
        raise HTTPException(status_code=413, detail=f"File too large: {display_name}")
    except ValueError:
        # Unsafe project_id charset — fail closed, indistinguishable from missing.
        raise _not_found()
    if staged.size_bytes == 0:
        await run_file_io(staged.staging_path.unlink, True)
        raise HTTPException(status_code=400, detail="Empty file")

    result = await add_staged_document(
        repo,
        paths,
        user_id=user_id,
        project_id=project_id,
        name=display_name,
        staged=staged,
        source_thread_id=body.thread_id,
        source_kind=body.kind,
        source_name=body.name,
    )
    if result is None:
        raise _not_found()
    row, created = result
    if not created:
        # Dedup hit: same body, 200 instead of 201 — the first writer's name
        # and provenance win (§10.9).
        response.status_code = 200
    return ProjectDocumentUploadResponse(document=_to_response(row), deduplicated=not created)


@router.post("/{document_id}/attach-to-thread/{thread_id}", response_model=AttachDocumentResponse)
@require_permission("projects", "write")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def attach_project_document_to_thread(
    project_id: str,
    document_id: str,
    thread_id: ThreadId,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> AttachDocumentResponse:
    """Materialize an independent copy of a shelf document into a thread (§7.3 item 3).

    The owned LIVE source document (an archived source project stays
    readable, §8.4 — its shelf is not mutated) is staged to a stable copy
    under its row lock, serialized against purge; the lock is then released
    and the shared thread-upload ingestion service takes over with ordinary
    upload lifecycle guarantees — size checks, optional conversion,
    sandbox-readable permissions, and non-mounted provider sync. Filename
    claiming is seeded from the thread's EXISTING uploads first, so the
    shelf copy never silently replaces a same-named thread file: it lands
    under a claimed unique name (``report_1.txt``), which the response
    reflects.
    The document transaction is never held across sandbox allocation or
    network sync. A target thread the caller cannot write is a 404 (the
    owner check above, ``require_existing``); the response is returned only
    after ingestion succeeds.
    """
    await _require_project(request, project_id)
    repo = get_project_document_repo(request)
    user_id = get_effective_user_id()
    paths = get_paths()
    try:
        staged = await stage_document_copy_for_attach(repo, paths, user_id=user_id, project_id=project_id, document_id=document_id)
    except ShelfContentMissingError:
        raise HTTPException(status_code=409, detail="content_missing")
    except ValueError:
        # Unsafe project_id charset — fail closed, indistinguishable from missing.
        raise _not_found()
    if staged is None:
        raise _not_found()
    row, staged_path = staged

    service = ThreadUploadIngestionService(request=request, thread_id=thread_id, user_id=user_id, app_config=config)
    try:
        try:
            await service.open()
            file_info = await service.ingest_chunks(read_file_chunks(staged_path, chunk_size=UPLOAD_CHUNK_SIZE), display_name=row["name"])
        except UnsafeFilenameError as exc:
            # Shelf names always normalize, so this cannot fire — fail closed.
            await service.cleanup_written()
            raise HTTPException(status_code=500, detail=f"Failed to upload {row['name']}: {exc}")
        except UnsafeUploadDestinationError as exc:
            await service.cleanup_written()
            raise HTTPException(status_code=500, detail=f"Failed to upload {row['name']}: {exc}")
        except HTTPException:
            await service.cleanup_written()
            raise
        except Exception as exc:
            logger.error(f"Failed to attach {row['name']} to thread {thread_id}: {exc}")
            await service.cleanup_written()
            raise HTTPException(status_code=500, detail=f"Failed to upload {row['name']}: {exc}")
        # Sync-phase failures (permissions/provider sync) follow ordinary
        # uploads: they propagate and the host files stay in place.
        await service.finalize()
    finally:
        await run_file_io(staged_path.unlink, True)
        await service.aclose()
    return AttachDocumentResponse(
        filename=file_info["filename"],
        size_bytes=file_info["size"],
        virtual_path=file_info["virtual_path"],
        artifact_url=file_info["artifact_url"],
    )


@router.get("/{document_id}/content")
@require_permission("projects", "read")
async def get_project_document_content(
    project_id: str,
    document_id: str,
    request: Request,
    download: bool = Query(default=False),
) -> FileResponse:
    """Inline text or attachment for one active shelf document (§6.5).

    ``download=false`` serves text inline (the converted-markdown companion
    when present, else the original when it samples as text) plus
    browser-viewable binaries — PDF, image, audio, video — for the sandboxed
    preview iframe, and streams other binaries as attachments.
    ``download=true`` always attaches the immutable ORIGINAL bytes under the
    original filename — the converted-markdown companion is preview-only, so
    a prior agent read never changes the download's format. Active content
    (HTML and the XML family, including ``+xml`` subtypes) is always forced to
    an attachment regardless of ``download`` so it never executes script on
    the application origin. A row whose original bytes are missing or
    size-mismatched answers with an explicit ``content_missing`` error (§11) —
    never an empty or substituted body.
    """
    await _require_project(request, project_id)
    row = await get_project_document_repo(request).get(document_id)
    if row is None or row.get("project_id") != project_id:
        raise _not_found()

    paths = get_paths()
    user_id = get_effective_user_id()
    # Validate the immutable ORIGINAL (existence AND recorded size, the one
    # shared §8.3 check) before selecting EITHER serving path: the derived
    # companion is only servable while its owning original validates (§6.2) —
    # a deleted or truncated original is ``content_missing``, never a healthy
    # preview.
    if not await check_document_content(paths, user_id=user_id, row=row):
        raise HTTPException(status_code=409, detail="content_missing")
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])

    serving_path = original
    media_type: str | None = None
    filename = row["name"]
    # The converted-markdown companion is a PREVIEW aid only: an explicit
    # download always serves the immutable original bytes under the original
    # filename — never a format that changed because an agent once read it.
    if not download and await run_file_io(derived.is_file):
        serving_path = derived
        media_type = "text/markdown"
        filename = f"{row['name']}.md"
    else:
        guessed, _ = await run_file_io(mimetypes.guess_type, str(original))
        media_type = guessed
    if media_type is None and not download and await run_file_io(is_text_file_by_content, serving_path):
        media_type = "text/plain"

    # Inline only what a browser can display WITHOUT running script on the
    # application origin: passive text, the converted-markdown companion, and
    # browser-viewable binaries (PDF, image, audio, video — the sandboxed
    # preview iframe navigates here). Active content (HTML or any XML family
    # type, including ``+xml`` subtypes such as SVG) is ALWAYS an attachment
    # regardless of ``download``, exactly like the artifacts router, and
    # ``download=true`` attaches everything.
    inline = not download and media_type is not None and _is_inline_viewable_mime_type(media_type)
    return FileResponse(
        serving_path,
        media_type=media_type or "application/octet-stream",
        filename=filename,
        # nosniff: a declared PDF/image/etc. must never be reinterpreted as
        # HTML — the transport-level guarantee behind unsandboxed PDF preview.
        headers={"X-Content-Type-Options": "nosniff"},
        content_disposition_type="inline" if inline else "attachment",
    )


@router.delete("/{document_id}", status_code=204)
@require_permission("projects", "delete")
async def delete_project_document(project_id: str, document_id: str, request: Request) -> None:
    """Move one document to trash (204). Restore/purge are the Slice-D trash tier.

    Archived shelves reject the write inside the repository's locked
    transaction, so they surface as the same fail-closed 404 (§8.4).
    """
    await _require_project(request, project_id)
    if not await get_project_document_repo(request).trash(document_id, project_id=project_id):
        raise _not_found()

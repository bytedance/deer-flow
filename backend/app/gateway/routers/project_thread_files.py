"""Conversation-files view for a project's member threads (Phase 2 Slice C).

``GET /api/projects/{project_id}/thread-files`` (§6.5/§7.4): a read-only
aggregation that pages member threads over the same non-archived ordering
the project thread list uses and reports each thread's uploads and outputs
(uploads via ``list_files_in_dir``; outputs via the new
``sandbox_outputs_dir`` listing — no outputs-listing endpoint exists
elsewhere). It keeps no storage of its own: entries disappear when their
thread is deleted, which is the honest ownership statement. The view is the
discovery route for Save to project and never feeds the shelf, the index,
or the tools. Per-thread file caps are reported per group
(``groups[].truncated``) and OR-ed into the envelope — never a silent cut.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_project_repo, get_thread_store
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import list_files_in_dir, output_artifact_url, upload_artifact_url
from deerflow.utils.file_io import run_file_io
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/thread-files", tags=["project-thread-files"])


class ThreadFileEntry(BaseModel):
    """One file in a member thread's uploads or outputs directory."""

    kind: Literal["upload", "output"]
    name: str
    size_bytes: int
    modified_at: str
    artifact_url: str


class ThreadFileGroup(BaseModel):
    """One member thread's contribution to the conversation-files view."""

    thread_id: str
    display_name: str | None = None
    updated_at: str
    files: list[ThreadFileEntry]
    #: True when this thread's file list was cut at ``file_limit`` — the
    #: per-group report behind the envelope's OR-ed ``truncated``.
    truncated: bool


class ThreadFilesResponse(BaseModel):
    """Paged groups plus the member-thread cursor and the truncation report."""

    groups: list[ThreadFileGroup]
    next_offset: int | None = None
    truncated: bool


def _not_found() -> HTTPException:
    # Fail closed: foreign projects are indistinguishable from missing ones.
    return HTTPException(status_code=404, detail="Project not found")


def _entry(kind: Literal["upload", "output"], thread_id: str, file: dict, artifact_url) -> ThreadFileEntry:
    modified = file.get("modified")
    modified_at = datetime.fromtimestamp(modified, tz=UTC).isoformat() if isinstance(modified, int | float) else ""
    return ThreadFileEntry(
        kind=kind,
        name=file["filename"],
        size_bytes=file["size"],
        modified_at=modified_at,
        artifact_url=artifact_url(thread_id, file["filename"]),
    )


async def _list_thread_files(paths: Paths, *, user_id: str, thread_id: str, file_limit: int) -> tuple[list[ThreadFileEntry], bool]:
    """List one thread's uploads + outputs, capped at ``file_limit`` entries.

    Returns ``(entries, truncated)`` — the cap is always reported, never a
    silent cut (§7.4). Uploads are listed via the shared
    ``list_files_in_dir``; outputs use the new ``sandbox_outputs_dir``
    listing this view introduces. Directory scans run in the file-IO worker.
    """
    uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=user_id)
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    uploads_listing = await run_file_io(list_files_in_dir, uploads_dir)
    outputs_listing = await run_file_io(list_files_in_dir, outputs_dir)
    entries = [_entry("upload", thread_id, f, upload_artifact_url) for f in uploads_listing["files"]]
    entries += [_entry("output", thread_id, f, output_artifact_url) for f in outputs_listing["files"]]
    truncated = len(entries) > file_limit
    return entries[:file_limit], truncated


@router.get("", response_model=ThreadFilesResponse)
@require_permission("projects", "read")
@require_permission("threads", "read")
async def list_project_thread_files(
    project_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    thread_limit: int = Query(default=20, ge=1, le=50),
    file_limit: int = Query(default=50, ge=1, le=200),
) -> ThreadFilesResponse:
    """Aggregate member threads' files, paged by thread (§6.5/§7.4).

    Member threads are paged (``thread_limit``) over the same non-archived
    ordering the project thread list uses — ``offset`` is the member-thread
    cursor and ``next_offset`` resumes it (``null`` when no threads remain).
    Each page thread contributes up to ``file_limit`` files across its
    uploads and outputs; a cut is reported per group (``groups[].truncated``)
    and OR-ed into the envelope ``truncated``.
    """
    if await get_project_repo(request).get(project_id) is None:
        raise _not_found()
    # One extra row decides whether another page exists; it is never rendered.
    rows = await get_thread_store(request).search(
        project_id=project_id,
        archived=False,
        limit=thread_limit + 1,
        offset=offset,
    )
    has_more = len(rows) > thread_limit
    page = rows[:thread_limit]

    user_id = get_effective_user_id()
    paths = get_paths()
    truncated = False
    groups: list[ThreadFileGroup] = []
    for row in page:
        thread_id = row["thread_id"]
        try:
            entries, thread_truncated = await _list_thread_files(paths, user_id=user_id, thread_id=thread_id, file_limit=file_limit)
        except ValueError:
            # A member row whose id cannot resolve to thread storage is
            # skipped rather than failing the whole view.
            logger.warning("Skipping thread-files listing for unresolvable thread id: %s", thread_id)
            continue
        truncated = truncated or thread_truncated
        groups.append(
            ThreadFileGroup(
                thread_id=thread_id,
                display_name=row.get("display_name"),
                updated_at=coerce_iso(row.get("updated_at", "")),
                files=entries,
                truncated=thread_truncated,
            )
        )
    return ThreadFilesResponse(
        groups=groups,
        next_offset=(offset + len(page)) if has_more else None,
        truncated=truncated,
    )

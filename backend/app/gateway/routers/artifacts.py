import asyncio
import functools
import hashlib
import logging
import mimetypes
import os
import stat
import tempfile
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_run_manager
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.path_utils import resolve_thread_virtual_path
from deerflow.config.paths import make_safe_user_id
from deerflow.runtime import ConflictError, ThreadOperationKind
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])

ACTIVE_CONTENT_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}

MAX_SKILL_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
_SKILL_ARCHIVE_READ_CHUNK_SIZE = 64 * 1024
MAX_EDITABLE_ARTIFACT_BYTES = 2 * 1024 * 1024
_EDITABLE_OUTPUTS_PREFIX = "mnt/user-data/outputs/"
_ARTIFACT_EDIT_TEMP_PREFIX = ".artifact-edit-"


class ArtifactUpdateRequest(BaseModel):
    content: str
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactUpdateResponse(BaseModel):
    path: str
    sha256: str
    size: int


@asynccontextmanager
async def reserve_artifact_write(request: Request, thread_id: str, *, user_id: str) -> AsyncIterator[None]:
    """Serialize an artifact edit against runs and other thread mutations."""
    run_manager = get_run_manager(request)
    async with run_manager.reserve_thread_operation(
        thread_id,
        kind=ThreadOperationKind.artifact_write,
        user_id=user_id,
    ):
        yield


def _normalize_editable_artifact_path(path: str) -> str:
    stripped = path.lstrip("/")
    if not stripped.startswith(_EDITABLE_OUTPUTS_PREFIX):
        raise HTTPException(status_code=400, detail="Only files in /mnt/user-data/outputs can be edited")
    if ".skill/" in stripped or stripped.endswith(".skill"):
        raise HTTPException(status_code=415, detail="Skill archives cannot be edited in the artifacts panel")
    return f"/{stripped}"


def _load_editable_artifact(actual_path: Path, path: str, expected_sha256: str) -> tuple[bytes, os.stat_result]:
    try:
        file_stat = os.lstat(actual_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}") from None
    if stat.S_ISLNK(file_stat.st_mode):
        raise HTTPException(status_code=415, detail="Symlinked artifacts cannot be edited")
    if not stat.S_ISREG(file_stat.st_mode):
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")
    if file_stat.st_size > MAX_EDITABLE_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="Artifact is too large to edit")

    current = actual_path.read_bytes()
    if len(current) > MAX_EDITABLE_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="Artifact is too large to edit")
    if b"\x00" in current:
        raise HTTPException(status_code=415, detail="Binary artifacts cannot be edited")
    try:
        current.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Only UTF-8 text artifacts can be edited") from None

    current_sha256 = hashlib.sha256(current).hexdigest()
    if current_sha256 != expected_sha256:
        raise HTTPException(status_code=412, detail="Artifact changed since it was opened")
    return current, file_stat


def _encode_artifact_update(content: str) -> bytes:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_EDITABLE_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="Artifact is too large to edit")
    if b"\x00" in encoded:
        raise HTTPException(status_code=415, detail="Binary content cannot be saved as an artifact")
    return encoded


def _replace_artifact_atomically(actual_path: Path, content: bytes, file_stat: os.stat_result) -> None:
    temp_fd, temp_path_str = tempfile.mkstemp(prefix=_ARTIFACT_EDIT_TEMP_PREFIX, dir=actual_path.parent)
    temp_path = Path(temp_path_str)
    try:
        # Preserve ownership where possible and keep replacement permissions
        # scoped to the owner/group. The shared outputs directory allows a
        # mounted sandbox to reach the file without making it world-writable.
        if hasattr(os, "fchown"):
            try:
                os.fchown(temp_fd, file_stat.st_uid, file_stat.st_gid)
            except OSError:
                logger.debug("Could not preserve artifact ownership: %s", actual_path, exc_info=True)
        # Windows has no fchmod and uses ACLs rather than POSIX mode bits.
        # Keep the mkstemp permissions there; retain the existing POSIX
        # behavior on platforms that expose descriptor-based chmod.
        if hasattr(os, "fchmod"):
            os.fchmod(temp_fd, stat.S_IMODE(file_stat.st_mode) | 0o660)
        with os.fdopen(temp_fd, "wb") as handle:
            temp_fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, actual_path)
        # Invalidate the SHA-256 cache after a successful edit so the next
        # preview request computes the new digest. Edits are rare, so
        # clearing the whole 256-entry LRU costs nothing (see PR review).
        _sha256_of_file_cached.cache_clear()
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _sync_artifact_to_sandbox(sandbox, virtual_path: str, content: bytes) -> None:
    sandbox.update_file(virtual_path, content)


def _build_content_disposition(disposition_type: str, filename: str) -> str:
    """Build an RFC 5987 encoded Content-Disposition header value."""
    return f"{disposition_type}; filename*=UTF-8''{quote(filename)}"


def _build_attachment_headers(filename: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Content-Disposition": _build_content_disposition("attachment", filename)}
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _slice_byte_range(content: bytes, range_header: str | None) -> tuple[bytes, int, dict[str, str]]:
    """Apply one RFC 9110 byte range to an in-memory archive member."""
    size = len(content)
    headers = {"Accept-Ranges": "bytes"}
    if range_header is None:
        return content, 200, headers

    def unsatisfied() -> HTTPException:
        return HTTPException(
            status_code=416,
            detail="Requested range is not satisfiable",
            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"},
        )

    if not range_header.startswith("bytes=") or "," in range_header:
        raise unsatisfied()
    range_spec = range_header.removeprefix("bytes=")
    if "-" not in range_spec:
        raise unsatisfied()
    start_text, end_text = range_spec.split("-", 1)
    try:
        if start_text:
            start = int(start_text)
            end = size - 1 if not end_text else min(int(end_text), size - 1)
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise unsatisfied()
            start = max(size - suffix_length, 0)
            end = size - 1
    except ValueError as exc:
        raise unsatisfied() from exc

    if size == 0 or start < 0 or start >= size or end < start:
        raise unsatisfied()
    ranged_content = content[start : end + 1]
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(len(ranged_content)),
        }
    )
    return ranged_content, 206, headers


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """Check if file is text by examining content for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # Text files shouldn't contain null bytes
            return b"\x00" not in chunk
    except Exception:
        return False


def _read_skill_archive_member(zip_ref: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read a .skill archive member while enforcing an uncompressed size cap."""
    if info.file_size > MAX_SKILL_ARCHIVE_MEMBER_BYTES:
        raise HTTPException(status_code=413, detail="Skill archive member is too large to preview")

    chunks: list[bytes] = []
    total_read = 0
    with zip_ref.open(info, "r") as src:
        while chunk := src.read(_SKILL_ARCHIVE_READ_CHUNK_SIZE):
            total_read += len(chunk)
            if total_read > MAX_SKILL_ARCHIVE_MEMBER_BYTES:
                raise HTTPException(status_code=413, detail="Skill archive member is too large to preview")
            chunks.append(chunk)
    return b"".join(chunks)


def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
    """Extract a file from a .skill ZIP archive.

    Args:
        zip_path: Path to the .skill file (ZIP archive).
        internal_path: Path to the file inside the archive (e.g., "SKILL.md").

    Returns:
        The file content as bytes, or None if not found.
    """
    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # List all files in the archive
            infos_by_name = {info.filename: info for info in zip_ref.infolist()}

            # Try direct path first
            if internal_path in infos_by_name:
                return _read_skill_archive_member(zip_ref, infos_by_name[internal_path])

            # Try with any top-level directory prefix (e.g., "skill-name/SKILL.md")
            for name, info in infos_by_name.items():
                if name.endswith("/" + internal_path) or name == internal_path:
                    return _read_skill_archive_member(zip_ref, info)

            # Not found
            return None
    except (zipfile.BadZipFile, KeyError):
        return None


def _load_skill_archive_member(actual_skill_path: Path, skill_file_path: str, internal_path: str) -> tuple[bytes, str | None]:
    """Worker-thread body for the ``.skill`` branch of ``get_artifact``.

    The ``exists`` / ``is_file`` probes, the ZIP open+extract, and the MIME
    sniff (``mimetypes`` lazily stats the system MIME database on first use) are
    blocking filesystem IO and must stay off the event loop. Raised
    ``HTTPException``s propagate through ``asyncio.to_thread`` unchanged,
    preserving status codes.
    """
    if not actual_skill_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill file not found: {skill_file_path}")
    if not actual_skill_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {skill_file_path}")
    content = _extract_file_from_skill_archive(actual_skill_path, internal_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"File '{internal_path}' not found in skill archive")
    mime_type, _ = mimetypes.guess_type(internal_path)
    return content, mime_type


def _read_artifact_payload(actual_path: Path, path: str, download: bool) -> tuple[str, str | None]:
    """Worker-thread body for the regular branch of ``get_artifact``.

    Stat probes and MIME sniffing (``mimetypes`` lazily stats the system MIME
    database on first use) are blocking filesystem IO. Returns a
    ``(kind, mime_type)`` plan the handler turns into a streamed
    ``FileResponse``. Inline text and binary previews both use FileResponse so
    clients can request a bounded byte range instead of buffering a whole file.
    """
    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}")
    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")
    mime_type, _ = mimetypes.guess_type(actual_path)
    # Active content / explicit download is streamed by FileResponse — no read here.
    if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
        return ("file", mime_type)
    if mime_type and mime_type.startswith("text/"):
        return ("inline_file", mime_type)
    if is_text_file_by_content(actual_path):
        return ("inline_file", mime_type or "text/plain")
    return ("inline_file", mime_type)


def _sha256_of_file(path: Path) -> str:
    """Return the hex SHA-256 digest of *path* without loading it whole.

    Computing the digest on the Gateway lets the browser skip its own
    crypto.subtle-based hashing, which is unavailable in non-secure contexts
    (e.g. http://<lan-ip>:<port>) and otherwise breaks artifact preview +
    inline editing (see issue #4864).

    The digest is cached by (path, mtime_ns, size) so the many small ``Range``
    requests a browser issues while scrubbing/paginating a preview do not each
    re-hash a potentially huge artifact from scratch (raised in PR review).
    """
    stat = path.stat()
    return _sha256_of_file_cached(str(path), stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=256)
def _sha256_of_file_cached(path: str, mtime_ns: int, size: int) -> str:
    """Cached SHA-256 of *path*; the size/mtime args invalidate stale entries."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.get(
    "/threads/{thread_id}/artifacts/{path:path}",
    summary="Get Artifact File",
    description="Retrieve an artifact file generated by the AI agent. Text and binary files can be viewed inline, while active web content is always downloaded.",
)
@require_permission("threads", "read", owner_check=True)
async def get_artifact(thread_id: ThreadId, path: str, request: Request, download: bool = False) -> Response:
    """Get an artifact file by its path.

    The endpoint automatically detects file types and returns appropriate content types.
    Use the `download` query parameter to force file download for non-active content.

    Args:
        thread_id: The thread ID.
        path: The artifact path with virtual prefix (e.g., mnt/user-data/outputs/file.txt).
        request: FastAPI request object (automatically injected).

    Returns:
        The file content as a FileResponse with appropriate content type:
        - Active content (HTML/XHTML/SVG): Served as download attachment
        - Text files: Plain text with proper MIME type
        - Binary files: Inline display with download option

    Raises:
        HTTPException:
            - 400 if path is invalid or not a file
            - 403 if access denied (path traversal detected)
            - 404 if file not found

    Query Parameters:
        download (bool): If true, forces attachment download for file types that are
            otherwise returned inline or as plain text. Active HTML/XHTML/SVG content
            is always downloaded regardless of this flag.

    Example:
        - Get text file inline: `/api/threads/abc123/artifacts/mnt/user-data/outputs/notes.txt`
        - Download file: `/api/threads/abc123/artifacts/mnt/user-data/outputs/data.csv?download=true`
        - Active web content such as `.html`, `.xhtml`, and `.svg` artifacts is always downloaded
    """
    # Trusted internal callers may act on behalf of a thread's owner via the
    # owner-user-id header (honored only after the internal token validates).
    # The header carries the raw platform owner id, while runs store files
    # under the make_safe_user_id bucket (the same normalization the channel
    # file pipeline and the memory router apply), so resolution uses the
    # normalized id. Browser/API callers get None here and fall back to the
    # effective user.
    raw_owner_user_id = get_trusted_internal_owner_user_id(request)
    owner_user_id = make_safe_user_id(raw_owner_user_id) if raw_owner_user_id else None

    # Check if this is a request for a file inside a .skill archive (e.g., xxx.skill/SKILL.md)
    if ".skill/" in path:
        # Split the path at ".skill/" to get the ZIP file path and internal path
        skill_marker = ".skill/"
        marker_pos = path.find(skill_marker)
        skill_file_path = path[: marker_pos + len(".skill")]  # e.g., "mnt/user-data/outputs/my-skill.skill"
        internal_path = path[marker_pos + len(skill_marker) :]  # e.g., "SKILL.md"

        actual_skill_path = await asyncio.to_thread(resolve_thread_virtual_path, thread_id, skill_file_path, user_id=owner_user_id)

        # Offload the stat probes + ZIP open/extract + MIME sniff (blocking filesystem IO).
        content, mime_type = await asyncio.to_thread(_load_skill_archive_member, actual_skill_path, skill_file_path, internal_path)

        # Add cache headers to avoid repeated ZIP extraction (cache for 5 minutes)
        cache_headers = {"Cache-Control": "private, max-age=300"}
        download_name = Path(internal_path).name or actual_skill_path.stem
        if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=_build_attachment_headers(download_name, cache_headers))

        # Archive members are already bounded during extraction. Preserve byte
        # semantics here so the frontend can request only its preview budget,
        # including a final partial UTF-8 sequence.
        request_headers = request.headers if request is not None else {}
        range_header = None if request_headers.get("if-range") else request_headers.get("range")
        ranged_content, status_code, range_headers = _slice_byte_range(content, range_header)
        inline_headers = {
            **cache_headers,
            **range_headers,
            # Real SHA-256 so the browser can skip crypto.subtle (unavailable on
            # non-secure contexts) when previewing / editing artifacts (#4864).
            "ETag": f'"{hashlib.sha256(content).hexdigest()}"',
        }

        if mime_type and mime_type.startswith("text/"):
            return Response(content=ranged_content, status_code=status_code, media_type=mime_type, headers=inline_headers)

        # Default to plain text for unknown types that look like text
        try:
            content.decode("utf-8")
            return Response(content=ranged_content, status_code=status_code, media_type="text/plain", headers=inline_headers)
        except UnicodeDecodeError:
            return Response(
                content=ranged_content,
                status_code=status_code,
                media_type=mime_type or "application/octet-stream",
                headers=inline_headers,
            )

    actual_path = await asyncio.to_thread(resolve_thread_virtual_path, thread_id, path, user_id=owner_user_id)

    logger.info(f"Resolving artifact path: thread_id={thread_id}, requested_path={path}, actual_path={actual_path}")

    # Offload path stat + MIME sniff (blocking filesystem IO). Every regular
    # artifact response is streamed by FileResponse; the worker only reports
    # disposition and media type.
    kind, mime_type = await asyncio.to_thread(_read_artifact_payload, actual_path, path, download)

    if kind == "file":
        # Always force download for active content types to prevent script
        # execution in the application origin when users open generated artifacts.
        headers = {**_build_attachment_headers(actual_path.name)}
        file_size = await asyncio.to_thread(lambda: actual_path.stat().st_size)
        if file_size <= MAX_EDITABLE_ARTIFACT_BYTES:
            # Real SHA-256 so the browser can skip crypto.subtle (unavailable
            # on non-secure contexts) when previewing / editing artifacts (#4864).
            # Skipped for oversized artifacts to avoid a full-file read on every
            # GET / Range request (raised in review as a performance P1).
            content_sha256 = await asyncio.to_thread(_sha256_of_file, actual_path)
            headers["ETag"] = f'"{content_sha256}"'
        return FileResponse(
            path=actual_path,
            filename=actual_path.name,
            media_type=mime_type,
            headers=headers,
        )

    if kind == "inline_file":
        # FileResponse honors byte-Range requests for large text previews and
        # media seeking without buffering the full artifact in the Gateway.
        headers = {"Content-Disposition": _build_content_disposition("inline", actual_path.name)}
        file_size = await asyncio.to_thread(lambda: actual_path.stat().st_size)
        if file_size <= MAX_EDITABLE_ARTIFACT_BYTES:
            # Real SHA-256 so the browser can skip crypto.subtle (unavailable
            # on non-secure contexts) when previewing / editing artifacts (#4864).
            # Skipped for oversized artifacts to avoid a full-file read on every
            # GET / Range request (raised in review as a performance P1).
            content_sha256 = await asyncio.to_thread(_sha256_of_file, actual_path)
            headers["ETag"] = f'"{content_sha256}"'
        return FileResponse(
            path=actual_path,
            media_type=mime_type,
            headers=headers,
        )

    raise AssertionError(f"Unhandled artifact response kind: {kind!r}")


@router.put(
    "/threads/{thread_id}/artifacts/{path:path}",
    response_model=ArtifactUpdateResponse,
    summary="Update Artifact File",
    description="Replace an existing UTF-8 text artifact after verifying that its content has not changed.",
)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def update_artifact(
    thread_id: ThreadId,
    path: str,
    body: ArtifactUpdateRequest,
    request: Request,
) -> ArtifactUpdateResponse:
    """Update an existing text artifact while the thread has no active run."""
    virtual_path = _normalize_editable_artifact_path(path)
    raw_owner_user_id = get_trusted_internal_owner_user_id(request)
    effective_user_id = make_safe_user_id(raw_owner_user_id) if raw_owner_user_id else get_effective_user_id()

    sandbox_provider = None
    sandbox_id: str | None = None
    sandbox = None
    try:
        async with reserve_artifact_write(request, thread_id, user_id=effective_user_id):
            actual_path = await asyncio.to_thread(
                resolve_thread_virtual_path,
                thread_id,
                virtual_path,
                user_id=effective_user_id,
            )
            current, file_stat = await asyncio.to_thread(
                _load_editable_artifact,
                actual_path,
                virtual_path,
                body.expected_sha256,
            )
            updated = _encode_artifact_update(body.content)

            sandbox_provider = get_sandbox_provider()
            if not bool(getattr(sandbox_provider, "uses_thread_data_mounts", False)):
                sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=effective_user_id)
                sandbox = sandbox_provider.get(sandbox_id)
                if sandbox is None:
                    raise RuntimeError("Failed to acquire sandbox for artifact update")

            try:
                if sandbox is not None:
                    await asyncio.to_thread(_sync_artifact_to_sandbox, sandbox, virtual_path, updated)
                await asyncio.to_thread(_replace_artifact_atomically, actual_path, updated, file_stat)
                # Invalidate any cached digest for this path so a subsequent GET
                # serves the fresh SHA-256. The (path, mtime_ns, size) LRU key can
                # collide on a same-size, sub-nanosecond re-write (review nit).
                _sha256_of_file_cached.cache_clear()
            except Exception:
                if sandbox is not None:
                    try:
                        await asyncio.to_thread(_sync_artifact_to_sandbox, sandbox, virtual_path, current)
                    except Exception:
                        logger.exception("Failed to roll back remote artifact after artifact update failure: %s", virtual_path)
                raise
    except ConflictError:
        raise HTTPException(status_code=409, detail="Thread has a run in flight. Save after the run finishes.") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update artifact %s for thread %s", path, thread_id)
        raise HTTPException(status_code=500, detail="Failed to update artifact") from None
    finally:
        if sandbox_id is not None and sandbox_provider is not None:
            try:
                await asyncio.to_thread(sandbox_provider.release, sandbox_id)
            except Exception:
                logger.warning("Failed to release sandbox after artifact update: %s", sandbox_id, exc_info=True)

    content_sha256 = hashlib.sha256(updated).hexdigest()
    return ArtifactUpdateResponse(
        path=virtual_path,
        sha256=content_sha256,
        size=len(updated),
    )

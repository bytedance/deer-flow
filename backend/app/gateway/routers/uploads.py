"""Upload router for handling file uploads."""

import logging
import os
import stat
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission, try_acquire_sandbox_for_request
from app.gateway.deps import get_config
from app.gateway.upload_ingestion import ThreadUploadIngestionService, UnsafeFilenameError, UnsafeUploadDestinationError
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import SandboxProvider, get_sandbox_provider
from deerflow.uploads.manager import (
    UPLOAD_STAGING_PREFIX,
    UPLOAD_STAGING_SUFFIX,
    PathTraversalError,
    UnsafeUploadPathError,
    apply_upload_sandbox_permits,
    claim_unique_filename,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    normalize_filename,
    upload_artifact_url,
    upload_virtual_path,
    validate_path_traversal,
)
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
from deerflow.utils.file_io import run_file_io
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])

# Ingestion bridge surface (Phase-2 Slice C): the shared thread-upload
# ingestion service (``app.gateway.upload_ingestion``) resolves these
# collaborators through this module at call time, so the pre-extraction
# upload tests keep patching one namespace for both this endpoint and the
# project-shelf attach route. They are re-exported deliberately — do not
# prune them as "unused".
__all__ = [
    "CONVERTIBLE_EXTENSIONS",
    "UnsafeUploadPathError",
    "claim_unique_filename",
    "convert_file_to_markdown",
    "ensure_uploads_dir",
    "get_sandbox_provider",
    "normalize_filename",
    "router",
    "try_acquire_sandbox_for_request",
    "upload_artifact_url",
    "upload_virtual_path",
]

UPLOAD_CHUNK_SIZE = 8192
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_SIZE = 100 * 1024 * 1024


@dataclass(slots=True)
class _UploadTempFile:
    file_path: Path
    temp_path: Path
    handle: BinaryIO


class UploadedFileInfo(BaseModel):
    """Uploaded file metadata exposed by upload and list APIs."""

    filename: str
    size: int
    path: str
    virtual_path: str
    artifact_url: str
    extension: str | None = None
    modified: float | None = None
    original_filename: str | None = None
    markdown_file: str | None = None
    markdown_path: str | None = None
    markdown_virtual_path: str | None = None
    markdown_artifact_url: str | None = None


class UploadResponse(BaseModel):
    """Response model for file upload."""

    success: bool
    files: list[UploadedFileInfo]
    message: str
    skipped_files: list[str] = Field(default_factory=list)


class UploadListResponse(BaseModel):
    """Response model for uploaded file listing."""

    files: list[UploadedFileInfo]
    count: int


class UploadLimits(BaseModel):
    """Application-level upload limits exposed to clients."""

    max_files: int
    max_file_size: int
    max_total_size: int


def _make_file_sandbox_writable(file_path: os.PathLike[str] | str) -> None:
    """Ensure uploaded files remain writable when mounted into non-local sandboxes.

    In AIO sandbox mode, the gateway writes the authoritative host-side file
    first, then the sandbox runtime may rewrite the same mounted path. Granting
    world-writable access here prevents permission mismatches between the
    gateway user and the sandbox runtime user. Delegates to the shared
    apply_upload_sandbox_permits helper so the change stays bound to the
    validated upload inode (O_NOFOLLOW + fchmod).
    """
    apply_upload_sandbox_permits(file_path, stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IRGRP | stat.S_IROTH)


def _make_file_sandbox_readable(file_path: os.PathLike[str] | str) -> None:
    """Ensure uploaded files are readable by the sandbox process.

    For Docker sandboxes (AIO), the gateway writes files as root with 0o600
    permissions, then bind-mounts the host directory into the container. The
    sandbox process inside the container runs as a non-root user and cannot
    read those files without group/other read bits. This function adds
    ``S_IRGRP | S_IROTH`` so the sandbox can read the uploaded content, via the
    shared apply_upload_sandbox_permits helper (O_NOFOLLOW + fchmod).
    """
    apply_upload_sandbox_permits(file_path, stat.S_IRGRP | stat.S_IROTH)


def _uses_thread_data_mounts(sandbox_provider: SandboxProvider) -> bool:
    return bool(getattr(sandbox_provider, "uses_thread_data_mounts", False))


def _get_uploads_config_value(app_config: AppConfig, key: str, default: object) -> object:
    """Read a value from the uploads config, supporting dict and attribute access."""
    uploads_cfg = getattr(app_config, "uploads", None)
    if isinstance(uploads_cfg, dict):
        return uploads_cfg.get(key, default)
    return getattr(uploads_cfg, key, default)


def _get_upload_limit(app_config: AppConfig, key: str, default: int, *, legacy_key: str | None = None) -> int:
    try:
        value = _get_uploads_config_value(app_config, key, None)
        if value is None and legacy_key is not None:
            value = _get_uploads_config_value(app_config, legacy_key, None)
        if value is None:
            value = default
        limit = int(value)
        if limit <= 0:
            raise ValueError
        return limit
    except Exception:
        logger.warning("Invalid uploads.%s value; falling back to %d", key, default)
        return default


def _get_upload_limits(app_config: AppConfig) -> UploadLimits:
    return UploadLimits(
        max_files=_get_upload_limit(app_config, "max_files", DEFAULT_MAX_FILES, legacy_key="max_file_count"),
        max_file_size=_get_upload_limit(app_config, "max_file_size", DEFAULT_MAX_FILE_SIZE, legacy_key="max_single_file_size"),
        max_total_size=_get_upload_limit(app_config, "max_total_size", DEFAULT_MAX_TOTAL_SIZE),
    )


def _cleanup_uploaded_paths(paths: list[os.PathLike[str] | str]) -> None:
    for path in reversed(paths):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Failed to clean up upload path after rejected request: %s", path, exc_info=True)


def _pure_destination(uploads_dir: os.PathLike[str] | str, display_filename: str) -> Path:
    """Normalize + type/confinement-check a destination name.

    The ``lstat`` rejects only a NON-REGULAR destination (a planted symlink
    must never become a write target — and following one during the
    confinement check would misreport a traversal): a stable property, unlike
    the old ``nlink > 1`` check, which raced the atomic link commit (the
    winner's link→unlink pair briefly shows ``nlink == 2`` on the name) and
    misclassified ordinary collisions as unsafe. Existence itself is decided
    by the commit's atomic link, never here.
    """
    base = Path(uploads_dir)
    file_path = base / normalize_filename(display_filename)
    try:
        st = os.lstat(file_path)
    except FileNotFoundError:
        st = None
    if st is not None and not stat.S_ISREG(st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {display_filename}")
    validate_path_traversal(file_path, base)
    return file_path


def _prepare_upload_destination(uploads_dir: os.PathLike[str] | str, display_filename: str) -> _UploadTempFile:
    uploads_dir_path = Path(uploads_dir)
    file_path = _pure_destination(uploads_dir_path, display_filename)
    temp_fd, temp_path_str = tempfile.mkstemp(prefix=UPLOAD_STAGING_PREFIX, suffix=UPLOAD_STAGING_SUFFIX, dir=uploads_dir_path)
    temp_path = Path(temp_path_str)
    try:
        handle = os.fdopen(temp_fd, "wb")
    except Exception:
        try:
            os.close(temp_fd)
        except OSError:
            pass
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    return _UploadTempFile(file_path=file_path, temp_path=temp_path, handle=handle)


def _link_staged_no_overwrite(
    staged_path: Path,
    uploads_dir: os.PathLike[str] | str,
    display_filename: str,
    *,
    unlink_staged: bool = True,
) -> Path:
    """Worker: publish *staged_path* under *display_filename* atomically, never overwriting.

    The ``os.link`` itself is the whole no-overwrite guard: it fails with
    :class:`FileExistsError` when the name exists as ANYTHING — a regular
    file collision (the caller retries with the next suffix), a symlink, a
    hardlink — and a link never writes through an existing file. The
    destination is NOT lstat-validated beforehand: the winner's link→unlink
    pair briefly shows ``nlink == 2`` on the name, so a pre-link multi-link
    check misclassifies an ordinary collision as unsafe (observed as
    intermittent 500s on concurrent same-name uploads). Classification
    happens AFTER the atomic failure: an existing non-regular file (a planted
    symlink — symlinks are excluded from the seeded listing, so one could
    only come from outside) stays an unsafe destination; anything else is a
    plain collision to retry. Any other failure removes the staged file and
    propagates; success unlinks it. Staging and destination are co-located in
    the uploads dir, so the hard link is always same-filesystem.

    ``unlink_staged=False`` publishes the link but leaves the staged name in
    place, for a caller that still holds a descriptor on the staged inode and
    therefore must remove it itself. Windows refuses to remove a file that
    has an open handle, so the removal cannot happen here in that case; the
    caller owns the staged path from the moment this returns.
    """
    file_path = _pure_destination(uploads_dir, display_filename)
    try:
        os.link(staged_path, file_path)
    except FileExistsError:
        try:
            if not stat.S_ISREG(os.lstat(file_path).st_mode):
                raise UnsafeUploadPathError(f"Upload destination is not a regular file: {display_filename}") from None
        except FileNotFoundError:
            pass  # The winner vanished between link and lstat — plain retry.
        raise
    except Exception:
        try:
            os.unlink(staged_path)
        except FileNotFoundError:
            pass
        raise
    if unlink_staged:
        os.unlink(staged_path)
    return file_path


def _commit_upload_temp_no_overwrite(
    upload_temp: _UploadTempFile,
    uploads_dir: os.PathLike[str] | str,
    display_filename: str,
    *,
    unlink_staged: bool = True,
) -> Path:
    """Worker: close the staged handle and publish the ``.part`` atomically via ``os.link``.

    Same no-overwrite contract as :func:`_link_staged_no_overwrite`:
    :class:`FileExistsError` leaves the staged part in place for a
    next-suffix retry (the handle's second ``close`` is idempotent); any
    other failure removes it. ``unlink_staged=False`` hands the staged name
    back to the caller, which still holds a descriptor on its inode.
    """
    upload_temp.handle.close()
    return _link_staged_no_overwrite(upload_temp.temp_path, uploads_dir, display_filename, unlink_staged=unlink_staged)


def _remove_staged_file(staged_path: os.PathLike[str] | str) -> None:
    """Worker: remove a staged ``.part`` name whose inode is no longer held open.

    The deferred half of ``unlink_staged=False``. Removal is best-effort: the
    name is already unreachable through the uploads listing, and failing an
    otherwise-committed upload over leftover staging bytes would be worse than
    leaving them for the startup sweep.
    """
    try:
        os.unlink(staged_path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Failed to remove staged upload file: %s", staged_path, exc_info=True)


def _write_upload_chunk(upload_temp: _UploadTempFile, chunk: bytes) -> None:
    upload_temp.handle.write(chunk)


def _abort_upload_temp(upload_temp: _UploadTempFile) -> None:
    try:
        upload_temp.handle.close()
    finally:
        # Best-effort, not ``os.unlink``: an abandoned duplication worker can
        # still hold this inode open (Windows refuses to remove it then), and
        # raising here would replace the caller's cancellation or original
        # failure with a secondary permission error.
        _remove_staged_file(upload_temp.temp_path)


def _make_uploaded_paths_sandbox_readable(paths: list[os.PathLike[str] | str]) -> None:
    for file_path in paths:
        _make_file_sandbox_readable(file_path)


def _sync_upload_to_sandbox(sandbox, file_path: os.PathLike[str] | str, virtual_path: str) -> None:
    _make_file_sandbox_writable(file_path)
    sandbox.update_file(virtual_path, Path(file_path).read_bytes())


def _list_uploaded_files_for_thread(thread_id: str, user_id: str) -> dict:
    uploads_dir = get_uploads_dir(thread_id, user_id=user_id)
    result = list_files_in_dir(uploads_dir)
    enrich_file_listing(result, thread_id)

    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id, user_id=user_id)
    for f in result["files"]:
        f["path"] = str(sandbox_uploads / f["filename"])
    return result


def _delete_uploaded_file_for_thread(thread_id: str, filename: str, user_id: str) -> dict:
    uploads_dir = get_uploads_dir(thread_id, user_id=user_id)
    return delete_file_safe(uploads_dir, filename)


async def _stream_upload_file(file: UploadFile) -> AsyncIterator[bytes]:
    """Adapt an ``UploadFile`` to the ingestion service's chunk stream."""
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        yield chunk


def _auto_convert_documents_enabled(app_config: AppConfig) -> bool:
    """Return whether automatic host-side document conversion is enabled.

    The secure default is disabled unless an operator explicitly opts in via
    uploads.auto_convert_documents in config.yaml.
    """
    try:
        raw = _get_uploads_config_value(app_config, "auto_convert_documents", False)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    except Exception:
        return False


@router.post("", response_model=UploadResponse)
@require_permission("threads", "write", owner_check=True, require_existing=False)
async def upload_files(
    thread_id: ThreadId,
    request: Request,
    files: list[UploadFile] = File(...),
    config: AppConfig = Depends(get_config),
) -> UploadResponse:
    """Upload multiple files to a thread's uploads directory.

    Thin adapter over the shared thread-upload ingestion service
    (``app.gateway.upload_ingestion``, Phase-2 spec §7.3 item 3), which owns
    staging, filename claiming, size checks, conversion, permissions and
    sandbox sync. When the sandbox provider is not thread-mounted, uploaded
    files are also synced into the thread's sandbox. Under
    ``authorization.enabled``, a caller denied ``sandbox:execute`` skips that
    sync (the upload itself still succeeds — files stay in the uploads dir;
    a sandbox-denied agent cannot consume them anyway).
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    limits = _get_upload_limits(config)
    if len(files) > limits.max_files:
        raise HTTPException(status_code=413, detail=f"Too many files: maximum is {limits.max_files}")

    # Setup runs INSIDE the cleanup scope: open() can acquire the sandbox
    # request lease and then raise (e.g. the acquired lease yields no
    # sandbox), and the finally's aclose() is what releases that partially
    # acquired holder.
    service = ThreadUploadIngestionService(request=request, thread_id=thread_id, user_id=get_effective_user_id(), app_config=config)
    uploaded_files = []
    skipped_files = []
    try:
        try:
            await service.open()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        for file in files:
            if not file.filename:
                continue
            try:
                file_info = await service.ingest_chunks(_stream_upload_file(file), display_name=file.filename)
            except UnsafeFilenameError:
                logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
                continue
            except UnsafeUploadDestinationError as e:
                logger.warning("Skipping upload with unsafe destination %s: %s", file.filename, e)
                skipped_files.append(e.filename)
                continue
            except HTTPException as e:
                await service.cleanup_written()
                raise e
            except Exception as e:
                logger.error(f"Failed to upload {file.filename}: {e}")
                await service.cleanup_written()
                raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")
            uploaded_files.append(file_info)

        await service.finalize()

        message = f"Successfully uploaded {len(uploaded_files)} file(s)"
        if skipped_files:
            message += f"; skipped {len(skipped_files)} unsafe file(s)"

        return UploadResponse(
            success=not skipped_files,
            files=uploaded_files,
            message=message,
            skipped_files=skipped_files,
        )
    finally:
        await service.aclose()


@router.get("/limits", response_model=UploadLimits)
@require_permission("threads", "read", owner_check=True)
async def get_upload_limits(
    thread_id: ThreadId,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> UploadLimits:
    """Return upload limits used by the gateway for this thread."""
    return _get_upload_limits(config)


@router.get("/list", response_model=UploadListResponse)
@require_permission("threads", "read", owner_check=True)
async def list_uploaded_files(thread_id: ThreadId, request: Request) -> UploadListResponse:
    """List all files in a thread's uploads directory."""
    try:
        result = await run_file_io(_list_uploaded_files_for_thread, thread_id, get_effective_user_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return UploadListResponse(**result)


@router.delete("/{filename}")
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_uploaded_file(thread_id: ThreadId, filename: str, request: Request) -> dict:
    """Delete a file from a thread's uploads directory."""
    try:
        return await run_file_io(_delete_uploaded_file_for_thread, thread_id, filename, get_effective_user_id())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")

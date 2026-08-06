"""Upload router for handling file uploads."""

import asyncio
import logging
import os
import stat
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import SandboxProvider, get_sandbox_provider
from deerflow.uploads.async_helpers import run_upload_lease_io, wait_for_task_completion
from deerflow.uploads.conversion import convert_uploaded_file_to_markdown
from deerflow.uploads.layout import artifact_url_for_virtual_path, conversion_virtual_path
from deerflow.uploads.manager import (
    PathTraversalError,
    PublishedUpload,
    StagedUpload,
    abort_staged_upload,
    create_upload_staging_file,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    normalize_filename,
    publish_staged_upload_leased,
    rollback_published_upload,
    upload_artifact_url,
    upload_virtual_path,
)
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS
from deerflow.utils.file_io import run_file_io
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])

UPLOAD_CHUNK_SIZE = 8192
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_SIZE = 100 * 1024 * 1024


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
    gateway user and the sandbox runtime user.
    """
    file_stat = os.lstat(file_path)
    if stat.S_ISLNK(file_stat.st_mode):
        logger.warning("Skipping sandbox chmod for symlinked upload path: %s", file_path)
        return

    writable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IRGRP | stat.S_IROTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, writable_mode, **chmod_kwargs)


def _make_file_sandbox_readable(file_path: os.PathLike[str] | str) -> None:
    """Ensure uploaded files are readable by the sandbox process.

    For Docker sandboxes (AIO), the gateway writes files as root with 0o600
    permissions, then bind-mounts the host directory into the container. The
    sandbox process inside the container runs as a non-root user and cannot
    read those files without group/other read bits. This function adds
    ``S_IRGRP | S_IROTH`` so the sandbox can read the uploaded content.
    """
    file_stat = os.lstat(file_path)
    if stat.S_ISLNK(file_stat.st_mode):
        logger.warning("Skipping sandbox chmod for symlinked upload path: %s", file_path)
        return

    readable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IRGRP | stat.S_IROTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, readable_mode, **chmod_kwargs)


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


def _cleanup_published_uploads(
    publications: list[PublishedUpload],
    generated_paths: list[os.PathLike[str] | str],
) -> None:
    for path in reversed(generated_paths):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Failed to clean up generated upload path after rejected request: %s", path, exc_info=True)
    for publication in reversed(publications):
        try:
            rollback_published_upload(publication)
        except Exception:
            logger.warning("Failed to roll back published upload after rejected request: %s", publication.path, exc_info=True)


def _cleanup_attempted_sandbox_paths(sandbox, virtual_paths: list[str]) -> None:
    """Best-effort removal of every exact remote path attempted by this request."""
    if sandbox is None or not virtual_paths:
        return
    for virtual_path in reversed(virtual_paths):
        try:
            sandbox.remove_file(virtual_path)
        except Exception:
            logger.warning("Failed to remove synchronized sandbox upload path: %s", virtual_path, exc_info=True)


def _rollback_upload_request(
    sandbox,
    attempted_sandbox_paths: list[str],
    publications: list[PublishedUpload],
    generated_paths: list[os.PathLike[str] | str],
) -> None:
    try:
        _cleanup_attempted_sandbox_paths(sandbox, attempted_sandbox_paths)
    finally:
        _cleanup_published_uploads(publications, generated_paths)


def _release_publications(publications: list[PublishedUpload]) -> None:
    for publication in reversed(publications):
        try:
            publication.release()
        except Exception:
            logger.warning("Failed to release published upload lease: %s", publication.path, exc_info=True)


def _rollback_and_release_publication(publication: PublishedUpload) -> None:
    try:
        rollback_published_upload(publication)
    finally:
        publication.release()


async def _run_file_io_cancellation_safe(function, *args):
    task = asyncio.create_task(run_file_io(function, *args))
    cancelled = await wait_for_task_completion(task)
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _run_file_io_commit(function, *args):
    """Finish a commit operation and ignore cancellation that arrives during it."""
    task = asyncio.create_task(run_file_io(function, *args))
    await wait_for_task_completion(task)
    return task.result()


async def _run_upload_lease_io_cancellation_safe(function, *args, **kwargs):
    task = asyncio.create_task(run_upload_lease_io(function, *args, **kwargs))
    cancelled = await wait_for_task_completion(task)
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _publish_staged_upload_cancellation_safe(
    staged: StagedUpload,
    filename: str,
    reserved_coordination_keys: set[str] | None = None,
) -> PublishedUpload:
    publish_task = asyncio.create_task(
        run_upload_lease_io(
            publish_staged_upload_leased,
            staged,
            filename,
            reserved_coordination_keys=reserved_coordination_keys,
        )
    )
    try:
        return await asyncio.shield(publish_task)
    except asyncio.CancelledError:
        await wait_for_task_completion(publish_task)
        if not publish_task.cancelled() and publish_task.exception() is None:
            cleanup_task = asyncio.create_task(run_file_io(_rollback_and_release_publication, publish_task.result()))
            await wait_for_task_completion(cleanup_task)
            try:
                cleanup_task.result()
            except Exception:
                logger.warning("Failed to roll back a cancelled upload publication", exc_info=True)
        raise


async def _create_upload_staging_file_cancellation_safe(uploads_dir: Path) -> StagedUpload:
    """Create a staged upload without leaking it when the caller is cancelled."""
    create_task = asyncio.create_task(run_file_io(create_upload_staging_file, uploads_dir))
    try:
        return await asyncio.shield(create_task)
    except asyncio.CancelledError:
        await wait_for_task_completion(create_task)
        if not create_task.cancelled() and create_task.exception() is None:
            cleanup_task = asyncio.create_task(run_file_io(abort_staged_upload, create_task.result()))
            await wait_for_task_completion(cleanup_task)
            try:
                cleanup_task.result()
            except Exception:
                logger.warning("Failed to abort a cancelled upload staging file", exc_info=True)
        raise


def _make_uploaded_paths_sandbox_readable(paths: list[os.PathLike[str] | str]) -> None:
    for file_path in paths:
        _make_file_sandbox_readable(file_path)


def _sync_upload_to_sandbox(
    sandbox,
    file_path: os.PathLike[str] | str,
    virtual_path: str,
    attempted_sandbox_paths: list[str],
) -> None:
    _make_file_sandbox_writable(file_path)
    data = Path(file_path).read_bytes()
    attempted_sandbox_paths.append(virtual_path)
    sandbox.update_file(virtual_path, data)


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


async def _write_upload_file_with_limits(
    file: UploadFile,
    *,
    uploads_dir: os.PathLike[str] | str,
    display_filename: str,
    max_single_file_size: int,
    max_total_size: int,
    total_size: int,
    reserved_coordination_keys: set[str] | None = None,
) -> tuple[PublishedUpload, int, int]:
    file_size = 0
    upload_temp: StagedUpload | None = None
    try:
        upload_temp = await _create_upload_staging_file_cancellation_safe(Path(uploads_dir))
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            file_size += len(chunk)
            total_size += len(chunk)
            if file_size > max_single_file_size:
                raise HTTPException(status_code=413, detail=f"File too large: {display_filename}")
            if total_size > max_total_size:
                raise HTTPException(status_code=413, detail="Total upload size too large")
            await run_file_io(upload_temp.handle.write, chunk)

        publication = await _publish_staged_upload_cancellation_safe(
            upload_temp,
            display_filename,
            reserved_coordination_keys,
        )
        upload_temp = None
    except BaseException:
        if upload_temp is not None:
            await _run_file_io_cancellation_safe(abort_staged_upload, upload_temp)
        raise
    return publication, file_size, total_size


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
    """Upload multiple files to a thread's uploads directory."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    limits = _get_upload_limits(config)
    if len(files) > limits.max_files:
        raise HTTPException(status_code=413, detail=f"Too many files: maximum is {limits.max_files}")

    try:
        effective_user_id = get_effective_user_id()
        uploads_dir = await run_file_io(ensure_uploads_dir, thread_id, user_id=effective_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sandbox_uploads = uploads_dir
    uploaded_files = []
    publications: list[PublishedUpload] = []
    generated_paths: list[Path] = []
    sandbox_sync_targets = []
    attempted_sandbox_paths: list[str] = []
    skipped_files = []
    reserved_coordination_keys: set[str] = set()
    total_size = 0
    sandbox_provider = await asyncio.to_thread(get_sandbox_provider)
    sync_to_sandbox = not _uses_thread_data_mounts(sandbox_provider)
    sandbox = None
    if sync_to_sandbox:
        sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=effective_user_id)
        sandbox = sandbox_provider.get(sandbox_id)
        if sandbox is None:
            raise HTTPException(status_code=500, detail="Failed to acquire sandbox")
    auto_convert_documents = _auto_convert_documents_enabled(config)
    current_filename = "request"

    try:
        for file in files:
            if not file.filename:
                continue
            current_filename = file.filename

            try:
                original_filename = normalize_filename(file.filename)
            except ValueError:
                logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
                continue

            publication, file_size, total_size = await _write_upload_file_with_limits(
                file,
                uploads_dir=uploads_dir,
                display_filename=original_filename,
                max_single_file_size=limits.max_file_size,
                max_total_size=limits.max_total_size,
                total_size=total_size,
                reserved_coordination_keys=reserved_coordination_keys,
            )
            publications.append(publication)
            file_path = publication.path
            safe_filename = file_path.name
            virtual_path = upload_virtual_path(safe_filename)

            if sync_to_sandbox:
                sandbox_sync_targets.append((file_path, virtual_path))

            file_info = {
                "filename": safe_filename,
                "size": file_size,
                "path": str(sandbox_uploads / safe_filename),
                "virtual_path": virtual_path,
                "artifact_url": upload_artifact_url(thread_id, safe_filename),
            }
            if safe_filename != original_filename:
                file_info["original_filename"] = original_filename

            logger.info(f"Saved file: {safe_filename} ({file_size} bytes) to {file_info['path']}")

            file_ext = file_path.suffix.lower()
            if auto_convert_documents and file_ext in CONVERTIBLE_EXTENSIONS:
                try:
                    md_path = await convert_uploaded_file_to_markdown(file_path, publication=publication)
                except Exception:
                    logger.warning("Failed to convert uploaded file: %s", file_path, exc_info=True)
                    md_path = None
                if md_path:
                    generated_paths.append(md_path)
                    md_virtual_path = conversion_virtual_path(safe_filename)

                    if sync_to_sandbox:
                        sandbox_sync_targets.append((md_path, md_virtual_path))

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = str(md_path)
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = artifact_url_for_virtual_path(thread_id, md_virtual_path)

            uploaded_files.append(file_info)

        # Uploaded files are created with 0o600 permissions (owner read/write only).
        # Always add group/other read bits before mounted or explicit sandbox use.
        postprocess_paths = [publication.path for publication in publications] + generated_paths
        await _run_file_io_cancellation_safe(_make_uploaded_paths_sandbox_readable, postprocess_paths)

        if sync_to_sandbox:
            for file_path, virtual_path in sandbox_sync_targets:
                await _run_file_io_cancellation_safe(
                    _sync_upload_to_sandbox,
                    sandbox,
                    file_path,
                    virtual_path,
                    attempted_sandbox_paths,
                )

        message = f"Successfully uploaded {len(uploaded_files)} file(s)"
        if skipped_files:
            message += f"; skipped {len(skipped_files)} unsafe file(s)"

        return UploadResponse(
            success=not skipped_files,
            files=uploaded_files,
            message=message,
            skipped_files=skipped_files,
        )
    except HTTPException:
        await _run_file_io_cancellation_safe(
            _rollback_upload_request,
            sandbox,
            attempted_sandbox_paths,
            publications,
            generated_paths,
        )
        raise
    except Exception as exc:
        logger.error("Failed to upload %s: %s", current_filename, exc)
        await _run_file_io_cancellation_safe(
            _rollback_upload_request,
            sandbox,
            attempted_sandbox_paths,
            publications,
            generated_paths,
        )
        raise HTTPException(status_code=500, detail=f"Failed to upload {current_filename}: {str(exc)}") from exc
    except BaseException:
        await _run_file_io_cancellation_safe(
            _rollback_upload_request,
            sandbox,
            attempted_sandbox_paths,
            publications,
            generated_paths,
        )
        raise
    finally:
        await _run_file_io_commit(_release_publications, publications)


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
        return await _run_upload_lease_io_cancellation_safe(
            _delete_uploaded_file_for_thread,
            thread_id,
            filename,
            get_effective_user_id(),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")

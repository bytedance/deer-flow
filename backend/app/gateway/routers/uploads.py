"""Upload router for handling file uploads."""

import logging
import os
import stat

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import SandboxProvider, get_sandbox_provider
from deerflow.uploads.manager import (
    PathTraversalError,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    normalize_filename,
    upload_artifact_url,
    upload_virtual_path,
)
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])

UPLOAD_CHUNK_SIZE = 8192
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_SIZE = 100 * 1024 * 1024


class UploadResponse(BaseModel):
    """Response model for file upload."""

    success: bool
    files: list[dict[str, str]]
    message: str


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

    writable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, writable_mode, **chmod_kwargs)


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


async def _write_upload_file_streaming(
    file: UploadFile,
    file_path: os.PathLike[str] | str,
    *,
    display_filename: str,
    max_single_file_size: int,
    max_total_size: int,
    total_size: int,
) -> tuple[int, int]:
    file_size = 0
    with open(file_path, "wb") as output:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            file_size += len(chunk)
            total_size += len(chunk)
            if file_size > max_single_file_size:
                raise HTTPException(status_code=413, detail=f"File too large: {display_filename}")
            if total_size > max_total_size:
                raise HTTPException(status_code=413, detail="Total upload size too large")
            output.write(chunk)
    return file_size, total_size


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
    thread_id: str,
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
        uploads_dir = ensure_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id, user_id=get_effective_user_id())
    uploaded_files = []
    written_paths = []
    sandbox_sync_targets = []
    total_size = 0

    sandbox_provider = get_sandbox_provider()
    sync_to_sandbox = not _uses_thread_data_mounts(sandbox_provider)
    sandbox = None
    if sync_to_sandbox:
        sandbox_id = sandbox_provider.acquire(thread_id)
        sandbox = sandbox_provider.get(sandbox_id)
        if sandbox is None:
            raise HTTPException(status_code=500, detail="Failed to acquire sandbox")
    auto_convert_documents = _auto_convert_documents_enabled(config)

    for file in files:
        if not file.filename:
            continue

        try:
            safe_filename = normalize_filename(file.filename)
        except ValueError:
            logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
            continue

        try:
            file_path = uploads_dir / safe_filename
            written_paths.append(file_path)
            file_size, total_size = await _write_upload_file_streaming(
                file,
                file_path,
                display_filename=safe_filename,
                max_single_file_size=limits.max_file_size,
                max_total_size=limits.max_total_size,
                total_size=total_size,
            )

            virtual_path = upload_virtual_path(safe_filename)

            if sync_to_sandbox:
                sandbox_sync_targets.append((file_path, virtual_path))

            file_info = {
                "filename": safe_filename,
                "size": str(file_size),
                "path": str(sandbox_uploads / safe_filename),
                "virtual_path": virtual_path,
                "artifact_url": upload_artifact_url(thread_id, safe_filename),
            }

            logger.info(f"Saved file: {safe_filename} ({file_size} bytes) to {file_info['path']}")

            file_ext = file_path.suffix.lower()
            if auto_convert_documents and file_ext in CONVERTIBLE_EXTENSIONS:
                md_path = await convert_file_to_markdown(file_path)
                if md_path:
                    written_paths.append(md_path)
                    md_virtual_path = upload_virtual_path(md_path.name)

                    if sync_to_sandbox:
                        sandbox_sync_targets.append((md_path, md_virtual_path))

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = str(sandbox_uploads / md_path.name)
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

            uploaded_files.append(file_info)

        except HTTPException as e:
            _cleanup_uploaded_paths(written_paths)
            raise e
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            _cleanup_uploaded_paths(written_paths)
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    if sync_to_sandbox:
        for file_path, virtual_path in sandbox_sync_targets:
            _make_file_sandbox_writable(file_path)
            sandbox.update_file(virtual_path, file_path.read_bytes())

    return UploadResponse(
        success=True,
        files=uploaded_files,
        message=f"Successfully uploaded {len(uploaded_files)} file(s)",
    )


@router.get("/limits", response_model=UploadLimits)
@require_permission("threads", "read", owner_check=True)
async def get_upload_limits(
    thread_id: str,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> UploadLimits:
    """Return upload limits used by the gateway for this thread."""
    return _get_upload_limits(config)


@router.get("/list", response_model=dict)
@require_permission("threads", "read", owner_check=True)
async def list_uploaded_files(thread_id: str, request: Request) -> dict:
    """List all files in a thread's uploads directory."""
    try:
        uploads_dir = get_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = list_files_in_dir(uploads_dir)
    enrich_file_listing(result, thread_id)

    # Gateway additionally includes the sandbox-relative path.
    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id, user_id=get_effective_user_id())
    for f in result["files"]:
        f["path"] = str(sandbox_uploads / f["filename"])

    return result


@router.delete("/{filename}")
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_uploaded_file(thread_id: str, filename: str, request: Request) -> dict:
    """Delete a file from a thread's uploads directory."""
    try:
        uploads_dir = get_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return delete_file_safe(uploads_dir, filename, convertible_extensions=CONVERTIBLE_EXTENSIONS)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")

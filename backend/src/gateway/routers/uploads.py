"""Upload router for handling file uploads with security validation."""

import logging
import os
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.gateway.auth.middleware import get_current_user
from src.gateway.auth.ownership import verify_thread_ownership
from src.gateway.rate_limiter import check_user_api_rate
from src.sandbox.sandbox_provider import get_sandbox_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])

# File extensions that should be converted to markdown
CONVERTIBLE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}

# ---------------------------------------------------------------------------
# Upload validation constants
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".bmp",
    # Code
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".html",
    ".css",
    ".sh",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".go",
    ".rs",
    ".rb",
    ".php",
    # Data
    ".sql",
    ".log",
    ".ini",
    ".cfg",
    ".toml",
    ".env",
    # Archives (for skill installation)
    ".zip",
}

ALLOWED_MIME_TYPES = {
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Text
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/xml",
    "text/x-python",
    "text/javascript",
    "text/x-sh",
    # Structured data
    "application/json",
    "application/xml",
    "application/x-yaml",
    # Images
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/svg+xml",
    "image/webp",
    "image/bmp",
    # Archives
    "application/zip",
    "application/x-zip-compressed",
    # Fallback for unknown but extension-validated files
    "application/octet-stream",
}

# Maximum size per individual file (50 MB)
MAX_SINGLE_FILE_SIZE = 50 * 1024 * 1024

# Per-user upload quota (configurable via UPLOAD_QUOTA_MB env var, default 500 MB)
UPLOAD_QUOTA_BYTES = int(os.environ.get("UPLOAD_QUOTA_MB", "500")) * 1024 * 1024


class UploadResponse(BaseModel):
    """Response model for file upload."""

    success: bool
    files: list[dict[str, str]]
    message: str


def get_uploads_dir(thread_id: str) -> Path:
    """Get the uploads directory for a thread."""
    base_dir = get_paths().sandbox_uploads_dir(thread_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _validate_upload(filename: str, content_type: str | None, content_size: int) -> None:
    """Validate a file upload against security rules.

    Args:
        filename: The original filename.
        content_type: The MIME type from the upload.
        content_size: The size of the file content in bytes.

    Raises:
        HTTPException: If validation fails.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not allowed. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"MIME type '{content_type}' is not allowed for upload.",
        )

    if content_size > MAX_SINGLE_FILE_SIZE:
        max_mb = MAX_SINGLE_FILE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File '{filename}' exceeds maximum size of {max_mb} MB.",
        )


def _get_user_total_upload_bytes(user_id: str) -> int:
    """Get total upload bytes for a user across all threads.

    Uses database query when available, falls back to filesystem scan.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        from sqlalchemy import func

        from src.db.engine import get_db_session
        from src.db.models import UploadModel

        with get_db_session() as session:
            total = session.query(func.coalesce(func.sum(UploadModel.size_bytes), 0)).filter(UploadModel.user_id == user_id).scalar()
            return int(total)

    # File-based fallback: walk all thread upload directories
    threads_dir = get_paths().base_dir / "threads"
    total = 0
    if threads_dir.exists():
        for upload_dir in threads_dir.glob("*/user-data/uploads"):
            for f in upload_dir.iterdir():
                if f.is_file():
                    total += f.stat().st_size
    return total


def _check_upload_quota(user_id: str, new_bytes: int) -> None:
    """Check if uploading new_bytes would exceed the user's quota.

    Raises:
        HTTPException: 413 if quota would be exceeded.
    """
    current = _get_user_total_upload_bytes(user_id)
    if current + new_bytes > UPLOAD_QUOTA_BYTES:
        used_mb = current / (1024 * 1024)
        quota_mb = UPLOAD_QUOTA_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Upload quota exceeded. Used: {used_mb:.1f} MB / {quota_mb:.0f} MB limit.",
        )


def _record_upload(user_id: str, thread_id: str, filename: str, content_type: str | None, size_bytes: int, storage_path: str) -> None:
    """Record upload metadata in the database (if enabled)."""
    from src.db.engine import is_db_enabled

    if not is_db_enabled():
        return

    from src.db.engine import get_db_session
    from src.db.models import UploadModel

    with get_db_session() as session:
        upload = UploadModel(
            id=uuid.uuid4().hex[:32],
            thread_id=thread_id,
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
        )
        session.add(upload)


async def convert_file_to_markdown(file_path: Path) -> Path | None:
    """Convert a file to markdown using markitdown."""
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(file_path))

        md_path = file_path.with_suffix(".md")
        md_path.write_text(result.text_content, encoding="utf-8")

        logger.info(f"Converted {file_path.name} to markdown: {md_path.name}")
        return md_path
    except Exception as e:
        logger.error(f"Failed to convert {file_path.name} to markdown: {e}")
        return None


@router.post("", response_model=UploadResponse)
async def upload_files(
    thread_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """Upload multiple files to a thread's uploads directory.

    Validates file type, MIME type, size, and per-user quota before saving.
    For PDF, PPT, Excel, and Word files, they will be converted to markdown.
    """
    check_user_api_rate(current_user["id"])
    verify_thread_ownership(thread_id, current_user["id"])

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Read all file contents and validate before writing anything
    file_contents: list[tuple[UploadFile, bytes, str]] = []
    total_new_bytes = 0

    for file in files:
        if not file.filename:
            continue

        # Normalize filename to prevent path traversal
        safe_filename = Path(file.filename).name
        if not safe_filename or safe_filename in {".", ".."} or "/" in safe_filename or "\\" in safe_filename:
            logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
            continue

        content = await file.read()
        _validate_upload(safe_filename, file.content_type, len(content))
        file_contents.append((file, content, safe_filename))
        total_new_bytes += len(content)

    if not file_contents:
        # If all files were filtered by safety checks, return success with empty list
        # (rather than erroring) so callers know no files were dangerously processed.
        return UploadResponse(success=True, files=[], message="No valid files to upload")

    # Check quota before writing
    _check_upload_quota(current_user["id"], total_new_bytes)

    uploads_dir = get_uploads_dir(thread_id)
    paths = get_paths()
    uploaded_files = []

    sandbox_provider = get_sandbox_provider()
    sandbox_id = sandbox_provider.acquire(thread_id)
    sandbox = sandbox_provider.get(sandbox_id)

    for file, content, safe_filename in file_contents:
        try:
            # Write to thread-scoped host storage first (canonical copy)
            file_path = uploads_dir / safe_filename
            file_path.write_bytes(content)

            relative_path = str(paths.sandbox_uploads_dir(thread_id) / safe_filename)
            virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"

            # For non-local sandboxes, also sync to virtual path for runtime visibility
            if sandbox_id != "local":
                sandbox.update_file(virtual_path, content)

            file_info = {
                "filename": safe_filename,
                "size": str(len(content)),
                "path": relative_path,
                "virtual_path": virtual_path,
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{safe_filename}",
            }

            logger.info(f"Saved file: {safe_filename} ({len(content)} bytes) to {relative_path}")

            # Record upload in database
            _record_upload(
                user_id=current_user["id"],
                thread_id=thread_id,
                filename=safe_filename,
                content_type=file.content_type,
                size_bytes=len(content),
                storage_path=relative_path,
            )

            # Check if file should be converted to markdown
            file_ext = file_path.suffix.lower()
            if file_ext in CONVERTIBLE_EXTENSIONS:
                md_path = await convert_file_to_markdown(file_path)
                if md_path:
                    md_relative_path = str(paths.sandbox_uploads_dir(thread_id) / md_path.name)
                    md_virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{md_path.name}"

                    if sandbox_id != "local":
                        sandbox.update_file(md_virtual_path, md_path.read_bytes())

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = md_relative_path
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{md_path.name}"

            uploaded_files.append(file_info)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to upload {safe_filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to upload {safe_filename}: {str(e)}")

    return UploadResponse(
        success=True,
        files=uploaded_files,
        message=f"Successfully uploaded {len(uploaded_files)} file(s)",
    )


@router.get("/list", response_model=dict)
async def list_uploaded_files(
    thread_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict:
    """List all files in a thread's uploads directory."""
    verify_thread_ownership(thread_id, current_user["id"])

    uploads_dir = get_uploads_dir(thread_id)

    if not uploads_dir.exists():
        return {"files": [], "count": 0}

    files = []
    for file_path in sorted(uploads_dir.iterdir()):
        if file_path.is_file():
            stat = file_path.stat()
            relative_path = f".think-tank/threads/{thread_id}/user-data/uploads/{file_path.name}"
            files.append(
                {
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "path": relative_path,
                    "virtual_path": f"/mnt/user-data/uploads/{file_path.name}",
                    "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{file_path.name}",
                    "extension": file_path.suffix,
                    "modified": stat.st_mtime,
                }
            )

    return {"files": files, "count": len(files)}


@router.delete("/{filename}")
async def delete_uploaded_file(
    thread_id: str,
    filename: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict:
    """Delete a file from a thread's uploads directory."""
    verify_thread_ownership(thread_id, current_user["id"])

    uploads_dir = get_uploads_dir(thread_id)
    file_path = uploads_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # Security check: ensure the path is within the uploads directory
    try:
        file_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        file_path.unlink()
        logger.info(f"Deleted file: {filename}")
        return {"success": True, "message": f"Deleted {filename}"}
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")

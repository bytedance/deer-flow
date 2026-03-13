"""Upload router for handling file uploads."""

import logging
import mimetypes
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.sandbox.sandbox_provider import get_sandbox_provider
from src.storage import get_storage

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


class UploadResponse(BaseModel):
    """Response model for file upload."""

    success: bool
    files: list[dict[str, str]]
    message: str


class PresignResponse(BaseModel):
    """Response model for presigned upload URL."""

    url: str
    key: str
    virtual_path: str
    artifact_url: str
    markdown_file: Optional[str] = None
    markdown_key: Optional[str] = None
    markdown_virtual_path: Optional[str] = None
    markdown_artifact_url: Optional[str] = None


class PresignBatchResponse(BaseModel):
    """Response for batch presigned URL generation."""

    files: list[PresignResponse]


def get_uploads_dir(thread_id: str) -> Path:
    """Get the uploads directory for a thread (local filesystem).

    Used for temporary file processing (e.g., markdown conversion).

    Args:
        thread_id: The thread ID.

    Returns:
        Path to the uploads directory.
    """
    base_dir = get_paths().sandbox_uploads_dir(thread_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _convert_file_to_markdown_sync(file_path: Path) -> Path | None:
    """Convert a file to markdown using markitdown.

    Args:
        file_path: Path to the file to convert.

    Returns:
        Path to the markdown file if conversion was successful, None otherwise.
    """
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(file_path))

        # Save as .md file with same name
        md_path = file_path.with_suffix(".md")
        md_path.write_text(result.text_content, encoding="utf-8")

        logger.info(f"Converted {file_path.name} to markdown: {md_path.name}")
        return md_path
    except Exception as e:
        logger.error(f"Failed to convert {file_path.name} to markdown: {e}")
        return None


def _background_sync(thread_id: str, safe_filename: str, content: bytes, file_path: Path, file_ext: str) -> None:
    """Background task: upload to R2, convert to markdown, sync to sandbox.

    This runs in a separate thread so the upload endpoint can return immediately
    after saving to local disk.
    """
    try:
        storage = get_storage()

        # 1. Upload original file to persistent storage (R2)
        storage_key = storage.upload_key(thread_id, safe_filename)
        storage.write(storage_key, content)
        logger.info(f"Background: synced {safe_filename} ({len(content)} bytes) to storage: {storage_key}")

        # 2. Convert to markdown if applicable
        if file_ext in CONVERTIBLE_EXTENSIONS:
            md_path = _convert_file_to_markdown_sync(file_path)
            if md_path:
                md_filename = md_path.name
                md_content = md_path.read_bytes()
                md_storage_key = storage.upload_key(thread_id, md_filename)
                storage.write(md_storage_key, md_content)
                logger.info(f"Background: synced markdown {md_filename} to storage: {md_storage_key}")

        # 3. Sync to sandbox if one already exists
        sandbox_provider = get_sandbox_provider()
        sandbox_id = sandbox_provider.get_existing(thread_id)
        if sandbox_id and sandbox_id != "local":
            sandbox = sandbox_provider.get(sandbox_id)
            if sandbox:
                virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"
                sandbox.update_file(virtual_path, content)
                md_local = file_path.with_suffix(".md")
                if file_ext in CONVERTIBLE_EXTENSIONS and md_local.exists():
                    md_virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{md_local.name}"
                    sandbox.update_file(md_virtual_path, md_local.read_bytes())

    except Exception as e:
        logger.error(f"Background sync failed for {safe_filename}: {e}")


@router.post("/presign", response_model=PresignBatchResponse)
async def presign_upload(
    thread_id: str,
    filenames: list[str] = Query(..., description="List of filenames to generate presigned URLs for"),
) -> PresignBatchResponse:
    """Generate presigned PUT URLs for direct browser-to-R2 uploads.

    The browser uses these URLs to upload files directly to R2, bypassing the
    gateway server entirely. This eliminates the gateway as a file proxy and
    makes uploads as fast as the client's connection to Cloudflare.

    Args:
        thread_id: The thread ID.
        filenames: List of filenames to generate URLs for.

    Returns:
        Presigned URLs and metadata for each file.
    """
    storage = get_storage()

    # Check if storage supports presigned URLs
    if not hasattr(storage, "generate_presigned_put"):
        raise HTTPException(
            status_code=501,
            detail="Storage backend does not support presigned URLs. Use POST upload instead.",
        )

    results = []
    for filename in filenames:
        # Normalize filename to prevent path traversal
        safe_filename = Path(filename).name
        if not safe_filename or safe_filename in {".", ".."} or "/" in safe_filename or "\\" in safe_filename:
            continue

        storage_key = storage.upload_key(thread_id, safe_filename)
        content_type = mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"

        url = storage.generate_presigned_put(storage_key, content_type=content_type)
        virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"

        result = PresignResponse(
            url=url,
            key=storage_key,
            virtual_path=virtual_path,
            artifact_url=f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{safe_filename}",
        )

        # Add expected markdown paths for convertible files
        file_ext = Path(safe_filename).suffix.lower()
        if file_ext in CONVERTIBLE_EXTENSIONS:
            md_filename = Path(safe_filename).with_suffix(".md").name
            result.markdown_file = md_filename
            result.markdown_key = storage.upload_key(thread_id, md_filename)
            result.markdown_virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{md_filename}"
            result.markdown_artifact_url = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{md_filename}"

        results.append(result)

    return PresignBatchResponse(files=results)


@router.post("/confirm")
async def confirm_upload(
    thread_id: str,
    filenames: list[str] = Query(..., description="Filenames that were uploaded directly to R2"),
) -> dict:
    """Confirm that files were uploaded directly to R2.

    Called by the frontend after a presigned upload completes, so the backend
    can run markdown conversion and sandbox sync in the background.

    Args:
        thread_id: The thread ID.
        filenames: Filenames that were uploaded.

    Returns:
        Confirmation response.
    """
    storage = get_storage()
    uploads_dir = get_uploads_dir(thread_id)

    for filename in filenames:
        safe_filename = Path(filename).name
        if not safe_filename or safe_filename in {".", ".."}:
            continue

        file_ext = Path(safe_filename).suffix.lower()
        if file_ext not in CONVERTIBLE_EXTENSIONS:
            continue

        # Download from R2 to local disk for markdown conversion
        def _bg_convert(tid: str, fn: str, ext: str) -> None:
            try:
                key = storage.upload_key(tid, fn)
                content = storage.read(key)
                local_path = uploads_dir / fn
                local_path.write_bytes(content)

                md_path = _convert_file_to_markdown_sync(local_path)
                if md_path:
                    md_content = md_path.read_bytes()
                    md_key = storage.upload_key(tid, md_path.name)
                    storage.write(md_key, md_content)
                    logger.info(f"Background: converted and synced {md_path.name}")
            except Exception as e:
                logger.error(f"Background conversion failed for {fn}: {e}")

        t = threading.Thread(target=_bg_convert, args=(thread_id, safe_filename, file_ext), daemon=True)
        t.start()

    return {"success": True, "message": f"Confirmed {len(filenames)} file(s)"}


@router.post("", response_model=UploadResponse)
def upload_files(
    thread_id: str,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """Upload files via multipart form (fallback when presigned URLs unavailable).

    Saves files to local disk immediately and returns fast. R2 upload,
    markdown conversion, and sandbox sync happen in background threads.

    Args:
        thread_id: The thread ID to upload files to.
        files: List of files to upload.

    Returns:
        Upload response with success status and file information.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    uploads_dir = get_uploads_dir(thread_id)
    uploaded_files = []

    for file in files:
        if not file.filename:
            continue

        try:
            # Normalize filename to prevent path traversal
            safe_filename = Path(file.filename).name
            if not safe_filename or safe_filename in {".", ".."} or "/" in safe_filename or "\\" in safe_filename:
                logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
                continue

            content = file.file.read()

            # Save to local disk immediately (fast, <1ms)
            file_path = uploads_dir / safe_filename
            file_path.write_bytes(content)

            storage = get_storage()
            storage_key = storage.upload_key(thread_id, safe_filename)
            virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"

            file_info: dict[str, str] = {
                "filename": safe_filename,
                "size": str(len(content)),
                "path": storage_key,
                "virtual_path": virtual_path,
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{safe_filename}",
            }

            # For convertible files, add expected markdown paths
            file_ext = file_path.suffix.lower()
            if file_ext in CONVERTIBLE_EXTENSIONS:
                md_filename = file_path.with_suffix(".md").name
                file_info["markdown_file"] = md_filename
                file_info["markdown_path"] = storage.upload_key(thread_id, md_filename)
                file_info["markdown_virtual_path"] = f"{VIRTUAL_PATH_PREFIX}/uploads/{md_filename}"
                file_info["markdown_artifact_url"] = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{md_filename}"

            uploaded_files.append(file_info)

            logger.info(f"Saved file: {safe_filename} ({len(content)} bytes) to local disk")

            # R2 upload + markdown conversion + sandbox sync in background
            t = threading.Thread(
                target=_background_sync,
                args=(thread_id, safe_filename, content, file_path, file_ext),
                daemon=True,
            )
            t.start()

        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    return UploadResponse(
        success=True,
        files=uploaded_files,
        message=f"Successfully uploaded {len(uploaded_files)} file(s)",
    )


@router.get("/list", response_model=dict)
async def list_uploaded_files(thread_id: str) -> dict:
    """List all files in a thread's uploads.

    Args:
        thread_id: The thread ID to list files for.

    Returns:
        Dictionary containing list of files with their metadata.
    """
    storage = get_storage()
    prefix = storage.uploads_prefix(thread_id)
    file_infos = storage.list_files(prefix)

    files = []
    for info in file_infos:
        files.append(
            {
                "filename": info.filename,
                "size": info.size,
                "path": info.path,
                "virtual_path": f"{VIRTUAL_PATH_PREFIX}/uploads/{info.filename}",
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{info.filename}",
                "extension": info.extension,
                "modified": info.modified,
            }
        )

    return {"files": files, "count": len(files)}


@router.delete("/{filename}")
async def delete_uploaded_file(thread_id: str, filename: str) -> dict:
    """Delete a file from a thread's uploads.

    Args:
        thread_id: The thread ID.
        filename: The filename to delete.

    Returns:
        Success message.
    """
    # Prevent path traversal
    safe_filename = Path(filename).name
    if safe_filename != filename or not safe_filename or safe_filename in {".", ".."}:
        raise HTTPException(status_code=403, detail="Access denied")

    storage = get_storage()
    key = storage.upload_key(thread_id, safe_filename)

    try:
        storage.delete(key)
        logger.info(f"Deleted file: {filename}")
        return {"success": True, "message": f"Deleted {filename}"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")

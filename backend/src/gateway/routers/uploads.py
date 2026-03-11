"""Upload router for handling file uploads."""

import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.sandbox.sandbox_provider import get_sandbox_provider
from src.storage import build_upload_metadata, evict_local_upload_cache, get_thread_file_backend, materialize_upload_to_local_cache

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


class TrustedAttachmentDescriptor(BaseModel):
    """Trusted downstream attachment descriptor for finalize-by-reference."""

    thread_id: str = Field(description="Thread binding context from downstream")
    filename: str
    size: int = Field(ge=0)
    content_type: str = Field(min_length=1)
    object_key: str = Field(min_length=1, description="Durable object key in shared storage")
    trusted_url: str | None = None
    checksum: str | None = None
    etag: str | None = None


class FinalizeReferencesRequest(BaseModel):
    attachments: list[TrustedAttachmentDescriptor]


class FinalizeReferencesResponse(BaseModel):
    success: bool
    files: list[dict[str, str]]
    message: str


def _validate_reference_contract(thread_id: str, descriptor: TrustedAttachmentDescriptor) -> str:
    if descriptor.thread_id != thread_id:
        raise HTTPException(status_code=400, detail=f"Attachment thread_id mismatch for {descriptor.filename}")

    safe_filename = Path(descriptor.filename).name
    if safe_filename != descriptor.filename or safe_filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail=f"Unsafe filename in attachment descriptor: {descriptor.filename!r}")

    expected_virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"

    # Primary contract input is object key, not arbitrary external URL.
    if descriptor.object_key.strip() == "":
        raise HTTPException(status_code=400, detail=f"Missing object_key for attachment: {safe_filename}")

    if descriptor.trusted_url:
        parsed = urlparse(descriptor.trusted_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail=f"Invalid trusted_url for attachment: {safe_filename}")

    return expected_virtual_path


def get_uploads_dir(thread_id: str) -> Path:
    """Get the uploads directory for a thread.

    Args:
        thread_id: The thread ID.

    Returns:
        Path to the uploads directory.
    """
    base_dir = get_paths().sandbox_uploads_dir(thread_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


async def convert_file_to_markdown(file_path: Path) -> Path | None:
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


@router.post("", response_model=UploadResponse)
async def upload_files(
    thread_id: str,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """Upload multiple files to a thread's uploads directory.

    For PDF, PPT, Excel, and Word files, they will be converted to markdown using markitdown.
    All files (original and converted) are saved to /mnt/user-data/uploads.

    Args:
        thread_id: The thread ID to upload files to.
        files: List of files to upload.

    Returns:
        Upload response with success status and file information.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    uploads_dir = get_uploads_dir(thread_id)
    paths = get_paths()
    uploads_backend = get_thread_file_backend("uploads")
    sidecar_backend = get_thread_file_backend("upload_markdown_sidecars")
    uploaded_files = []

    sandbox_provider = get_sandbox_provider()
    sandbox_id = sandbox_provider.acquire(thread_id)
    sandbox = sandbox_provider.get(sandbox_id)

    for file in files:
        if not file.filename:
            continue

        try:
            # Normalize filename to prevent path traversal
            safe_filename = Path(file.filename).name
            if not safe_filename or safe_filename in {".", ".."} or "/" in safe_filename or "\\" in safe_filename:
                logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
                continue

            content = await file.read()
            file_path = uploads_dir / safe_filename
            file_path.write_bytes(content)
            uploads_backend.put_virtual_file(thread_id, f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}", content)
            evict_local_upload_cache(thread_id, keep_filenames={safe_filename})

            # Build relative path from backend root
            relative_path = str(paths.sandbox_uploads_dir(thread_id) / safe_filename)
            virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{safe_filename}"

            # Keep local sandbox source of truth in thread-scoped host storage.
            # For non-local sandboxes, also sync to virtual path for runtime visibility.
            if sandbox_id != "local":
                sandbox.update_file(virtual_path, content)

            file_info = {
                "filename": safe_filename,
                "size": str(len(content)),
                "path": relative_path,  # Actual filesystem path (relative to backend/)
                "virtual_path": virtual_path,  # Path for Agent in sandbox
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{safe_filename}",  # HTTP URL
            }

            logger.info(f"Saved file: {safe_filename} ({len(content)} bytes) to {relative_path}")

            # Check if file should be converted to markdown
            file_ext = file_path.suffix.lower()
            if file_ext in CONVERTIBLE_EXTENSIONS:
                md_path = await convert_file_to_markdown(file_path)
                if md_path:
                    md_relative_path = str(paths.sandbox_uploads_dir(thread_id) / md_path.name)
                    md_virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{md_path.name}"
                    md_content = md_path.read_bytes()
                    sidecar_backend.put_virtual_file(thread_id, md_virtual_path, md_content)
                    evict_local_upload_cache(thread_id, keep_filenames={safe_filename, md_path.name})

                    if sandbox_id != "local":
                        sandbox.update_file(md_virtual_path, md_content)

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = md_relative_path
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{md_path.name}"

            uploaded_files.append(file_info)

        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    return UploadResponse(
        success=True,
        files=uploaded_files,
        message=f"Successfully uploaded {len(uploaded_files)} file(s)",
    )


@router.post("/references", response_model=FinalizeReferencesResponse)
async def finalize_upload_references(thread_id: str, request: FinalizeReferencesRequest) -> FinalizeReferencesResponse:
    """Finalize trusted downstream upload references without proxying file bytes through this service."""
    if not request.attachments:
        raise HTTPException(status_code=400, detail="No attachments provided")

    uploads_backend = get_thread_file_backend("uploads")
    files: list[dict[str, str]] = []

    for descriptor in request.attachments:
        safe_filename = Path(descriptor.filename).name
        expected_virtual_path = _validate_reference_contract(thread_id, descriptor)

        # Enforce canonical key ownership to reject arbitrary external URL-driven contracts.
        expected_suffix = f"/{thread_id}/uploads/{safe_filename}"
        if not descriptor.object_key.endswith(expected_suffix):
            raise HTTPException(status_code=400, detail=f"Attachment object_key is outside canonical thread uploads namespace: {safe_filename}")

        if not uploads_backend.exists_virtual_file(thread_id, expected_virtual_path):
            raise HTTPException(status_code=404, detail=f"Attachment not found in durable backend: {safe_filename}")

        # Materialize on finalize for near-term runtime readiness, while remaining rehydratable cache.
        try:
            materialize_upload_to_local_cache(thread_id, expected_virtual_path)
        except Exception:
            logger.info("Attachment %s exists durably but local pre-materialization failed; runtime will lazy rehydrate", safe_filename)

        files.append(
            {
                "filename": safe_filename,
                "size": str(descriptor.size),
                "path": str(get_paths().sandbox_uploads_dir(thread_id) / safe_filename),
                "virtual_path": expected_virtual_path,
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{safe_filename}",
            }
        )

    return FinalizeReferencesResponse(success=True, files=files, message=f"Finalized {len(files)} trusted attachment reference(s)")


@router.get("/list", response_model=dict)
async def list_uploaded_files(thread_id: str) -> dict:
    """List all files in a thread's uploads directory.

    Args:
        thread_id: The thread ID to list files for.

    Returns:
        Dictionary containing list of files with their metadata.
    """
    uploads_backend = get_thread_file_backend("uploads")
    files = [build_upload_metadata(thread_id, item) for item in uploads_backend.list_uploads(thread_id)]
    return {"files": files, "count": len(files)}


@router.delete("/{filename}")
async def delete_uploaded_file(thread_id: str, filename: str) -> dict:
    """Delete a file from a thread's uploads directory.

    Args:
        thread_id: The thread ID.
        filename: The filename to delete.

    Returns:
        Success message.
    """
    uploads_dir = get_uploads_dir(thread_id)
    file_path = uploads_dir / filename
    virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"

    # Security check: ensure the path is within the uploads directory
    try:
        file_path.resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    uploads_backend = get_thread_file_backend("uploads")

    if not file_path.exists() and not uploads_backend.exists_virtual_file(thread_id, virtual_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    try:
        if file_path.exists():
            file_path.unlink()
        uploads_backend.delete_virtual_file(thread_id, virtual_path)

        # Delete derived markdown sidecar when it exists.
        md_name = f"{Path(filename).stem}.md"
        md_path = uploads_dir / md_name
        md_virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{md_name}"
        if md_path.exists():
            md_path.unlink()
        get_thread_file_backend("upload_markdown_sidecars").delete_virtual_file(thread_id, md_virtual_path)
        evict_local_upload_cache(thread_id)

        logger.info(f"Deleted file: {filename}")
        return {"success": True, "message": f"Deleted {filename}"}
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")

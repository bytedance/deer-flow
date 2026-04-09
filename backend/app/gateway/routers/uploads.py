"""Upload router for handling file uploads."""

import logging
import os
import stat

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from deerflow.config.paths import get_paths
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.uploads.manager import (
    PathTraversalError,
    delete_docx_sidecars,
    delete_file_safe,
    docx_sidecar_manifest_path,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    normalize_filename,
    upload_artifact_url,
    upload_virtual_path,
    write_docx_sidecar_manifest,
)
from deerflow.utils.file_conversion import (
    CONVERTIBLE_EXTENSIONS,
    convert_file_to_markdown,
    extract_docx_images,
    rewrite_docx_markdown_image_links,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])


class ExtractedImageInfo(BaseModel):
    """Metadata for a document image extracted into the uploads directory."""

    filename: str
    size: str
    path: str
    virtual_path: str
    artifact_url: str
    extension: str | None = None
    modified: float | None = None


class UploadedFileInfo(BaseModel):
    """Structured upload metadata returned by the gateway."""

    filename: str
    size: str
    path: str
    virtual_path: str
    artifact_url: str
    extension: str | None = None
    modified: float | None = None
    markdown_file: str | None = None
    markdown_path: str | None = None
    markdown_virtual_path: str | None = None
    markdown_artifact_url: str | None = None
    extracted_images: list[ExtractedImageInfo] | None = None


class UploadResponse(BaseModel):
    """Response model for file upload."""

    success: bool
    files: list[UploadedFileInfo]
    message: str


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


@router.post("", response_model=UploadResponse)
async def upload_files(
    thread_id: str,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """Upload multiple files to a thread's uploads directory."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    try:
        uploads_dir = ensure_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id)
    uploaded_files = []

    sandbox_provider = get_sandbox_provider()
    sandbox_id = sandbox_provider.acquire(thread_id)
    sandbox = sandbox_provider.get(sandbox_id)

    for file in files:
        if not file.filename:
            continue

        try:
            safe_filename = normalize_filename(file.filename)
        except ValueError:
            logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
            continue

        try:
            content = await file.read()
            file_path = uploads_dir / safe_filename
            file_path.write_bytes(content)

            virtual_path = upload_virtual_path(safe_filename)

            if sandbox_id != "local":
                _make_file_sandbox_writable(file_path)
                sandbox.update_file(virtual_path, content)

            file_info = {
                "filename": safe_filename,
                "size": str(len(content)),
                "path": str(sandbox_uploads / safe_filename),
                "virtual_path": virtual_path,
                "artifact_url": upload_artifact_url(thread_id, safe_filename),
            }

            logger.info(f"Saved file: {safe_filename} ({len(content)} bytes) to {file_info['path']}")

            file_ext = file_path.suffix.lower()
            if file_ext in CONVERTIBLE_EXTENSIONS:
                md_path = await convert_file_to_markdown(file_path)
                if md_path:
                    md_virtual_path = upload_virtual_path(md_path.name)

                    if sandbox_id != "local":
                        _make_file_sandbox_writable(md_path)
                        sandbox.update_file(md_virtual_path, md_path.read_bytes())

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = str(sandbox_uploads / md_path.name)
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

                if file_ext == ".docx":
                    delete_docx_sidecars(file_path)
                    extracted_images = []
                    extracted_image_paths = await extract_docx_images(file_path)
                    write_docx_sidecar_manifest(file_path, extracted_image_paths)
                    markdown_rewritten = False
                    if md_path and extracted_image_paths:
                        markdown_rewritten = rewrite_docx_markdown_image_links(md_path, extracted_image_paths)
                    manifest_path = docx_sidecar_manifest_path(file_path)
                    manifest_virtual_path = upload_virtual_path(manifest_path.name)
                    manifest_bytes = manifest_path.read_bytes() if manifest_path.is_file() else b""
                    if sandbox_id != "local" and manifest_bytes:
                        _make_file_sandbox_writable(manifest_path)
                        sandbox.update_file(manifest_virtual_path, manifest_bytes)
                    if sandbox_id != "local" and md_path and markdown_rewritten:
                        _make_file_sandbox_writable(md_path)
                        sandbox.update_file(md_virtual_path, md_path.read_bytes())
                    for image_path in extracted_image_paths:
                        image_virtual_path = upload_virtual_path(image_path.name)
                        image_bytes = image_path.read_bytes()

                        if sandbox_id != "local":
                            _make_file_sandbox_writable(image_path)
                            sandbox.update_file(image_virtual_path, image_bytes)

                        extracted_images.append(
                            {
                                "filename": image_path.name,
                                "size": str(image_path.stat().st_size),
                                "path": str(sandbox_uploads / image_path.name),
                                "virtual_path": image_virtual_path,
                                "artifact_url": upload_artifact_url(thread_id, image_path.name),
                                "extension": image_path.suffix,
                                "modified": image_path.stat().st_mtime,
                            }
                        )

                    if extracted_images:
                        file_info["extracted_images"] = extracted_images

            uploaded_files.append(file_info)

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
    """List all files in a thread's uploads directory."""
    try:
        uploads_dir = get_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = list_files_in_dir(uploads_dir)
    enrich_file_listing(result, thread_id)

    # Gateway additionally includes the sandbox-relative path.
    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id)
    for f in result["files"]:
        f["path"] = str(sandbox_uploads / f["filename"])
        for image in f.get("extracted_images", []):
            image["path"] = str(sandbox_uploads / image["filename"])

    return result


@router.delete("/{filename}")
async def delete_uploaded_file(thread_id: str, filename: str) -> dict:
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

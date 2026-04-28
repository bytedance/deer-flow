"""File system API for browsing, reading, writing, and deleting files in thread workspace."""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.gateway.path_utils import resolve_thread_virtual_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["filesystem"])

# Supported file extensions for browsing
SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".log"}

# Maximum file size for reading (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


class DirectoryEntry(BaseModel):
    """Directory entry model."""

    name: str
    path: str
    isDirectory: bool


class BrowseResponse(BaseModel):
    """Response for directory browsing."""

    currentPath: str
    parentPath: str
    entries: list[DirectoryEntry]


class ReadResponse(BaseModel):
    """Response for file reading."""

    path: str
    name: str
    content: str
    size: int
    modifiedAt: str


class WriteResponse(BaseModel):
    """Response for file writing."""

    success: bool
    path: str
    size: int
    modifiedAt: str


class WriteRequest(BaseModel):
    """Request body for file writing."""

    path: str
    content: str


class DeleteResponse(BaseModel):
    """Response for file deletion."""

    success: bool
    path: str


@router.get(
    "/threads/{thread_id}/filesystem/browse",
    summary="Browse Workspace Directory",
    description="List directory contents in the thread workspace.",
    response_model=BrowseResponse,
)
async def browse_directory(
    thread_id: str,
    path: str = "/mnt/user-data/workspace",
    extensions: str | None = None,
):
    """Browse directory contents in the thread workspace.

    Args:
        thread_id: The thread ID.
        path: Virtual directory path (default: /mnt/user-data/workspace).
        extensions: Comma-separated file extensions to filter (e.g., "md,txt,json,log").

    Returns:
        Directory contents with folders and filtered files.
    """
    try:
        actual_path = resolve_thread_virtual_path(thread_id, path)

        if not actual_path.exists():
            raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

        if not actual_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

        entries = []
        allowed_extensions = None
        if extensions:
            allowed_extensions = {f".{ext.strip().lower()}" for ext in extensions.split(",")}

        for item in sorted(actual_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name.startswith("."):
                continue

            if item.is_dir():
                entries.append(
                    DirectoryEntry(
                        name=item.name,
                        path=f"{path}/{item.name}",
                        isDirectory=True,
                    )
                )
            elif item.is_file():
                if allowed_extensions:
                    if item.suffix.lower() in allowed_extensions:
                        entries.append(
                            DirectoryEntry(
                                name=item.name,
                                path=f"{path}/{item.name}",
                                isDirectory=False,
                            )
                        )
                else:
                    if item.suffix.lower() in SUPPORTED_EXTENSIONS:
                        entries.append(
                            DirectoryEntry(
                                name=item.name,
                                path=f"{path}/{item.name}",
                                isDirectory=False,
                            )
                        )

        parent_path = str(Path(path).parent) if path != "/" else path

        return BrowseResponse(
            currentPath=path,
            parentPath=parent_path,
            entries=entries,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to browse directory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to browse directory: {str(e)}")


@router.get(
    "/threads/{thread_id}/filesystem/read",
    summary="Read File Content",
    description="Read the content of a file in the thread workspace.",
    response_model=ReadResponse,
)
async def read_file(thread_id: str, path: str):
    """Read file content from the thread workspace.

    Args:
        thread_id: The thread ID.
        path: Virtual file path.

    Returns:
        File content and metadata.
    """
    try:
        actual_path = resolve_thread_virtual_path(thread_id, path)

        if not actual_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        if not actual_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")

        if actual_path.stat().st_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large (max 10MB)")

        content = actual_path.read_text(encoding="utf-8")
        stat = actual_path.stat()

        return ReadResponse(
            path=path,
            name=actual_path.name,
            content=content,
            size=stat.st_size,
            modifiedAt=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


@router.post(
    "/threads/{thread_id}/filesystem/write",
    summary="Write File Content",
    description="Write or update a file in the thread workspace.",
    response_model=WriteResponse,
)
async def write_file(thread_id: str, request: WriteRequest):
    """Write file content to the thread workspace.

    Args:
        thread_id: The thread ID.
        request: File path and content.

    Returns:
        Success status and file metadata.
    """
    try:
        actual_path = resolve_thread_virtual_path(thread_id, request.path)

        if actual_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Path is a directory: {request.path}")

        actual_path.parent.mkdir(parents=True, exist_ok=True)
        actual_path.write_text(request.content, encoding="utf-8")

        stat = actual_path.stat()

        return WriteResponse(
            success=True,
            path=request.path,
            size=stat.st_size,
            modifiedAt=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to write file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write file: {str(e)}")


@router.delete(
    "/threads/{thread_id}/filesystem/delete",
    summary="Delete File",
    description="Delete a file in the thread workspace.",
    response_model=DeleteResponse,
)
async def delete_file(thread_id: str, path: str):
    """Delete a file from the thread workspace.

    Args:
        thread_id: The thread ID.
        path: Virtual file path.

    Returns:
        Success status.
    """
    try:
        actual_path = resolve_thread_virtual_path(thread_id, path)

        if not actual_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        if actual_path.is_dir():
            raise HTTPException(status_code=403, detail="Cannot delete directory using this endpoint")

        actual_path.unlink()

        return DeleteResponse(
            success=True,
            path=path,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

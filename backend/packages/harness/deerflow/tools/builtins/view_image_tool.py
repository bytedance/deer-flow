import mimetypes
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.tools.types import Runtime

_ALLOWED_IMAGE_VIRTUAL_ROOTS = (
    f"{VIRTUAL_PATH_PREFIX}/workspace",
    f"{VIRTUAL_PATH_PREFIX}/uploads",
    f"{VIRTUAL_PATH_PREFIX}/outputs",
)
_ALLOWED_IMAGE_VIRTUAL_ROOTS_TEXT = ", ".join(_ALLOWED_IMAGE_VIRTUAL_ROOTS)
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _is_allowed_image_virtual_path(image_path: str, *, allow_custom_mount: bool = False) -> bool:
    if any(image_path == root or image_path.startswith(f"{root}/") for root in _ALLOWED_IMAGE_VIRTUAL_ROOTS):
        return True
    if allow_custom_mount:
        from deerflow.sandbox.tools import _is_custom_mount_path

        return _is_custom_mount_path(image_path)
    return False


def _detect_image_mime(image_data: bytes) -> str | None:
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(image_data) >= 12 and image_data.startswith(b"RIFF") and image_data[8:12] == b"WEBP":
        return "image/webp"
    if image_data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


@tool("view_image", parse_docstring=True)
def view_image_tool(
    runtime: Runtime,
    image_path: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Read an image file.

    Use this tool to read an image file and make it available for display.

    When to use the view_image tool:
    - When you need to view an image file.

    When NOT to use the view_image tool:
    - For non-image files (use present_files instead)
    - For multiple files at once (use present_files instead)

    Args:
        image_path: Absolute /mnt/user-data virtual path or configured local-mount path to the image file. On Windows LocalSandbox, a configured host spelling is also accepted. Common formats supported: jpg, jpeg, png, webp, gif.
    """
    from deerflow.sandbox.exceptions import SandboxError
    from deerflow.sandbox.security import uses_local_sandbox_provider
    from deerflow.sandbox.tools import (
        ensure_sandbox_initialized,
        get_thread_data,
        is_local_sandbox,
        normalize_local_tool_path,
        resolve_and_validate_user_data_path,
        validate_local_tool_path,
    )

    thread_data = get_thread_data(runtime)
    local_runtime = is_local_sandbox(runtime)
    local_provider = local_runtime or uses_local_sandbox_provider()
    try:
        if local_provider:
            image_path = normalize_local_tool_path(image_path)
    except (PermissionError, SandboxError):
        # Host-path normalization can fail before a virtual path is available;
        # keep the raw host spelling out of the model-visible ToolMessage.
        return Command(
            update={"messages": [ToolMessage("Error: Image path is not allowed", tool_call_id=tool_call_id)]},
        )

    if not _is_allowed_image_virtual_path(image_path, allow_custom_mount=local_provider):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Error: Only image paths under {_ALLOWED_IMAGE_VIRTUAL_ROOTS_TEXT} or configured local mounts are allowed",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    try:
        validate_local_tool_path(image_path, thread_data, read_only=True)
        if local_provider:
            from deerflow.sandbox.tools import _is_custom_mount_path

            if _is_custom_mount_path(image_path):
                sandbox = ensure_sandbox_initialized(runtime)
                actual_path = sandbox._resolve_path(image_path)
            else:
                actual_path = resolve_and_validate_user_data_path(image_path, thread_data)
        else:
            actual_path = resolve_and_validate_user_data_path(image_path, thread_data)
    except (PermissionError, SandboxError) as e:
        return Command(
            update={"messages": [ToolMessage(f"Error: {str(e)}", tool_call_id=tool_call_id)]},
        )

    path = Path(actual_path)

    # Validate that the file exists
    if not path.exists():
        return Command(
            update={"messages": [ToolMessage(f"Error: Image file not found: {image_path}", tool_call_id=tool_call_id)]},
        )

    # Validate that it's a file (not a directory)
    if not path.is_file():
        return Command(
            update={"messages": [ToolMessage(f"Error: Path is not a file: {image_path}", tool_call_id=tool_call_id)]},
        )

    # Validate image extension
    expected_mime_type = _EXTENSION_TO_MIME.get(path.suffix.lower())
    if expected_mime_type is None:
        return Command(
            update={"messages": [ToolMessage(f"Error: Unsupported image format: {path.suffix}. Supported formats: {', '.join(_EXTENSION_TO_MIME)}", tool_call_id=tool_call_id)]},
        )

    # Detect MIME type from file extension
    mime_type, _ = mimetypes.guess_type(actual_path)
    if mime_type is None:
        mime_type = expected_mime_type

    try:
        image_size = path.stat().st_size
    except OSError:
        return Command(
            update={"messages": [ToolMessage(f"Error reading image metadata: {image_path}", tool_call_id=tool_call_id)]},
        )
    if image_size > _MAX_IMAGE_BYTES:
        return Command(
            update={"messages": [ToolMessage(f"Error: Image file is too large: {image_size} bytes. Maximum supported size is {_MAX_IMAGE_BYTES} bytes", tool_call_id=tool_call_id)]},
        )

    # Read image file to validate contents (magic bytes + size)
    try:
        with open(actual_path, "rb") as f:
            image_data = f.read()
    except Exception:
        return Command(
            update={"messages": [ToolMessage(f"Error reading image file: {image_path}", tool_call_id=tool_call_id)]},
        )

    if len(image_data) != image_size:
        # File changed between stat() and read() - reject for safety.
        return Command(
            update={"messages": [ToolMessage("Error: Image file changed during read", tool_call_id=tool_call_id)]},
        )

    detected_mime_type = _detect_image_mime(image_data)
    if detected_mime_type is None:
        return Command(
            update={"messages": [ToolMessage("Error: File contents do not match a supported image format", tool_call_id=tool_call_id)]},
        )
    if detected_mime_type != expected_mime_type:
        return Command(
            update={"messages": [ToolMessage(f"Error: Image contents are {detected_mime_type}, but file extension indicates {expected_mime_type}", tool_call_id=tool_call_id)]},
        )
    mime_type = detected_mime_type

    # Store only lightweight metadata in state (not base64) to avoid
    # duplicating large payloads across every checkpoint (see #4138).
    # The middleware reads the file on-demand when the model needs it.
    new_viewed_images = {
        image_path: {
            "mime_type": mime_type,
            "size": image_size,
            "actual_path": str(actual_path),
        }
    }

    return Command(
        update={"viewed_images": new_viewed_images, "messages": [ToolMessage("Successfully read image", tool_call_id=tool_call_id)]},
    )

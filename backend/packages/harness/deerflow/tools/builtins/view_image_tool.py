import hashlib
import mimetypes
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadDataState
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


def _is_allowed_image_virtual_path(image_path: str) -> bool:
    return any(image_path == root or image_path.startswith(f"{root}/") for root in _ALLOWED_IMAGE_VIRTUAL_ROOTS)


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


def _sanitize_image_error(error: Exception, thread_data: ThreadDataState | None) -> str:
    from deerflow.sandbox.tools import mask_local_paths_in_output

    return mask_local_paths_in_output(f"{type(error).__name__}: {error}", thread_data)


def _is_file_not_found_error(error: BaseException) -> bool:
    """Recognize an explicit missing-file signal through provider wrappers.

    ``Sandbox.download_file`` promises ``OSError`` for read failures, while
    remote SDKs expose missing paths in different explicit forms: builtin or
    provider-defined ``FileNotFoundError`` types, E2B's
    ``FileNotFoundException``, and HTTP-style exceptions carrying
    ``status_code == 404``. Walk only explicit ``raise ... from`` causes so an
    unrelated exception being handled when a transport failure is raised cannot
    accidentally authorize historical host recovery. Error-message strings are
    deliberately never parsed.
    """

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        error_type = type(current)
        if isinstance(current, FileNotFoundError) or error_type.__name__ == "FileNotFoundError":
            return True
        if error_type.__name__ == "FileNotFoundException" and error_type.__module__.split(".", 1)[0] == "e2b":
            return True
        if getattr(current, "status_code", None) == 404:
            return True
        current = current.__cause__
    return False


def _read_verified_host_copy(
    actual_path: str | Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> bytes | None:
    """Read a synchronized host image only when it matches prior metadata."""

    path = Path(actual_path)
    try:
        if not path.exists() or not path.is_file():
            return None
        size = path.stat().st_size
        if size != expected_size or size > _MAX_IMAGE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) != size:
        return None
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        return None
    return data


def _view_image(
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
        image_path: Absolute /mnt/user-data virtual path to the image file. Common formats supported: jpg, jpeg, png, webp, gif.
    """
    from deerflow.sandbox.exceptions import SandboxRuntimeError
    from deerflow.sandbox.overwrite import unwrap_sandbox
    from deerflow.sandbox.sandbox_provider import get_sandbox_provider
    from deerflow.sandbox.tools import (
        get_thread_data,
        resolve_and_validate_user_data_path,
        validate_local_tool_path,
    )

    thread_data = get_thread_data(runtime)

    if not _is_allowed_image_virtual_path(image_path):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Error: Only image paths under {_ALLOWED_IMAGE_VIRTUAL_ROOTS_TEXT} are allowed",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    try:
        validate_local_tool_path(image_path, thread_data, read_only=True)
        actual_path = resolve_and_validate_user_data_path(image_path, thread_data)
    except (PermissionError, SandboxRuntimeError) as e:
        return Command(
            update={"messages": [ToolMessage(f"Error: {str(e)}", tool_call_id=tool_call_id)]},
        )

    image_suffix = Path(image_path).suffix.lower()
    expected_mime_type = _EXTENSION_TO_MIME.get(image_suffix)
    if expected_mime_type is None:
        return Command(
            update={"messages": [ToolMessage(f"Error: Unsupported image format: {image_suffix}. Supported formats: {', '.join(_EXTENSION_TO_MIME)}", tool_call_id=tool_call_id)]},
        )

    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type is None:
        mime_type = expected_mime_type

    state = runtime.state or {}
    sandbox_state, _ = unwrap_sandbox(state.get("sandbox"))
    sandbox_id = sandbox_state.get("sandbox_id") if isinstance(sandbox_state, dict) else None
    sandbox = get_sandbox_provider().get(sandbox_id) if sandbox_id else None
    viewed_images = state.get("viewed_images")
    previous_view = viewed_images.get(image_path) if isinstance(viewed_images, dict) else None
    previous_source_id = previous_view.get("source_sandbox_id") if isinstance(previous_view, dict) else None
    read_source_sandbox_id: str | None = None

    if sandbox is not None:
        try:
            image_data = sandbox.download_file(image_path)
            read_source_sandbox_id = sandbox_id
        except IsADirectoryError:
            return Command(
                update={"messages": [ToolMessage(f"Error: Path is not a file: {image_path}", tool_call_id=tool_call_id)]},
            )
        except Exception as e:
            # A replacement sandbox may be live without containing files from
            # the earlier generation. Recover only from an explicitly missing
            # file and only when the synchronized host copy matches the exact
            # metadata of the previously viewed image. Other live-client
            # failures stay fail-closed so a stale mirror cannot mask them.
            if _is_file_not_found_error(e) and isinstance(previous_view, dict) and previous_source_id != sandbox_id:
                previous_size = previous_view.get("size")
                previous_sha256 = previous_view.get("sha256")
                if isinstance(previous_size, int) and isinstance(previous_sha256, str):
                    recovered = _read_verified_host_copy(
                        actual_path,
                        expected_size=previous_size,
                        expected_sha256=previous_sha256,
                    )
                    if recovered is not None:
                        image_data = recovered
                    else:
                        return Command(
                            update={"messages": [ToolMessage(f"Error: Image file not found: {image_path}", tool_call_id=tool_call_id)]},
                        )
                else:
                    return Command(
                        update={"messages": [ToolMessage(f"Error: Image file not found: {image_path}", tool_call_id=tool_call_id)]},
                    )
            elif _is_file_not_found_error(e):
                return Command(
                    update={"messages": [ToolMessage(f"Error: Image file not found: {image_path}", tool_call_id=tool_call_id)]},
                )
            else:
                return Command(
                    update={"messages": [ToolMessage(f"Error reading image file: {_sanitize_image_error(e, thread_data)}", tool_call_id=tool_call_id)]},
                )
        image_size = len(image_data)
    else:
        path = Path(actual_path)
        if not path.exists():
            return Command(
                update={"messages": [ToolMessage(f"Error: Image file not found: {image_path}", tool_call_id=tool_call_id)]},
            )
        if not path.is_file():
            return Command(
                update={"messages": [ToolMessage(f"Error: Path is not a file: {image_path}", tool_call_id=tool_call_id)]},
            )

        try:
            image_size = path.stat().st_size
        except OSError as e:
            return Command(
                update={"messages": [ToolMessage(f"Error reading image metadata: {_sanitize_image_error(e, thread_data)}", tool_call_id=tool_call_id)]},
            )
        if image_size > _MAX_IMAGE_BYTES:
            return Command(
                update={"messages": [ToolMessage(f"Error: Image file is too large: {image_size} bytes. Maximum supported size is {_MAX_IMAGE_BYTES} bytes", tool_call_id=tool_call_id)]},
            )

        try:
            with open(actual_path, "rb") as f:
                image_data = f.read()
        except Exception as e:
            return Command(
                update={"messages": [ToolMessage(f"Error reading image file: {_sanitize_image_error(e, thread_data)}", tool_call_id=tool_call_id)]},
            )

        if len(image_data) != image_size:
            return Command(
                update={"messages": [ToolMessage("Error: Image file changed during read", tool_call_id=tool_call_id)]},
            )

    if image_size > _MAX_IMAGE_BYTES:
        return Command(
            update={"messages": [ToolMessage(f"Error: Image file is too large: {image_size} bytes. Maximum supported size is {_MAX_IMAGE_BYTES} bytes", tool_call_id=tool_call_id)]},
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

    image_metadata = {
        "mime_type": mime_type,
        "size": image_size,
        "actual_path": str(actual_path),
        "sha256": hashlib.sha256(image_data).hexdigest(),
    }
    if read_source_sandbox_id is not None:
        image_metadata["source_sandbox_id"] = read_source_sandbox_id
    new_viewed_images = {image_path: image_metadata}

    return Command(
        update={"viewed_images": new_viewed_images, "messages": [ToolMessage("Successfully read image", tool_call_id=tool_call_id)]},
    )


async def _aview_image(
    runtime: Runtime,
    image_path: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Run the blocking image read without letting cancellation outlive it."""
    from deerflow.sandbox.lease import run_sync_lifecycle_operation

    return await run_sync_lifecycle_operation(
        _view_image,
        runtime,
        image_path,
        tool_call_id,
    )


view_image_tool = StructuredTool.from_function(
    func=_view_image,
    coroutine=_aview_image,
    name="view_image",
    parse_docstring=True,
)

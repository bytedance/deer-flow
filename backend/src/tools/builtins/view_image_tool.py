import base64
import io
import json
import mimetypes
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT
from PIL import Image

from src.agents.thread_state import ThreadState
from src.sandbox.tools import get_thread_data, is_local_sandbox, replace_virtual_path

# Max dimension for resizing images before sending to the LLM.
# 1024px is sufficient for vision models to understand content while keeping tokens low.
MAX_IMAGE_DIMENSION = 1024


def _resize_image_bytes(image_data: bytes, mime_type: str) -> tuple[bytes, str]:
    """Resize image to fit within MAX_IMAGE_DIMENSION, preserving aspect ratio.

    Returns the (possibly resized) image bytes and the output mime type.
    If the image is already small enough, returns the original data unchanged.
    """
    try:
        img = Image.open(io.BytesIO(image_data))
        w, h = img.size

        if w <= MAX_IMAGE_DIMENSION and h <= MAX_IMAGE_DIMENSION:
            return image_data, mime_type

        # Calculate new dimensions preserving aspect ratio
        ratio = min(MAX_IMAGE_DIMENSION / w, MAX_IMAGE_DIMENSION / h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)

        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Re-encode to the same format (default JPEG for smaller size)
        buf = io.BytesIO()
        out_format = "JPEG"
        out_mime = "image/jpeg"
        if mime_type == "image/png":
            out_format = "PNG"
            out_mime = "image/png"
        elif mime_type == "image/webp":
            out_format = "WEBP"
            out_mime = "image/webp"

        # Convert RGBA to RGB for JPEG
        if out_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        img.save(buf, format=out_format, quality=85)
        return buf.getvalue(), out_mime
    except Exception:
        # If resizing fails, return original data
        return image_data, mime_type


@tool("view_image", parse_docstring=True)
def view_image_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
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
        image_path: Absolute path to the image file. Common formats supported: jpg, jpeg, png, webp.
    """
    # Replace virtual path with actual path.
    # For local sandbox: translate /mnt/user-data/* to host thread directories.
    # For Docker/aio sandbox: paths are already mounted at /mnt/user-data/*.
    # If sandbox state is not yet set, default to path replacement (safe fallback).
    sandbox_state = runtime.state.get("sandbox") if runtime.state else None
    is_docker = sandbox_state is not None and sandbox_state.get("sandbox_id") != "local"

    if is_docker:
        actual_path = image_path
    else:
        thread_data = get_thread_data(runtime)
        actual_path = replace_virtual_path(image_path, thread_data)

    # Validate that the path is absolute
    path = Path(actual_path)
    if not path.is_absolute():
        return Command(
            update={"messages": [ToolMessage(f"Error: Path must be absolute, got: {image_path}", tool_call_id=tool_call_id)]},
        )

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
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    if path.suffix.lower() not in valid_extensions:
        return Command(
            update={"messages": [ToolMessage(f"Error: Unsupported image format: {path.suffix}. Supported formats: {', '.join(valid_extensions)}", tool_call_id=tool_call_id)]},
        )

    # Detect MIME type from file extension
    mime_type, _ = mimetypes.guess_type(actual_path)
    if mime_type is None:
        extension_to_mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        mime_type = extension_to_mime.get(path.suffix.lower(), "application/octet-stream")

    # Read image file, resize to save tokens, and convert to base64
    try:
        with open(actual_path, "rb") as f:
            image_data = f.read()

        # Resize to max 1024px to keep token usage reasonable
        image_data, mime_type = _resize_image_bytes(image_data, mime_type)
        image_base64 = base64.b64encode(image_data).decode("utf-8")
    except Exception as e:
        return Command(
            update={"messages": [ToolMessage(f"Error reading image file: {str(e)}", tool_call_id=tool_call_id)]},
        )

    # Embed image data in the ToolMessage content as JSON so the ViewImageMiddleware
    # can extract it. This avoids updating viewed_images via Command, which crashes
    # when the agent calls view_image multiple times in parallel (LangGraph does not
    # allow multiple Command updates to the same state key in one step).
    result_payload = json.dumps({
        "__view_image__": True,
        "image_path": image_path,
        "base64": image_base64,
        "mime_type": mime_type,
    })

    return Command(
        update={"messages": [ToolMessage(result_payload, tool_call_id=tool_call_id)]},
    )

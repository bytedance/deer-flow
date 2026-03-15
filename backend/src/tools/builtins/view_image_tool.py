import base64
import io
import logging
import mimetypes
from pathlib import Path
from typing import Annotated
import json

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.sandbox.tools import get_thread_data, replace_virtual_path

logger = logging.getLogger(__name__)

# Max dimension (width or height) for images sent to LLM.
# GPT-4o and Claude both downscale internally — sending 4K is pure waste.
# 1024px is enough for the model to see composition, details, and quality.
MAX_IMAGE_DIMENSION = 1024

# JPEG quality for compressed images sent to LLM context.
# 85 is visually lossless while being ~5-10x smaller than PNG.
JPEG_QUALITY = 85


def _resize_and_compress(image_data: bytes, max_dim: int = MAX_IMAGE_DIMENSION) -> tuple[bytes, str]:
    """Resize image to fit within max_dim and compress as JPEG.

    A 4K PNG (10-20MB) becomes a 1024px JPEG (~50-150KB).
    This saves ~99% of tokens vs sending the raw image.

    Args:
        image_data: Raw image bytes.
        max_dim: Maximum dimension (width or height).

    Returns:
        Tuple of (compressed_bytes, mime_type).
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_data))

        # Log original size
        orig_size = len(image_data)
        orig_w, orig_h = img.size

        # Resize if larger than max_dim
        if max(orig_w, orig_h) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # Convert to RGB if needed (PNG with alpha, palette mode, etc.)
        if img.mode in ("RGBA", "P", "LA"):
            # Preserve transparency info in a white background
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Compress as JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        compressed = buffer.getvalue()

        new_w, new_h = img.size
        logger.info(
            f"Image resized for LLM: {orig_w}x{orig_h} ({orig_size:,}B) → "
            f"{new_w}x{new_h} ({len(compressed):,}B) — "
            f"{orig_size / max(len(compressed), 1):.0f}x smaller"
        )

        return compressed, "image/jpeg"
    except Exception as e:
        logger.warning(f"Image resize failed, using original: {e}")
        return image_data, "image/png"


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

    # Read image file, resize for LLM, and convert to base64
    try:
        with open(actual_path, "rb") as f:
            raw_data = f.read()

        # Resize and compress before sending to LLM
        # 4K PNG (10-20MB) → 1024px JPEG (~50-150KB) — 99% smaller
        compressed_data, mime_type = _resize_and_compress(raw_data)
        image_base64 = base64.b64encode(compressed_data).decode("utf-8")
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

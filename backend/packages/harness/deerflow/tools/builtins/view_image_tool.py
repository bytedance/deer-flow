import base64
import mimetypes
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.sandbox.tools import get_thread_data, replace_virtual_path


@tool("view_image", parse_docstring=True)
def view_image_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    image_path: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Read an image 文件.

    Use this 工具 to read an image 文件 and make it 可用的 for display.

    When to use the view_image 工具:
    - When you need to view an image 文件.

    When NOT to use the view_image 工具:
    - For non-image files (use present_files instead)
    - For multiple files at once (use present_files instead)

    Args:
        image_path: Absolute 路径 to the image 文件. Common formats supported: jpg, jpeg, png, webp.
    """
    #    Replace virtual 路径 with actual 路径


    #    /mnt/用户-数据/* paths are mapped to 线程-specific directories


    thread_data = get_thread_data(runtime)
    actual_path = replace_virtual_path(image_path, thread_data)

    #    Validate that the 路径 is absolute


    path = Path(actual_path)
    if not path.is_absolute():
        return Command(
            update={"messages": [ToolMessage(f"Error: Path must be absolute, got: {image_path}", tool_call_id=tool_call_id)]},
        )

    #    Validate that the 文件 exists


    if not path.exists():
        return Command(
            update={"messages": [ToolMessage(f"Error: Image file not found: {image_path}", tool_call_id=tool_call_id)]},
        )

    #    Validate that it's a 文件 (not a 目录)


    if not path.is_file():
        return Command(
            update={"messages": [ToolMessage(f"Error: Path is not a file: {image_path}", tool_call_id=tool_call_id)]},
        )

    #    Validate image extension


    valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    if path.suffix.lower() not in valid_extensions:
        return Command(
            update={"messages": [ToolMessage(f"Error: Unsupported image format: {path.suffix}. Supported formats: {', '.join(valid_extensions)}", tool_call_id=tool_call_id)]},
        )

    #    Detect MIME 类型 from 文件 extension


    mime_type, _ = mimetypes.guess_type(actual_path)
    if mime_type is None:
        #    Fallback to 默认 MIME types 对于 common image formats


        extension_to_mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        mime_type = extension_to_mime.get(path.suffix.lower(), "application/octet-stream")

    #    Read image 文件 and convert to base64


    try:
        with open(actual_path, "rb") as f:
            image_data = f.read()
            image_base64 = base64.b64encode(image_data).decode("utf-8")
    except Exception as e:
        return Command(
            update={"messages": [ToolMessage(f"Error reading image file: {str(e)}", tool_call_id=tool_call_id)]},
        )

    #    Update viewed_images in 状态


    #    The merge_viewed_images reducer will 处理 merging with existing images


    new_viewed_images = {image_path: {"base64": image_base64, "mime_type": mime_type}}

    return Command(
        update={"viewed_images": new_viewed_images, "messages": [ToolMessage("Successfully read image", tool_call_id=tool_call_id)]},
    )

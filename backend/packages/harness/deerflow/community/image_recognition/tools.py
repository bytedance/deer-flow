"""
Image Recognition Tool - Analyze images using vision-capable LLMs.

This tool provides comprehensive image analysis capabilities including:
- Object detection and recognition
- Scene understanding and description
- Text extraction (OCR)
- Face detection and analysis
- Image quality assessment
"""

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import requests
from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.config import get_app_config
from deerflow.models.factory import create_chat_model
from deerflow.sandbox.tools import get_thread_data, replace_virtual_path

logger = logging.getLogger(__name__)


def _is_url(path: str) -> bool:
    """Check if the given path is a URL."""
    try:
        result = urlparse(path)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def _download_image(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Download image from URL.

    Args:
        url: The image URL to download
        timeout: Request timeout in seconds

    Returns:
        Tuple of (image_bytes, mime_type)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=timeout, stream=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "application/octet-stream")
    return response.content, content_type


def _load_local_image(image_path: str, thread_data: dict | None = None) -> tuple[bytes, str]:
    """Load image from local file system.

    Args:
        image_path: Path to the image file
        thread_data: Thread data for virtual path resolution

    Returns:
        Tuple of (image_bytes, mime_type)
    """
    # Replace virtual path with actual path
    if thread_data:
        actual_path = replace_virtual_path(image_path, thread_data)
    else:
        actual_path = image_path

    path = Path(actual_path)

    if not path.is_absolute():
        raise ValueError(f"Path must be absolute, got: {image_path}")

    if not path.exists():
        raise ValueError(f"Image file not found: {image_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {image_path}")

    # Validate image extension
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    if path.suffix.lower() not in valid_extensions:
        raise ValueError(f"Unsupported image format: {path.suffix}")

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(actual_path)
    if mime_type is None:
        extension_to_mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        mime_type = extension_to_mime.get(path.suffix.lower(), "application/octet-stream")

    with open(actual_path, "rb") as f:
        image_bytes = f.read()

    return image_bytes, mime_type


def _encode_image(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def _analyze_image_with_vision_model(
    image_base64: str,
    mime_type: str,
    analysis_type: str,
    prompt: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Analyze image using a vision-capable LLM.

    Args:
        image_base64: Base64 encoded image data
        mime_type: MIME type of the image
        analysis_type: Type of analysis to perform
        prompt: Custom prompt for analysis (optional)
        model_name: Specific model to use (optional)

    Returns:
        Analysis results as a dictionary
    """
    config = get_app_config()

    # Get vision-capable model
    if model_name:
        model_config = config.get_model_config(model_name)
        if not model_config or not model_config.supports_vision:
            raise ValueError(f"Model {model_name} does not support vision")
    else:
        # Find first vision-capable model
        model_config = None
        for mc in config.models:
            if mc.supports_vision:
                model_config = mc
                model_name = mc.name
                break

        if not model_config:
            raise ValueError("No vision-capable model found in configuration")

    # Create model instance
    model = create_chat_model(model_name)

    # Build analysis prompt based on type
    default_prompts = {
        "general": "Please provide a detailed description of this image. Include: 1) Main subjects and objects, 2) Scene/setting, 3) Colors and visual style, 4) Any notable details.",
        "objects": "Identify and list all objects in this image. For each object, provide: name, approximate location, and any distinguishing features.",
        "text": "Extract all text visible in this image. Preserve the layout and formatting as much as possible. If text is in multiple languages, identify each language.",
        "faces": "Analyze any human faces in this image. For each face, describe: approximate age range, gender, expression/emotion, and any notable features. Note: Do not attempt to identify specific individuals.",
        "scene": "Describe the scene/setting of this image. Include: location type, time of day, weather/lighting conditions, and overall atmosphere/mood.",
        "quality": "Assess the technical quality of this image. Evaluate: resolution, sharpness, lighting, composition, color balance, and any artifacts or issues.",
    }

    analysis_prompt = prompt or default_prompts.get(analysis_type, default_prompts["general"])

    # Construct message with image
    from langchain_core.messages import HumanMessage

    message = HumanMessage(
        content=[
            {"type": "text", "text": analysis_prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
            },
        ]
    )

    # Get response from model
    response = model.invoke([message])

    return {
        "analysis_type": analysis_type,
        "model_used": model_name,
        "description": response.content,
    }


@tool("image_recognition", parse_docstring=True)
def image_recognition_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    image_source: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    analysis_type: str = "general",
    custom_prompt: str | None = None,
) -> Command:
    """Analyze and recognize content in images using AI vision models.

    Use this tool to:
    - Get detailed descriptions of images
    - Identify objects, people, and scenes
    - Extract text from images (OCR)
    - Analyze image quality and composition
    - Understand visual content for decision making

    When to use the image_recognition tool:
    - When you need to understand what's in an image
    - When processing uploaded image files from users
    - When analyzing images referenced by URL
    - Before performing operations based on image content

    When NOT to use the image_recognition tool:
    - For simple image viewing (use view_image instead)
    - For image generation (use image generation tools)
    - For image format conversion (use image processing libraries)

    Args:
        image_source: Path to the image file (absolute path) or URL. Supported formats:
            jpg, jpeg, png, webp, gif, bmp.
        analysis_type: Type of analysis to perform. Options: "general" (comprehensive
            description), "objects" (object detection), "text" (OCR), "faces" (face
            analysis), "scene" (scene understanding), "quality" (technical assessment).
            Default is "general".
        custom_prompt: Custom analysis prompt to override default behavior. Use this for
            specific analysis needs not covered by analysis_type.
    """

    # Suppress unused variable warning - tool_call_id is injected by the framework
    _ = tool_call_id
    try:
        # Get thread data for path resolution
        thread_data = get_thread_data(runtime)

        # Load image based on source type
        if _is_url(image_source):
            logger.info(f"Downloading image from URL: {image_source}")
            try:
                image_bytes, mime_type = _download_image(image_source)
            except requests.RequestException as e:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                f"Error downloading image from URL: {str(e)}",
                                tool_call_id=tool_call_id,
                            )
                        ]
                    },
                )
        else:
            logger.info(f"Loading local image: {image_source}")
            try:
                image_bytes, mime_type = _load_local_image(image_source, thread_data)
            except ValueError as e:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                f"Error loading image: {str(e)}",
                                tool_call_id=tool_call_id,
                            )
                        ]
                    },
                )

        # Encode image
        image_base64 = _encode_image(image_bytes)

        # Analyze image
        logger.info(f"Performing {analysis_type} analysis on image")
        result = _analyze_image_with_vision_model(
            image_base64=image_base64,
            mime_type=mime_type,
            analysis_type=analysis_type,
            prompt=custom_prompt,
        )

        # Format output
        output = {
            "success": True,
            "image_source": image_source,
            "analysis_type": analysis_type,
            "model_used": result["model_used"],
            "analysis": result["description"],
        }

        if custom_prompt:
            output["custom_prompt_used"] = True

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        json.dumps(output, indent=2, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Configuration error: {str(e)}. Please ensure a vision-capable model is configured.",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )
    except Exception as e:
        logger.exception("Unexpected error during image recognition")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Error analyzing image: {str(e)}",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

"""Native image tool; the company credential is never exposed to the model."""

from typing import Annotated, Literal

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.tools.types import Runtime

from .service import generate_image


@tool("gpt_image2", parse_docstring=True)
async def gpt_image2_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    prompt: str,
    size: Literal["1024x1024", "1536x1024", "1024x1536", "auto"] = "1024x1024",
    quality: Literal["low", "medium", "high", "auto"] = "medium",
    reference_images: list[str] | None = None,
    mask: str | None = None,
) -> Command:
    """Generate or edit one image with GPT Image 2 using authorized company billing.

    Use for drawing, posters, product images and editing uploaded reference images.
    The result is automatically presented as a downloadable image in this chat.
    Requires explicit user or group access. Never ask users for the company key.
    Do not automatically retry timeouts: the original request may be billed.

    Args:
        prompt: Detailed image description or editing instructions, including exact text to render.
        size: Square, landscape or portrait canvas, or auto.
        quality: Rendering quality; medium by default, low for a draft, high for detailed final images.
        reference_images: Up to four current-conversation /mnt/user-data image paths for editing. Omit for text-to-image.
        mask: Optional PNG mask with alpha, same size as the first reference. Transparent areas are edited.
    """
    path = await generate_image(runtime, prompt, size=size, quality=quality, reference_images=reference_images, mask=mask)
    return Command(update={"artifacts": [path], "messages": [ToolMessage(content=f"Image generated and presented: {path}", tool_call_id=tool_call_id)]})

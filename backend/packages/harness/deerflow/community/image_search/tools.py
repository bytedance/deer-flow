"""
Image Search Tool - Search images using DuckDuckGo for reference in image generation.
"""

import asyncio
import json
import logging

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5


def _coerce_max_results(value: object) -> int:
    """Normalize config/parameter values before passing them to DDGS."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        # int() accepts booleans and silently truncates a YAML value such as 3.5.
        count = 0
    else:
        try:
            count = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError, OverflowError):
            count = 0
    if count <= 0:
        logger.warning("Invalid DDG image search max_results=%r; using default %s", value, DEFAULT_MAX_RESULTS)
        return DEFAULT_MAX_RESULTS
    return count


def _search_images(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
    safesearch: str = "moderate",
    size: str | None = None,
    color: str | None = None,
    type_image: str | None = None,
    layout: str | None = None,
    license_image: str | None = None,
) -> list[dict]:
    """
    Execute image search using DuckDuckGo.

    Args:
        query: Search keywords
        max_results: Maximum number of results
        region: Search region
        safesearch: Safe search level
        size: Image size (Small/Medium/Large/Wallpaper)
        color: Color filter
        type_image: Image type (photo/clipart/gif/transparent/line)
        layout: Layout (Square/Tall/Wide)
        license_image: License filter

    Returns:
        List of search results
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("ddgs library not installed. Run: pip install ddgs")
        return []

    ddgs = DDGS(timeout=30)

    try:
        kwargs = {
            "region": region,
            "safesearch": safesearch,
            "max_results": max_results,
        }

        if size:
            kwargs["size"] = size
        if color:
            kwargs["color"] = color
        if type_image:
            kwargs["type_image"] = type_image
        if layout:
            kwargs["layout"] = layout
        if license_image:
            kwargs["license_image"] = license_image

        results = ddgs.images(query, **kwargs)
        return list(results) if results else []

    except Exception as e:
        logger.error(f"Failed to search images: {e}")
        return []


@tool("image_search", parse_docstring=True)
async def image_search_tool(
    query: str,
    max_results: int = 5,
    size: str | None = None,
    color: str | None = None,
    type_image: str | None = None,
    layout: str | None = None,
    license_image: str | None = None,
) -> str:
    """Search for images online. Use this tool BEFORE image generation to find reference images for characters, portraits, objects, scenes, or any content requiring visual accuracy.

    **When to use:**
    - Before generating character/portrait images: search for similar poses, expressions, styles
    - Before generating specific objects/products: search for accurate visual references
    - Before generating scenes/locations: search for architectural or environmental references
    - Before generating fashion/clothing: search for style and detail references

    The returned image URLs can be used as reference images in image generation to significantly improve quality.

    Args:
        query: Search keywords describing the images you want to find. Be specific for better results (e.g., "Japanese woman street photography 1990s" instead of just "woman").
        max_results: Maximum number of images to return. Default is 5.
        size: Image size filter. Options: "Small", "Medium", "Large", "Wallpaper". Use "Large" for reference images.
        color: Color filter. Options: "color", "Monochrome", "Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Pink", "Brown", "Black", "Gray", "Teal", "White".
            Note that "color" means full-color (as opposed to "Monochrome"), not a meta-parameter.
            Match the dominant palette of the image you plan to generate; omit it for unrestricted results.
        type_image: Image type filter. Options: "photo", "clipart", "gif", "transparent", "line". Use "photo" for realistic references.
        layout: Layout filter. Options: "Square", "Tall", "Wide". Choose based on your generation needs.
        license_image: License filter. Options: "any", "Public", "Share", "ShareCommercially", "Modify", "ModifyCommercially".
            Use this when the reference image will be redistributed, so the results are already license-cleared.
    """

    def search_with_config() -> list[dict]:
        # Both config loading and DDGS perform blocking I/O. Keep the entire
        # search setup in one worker so neither can stall the agent event loop.
        config = get_app_config().get_tool_config("image_search")
        resolved_max_results = max_results
        if config is not None and "max_results" in config.model_extra:
            resolved_max_results = config.model_extra.get("max_results", resolved_max_results)

        return _search_images(
            query=query,
            max_results=_coerce_max_results(resolved_max_results),
            size=size,
            color=color,
            type_image=type_image,
            layout=layout,
            license_image=license_image,
        )

    results = await asyncio.to_thread(search_with_config)

    if not results:
        return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "image_url": r.get("image", ""),
            "thumbnail_url": r.get("thumbnail", ""),
        }
        for r in results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
        "usage_hint": "Use the 'image_url' values as reference images in image generation. Download them first if needed.",
    }

    return json.dumps(output, indent=2, ensure_ascii=False)

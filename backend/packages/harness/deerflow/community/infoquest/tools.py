import asyncio
import logging

from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

from .infoquest_client import InfoQuestClient

logger = logging.getLogger(__name__)

readability_extractor = ReadabilityExtractor()

# config.example.yaml documents -1 as "no time filtering" for every option below.
_NO_TIME_FILTER = -1


def _coerce_seconds(value: object, option: str) -> int:
    """Normalize one of the documented crawl timeouts before handing it to the client.

    ``$VAR`` references in config.yaml resolve verbatim from the environment, so a
    configured ``timeout: $FETCH_TIMEOUT`` arrives as ``"10"``. The client compares each
    of these options with ``0``, which raises for a string, ``None`` or a mapping and
    takes the whole ``web_fetch``/``web_search``/``image_search`` call down with it.
    Only an integer, an integral float or an integer-form string is accepted: plain
    ``int()`` would silently truncate ``3.5`` and turn ``true`` into 1. Anything else
    warns and keeps the documented default instead.
    """
    seconds: int | None
    if isinstance(value, bool):
        seconds = None
    elif isinstance(value, int):
        seconds = value
    elif isinstance(value, float):
        seconds = int(value) if value.is_integer() else None
    elif isinstance(value, str):
        try:
            seconds = int(value.strip())
        except ValueError:
            seconds = None
    else:
        seconds = None

    if seconds is None:
        logger.warning("Invalid InfoQuest %s=%r; using default %s", option, value, _NO_TIME_FILTER)
        return _NO_TIME_FILTER
    return seconds


def _get_infoquest_client() -> InfoQuestClient:
    search_config = get_app_config().get_tool_config("web_search")
    search_time_range = _NO_TIME_FILTER
    if search_config is not None and "search_time_range" in search_config.model_extra:
        search_time_range = _coerce_seconds(search_config.model_extra.get("search_time_range"), "search_time_range")

    fetch_config = get_app_config().get_tool_config("web_fetch")
    fetch_time = _NO_TIME_FILTER
    if fetch_config is not None and "fetch_time" in fetch_config.model_extra:
        fetch_time = _coerce_seconds(fetch_config.model_extra.get("fetch_time"), "fetch_time")
    fetch_timeout = _NO_TIME_FILTER
    if fetch_config is not None and "timeout" in fetch_config.model_extra:
        fetch_timeout = _coerce_seconds(fetch_config.model_extra.get("timeout"), "timeout")
    navigation_timeout = _NO_TIME_FILTER
    if fetch_config is not None and "navigation_timeout" in fetch_config.model_extra:
        navigation_timeout = _coerce_seconds(fetch_config.model_extra.get("navigation_timeout"), "navigation_timeout")

    image_search_config = get_app_config().get_tool_config("image_search")
    image_search_time_range = _NO_TIME_FILTER
    if image_search_config is not None and "image_search_time_range" in image_search_config.model_extra:
        image_search_time_range = _coerce_seconds(image_search_config.model_extra.get("image_search_time_range"), "image_search_time_range")
    image_size = "i"
    if image_search_config is not None and "image_size" in image_search_config.model_extra:
        image_size = image_search_config.model_extra.get("image_size")

    return InfoQuestClient(
        search_time_range=search_time_range,
        fetch_timeout=fetch_timeout,
        fetch_navigation_timeout=navigation_timeout,
        fetch_time=fetch_time,
        image_search_time_range=image_search_time_range,
        image_size=image_size,
    )


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """

    client = _get_infoquest_client()
    return await client.web_search(query)


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    client = _get_infoquest_client()
    result = await client.fetch(url)
    if result.startswith("Error: "):
        return result
    article = await asyncio.to_thread(readability_extractor.extract_article, result, url=url)
    return article.to_markdown()[:4096]


@tool("image_search", parse_docstring=True)
async def image_search_tool(query: str) -> str:
    """Search for images online. Use this tool BEFORE image generation to find reference images for characters, portraits, objects, scenes, or any content requiring visual accuracy.

    **When to use:**
    - Before generating character/portrait images: search for similar poses, expressions, styles
    - Before generating specific objects/products: search for accurate visual references
    - Before generating scenes/locations: search for architectural or environmental references
    - Before generating fashion/clothing: search for style and detail references

    The returned image URLs can be used as reference images in image generation to significantly improve quality.

    Args:
        query: The query to search for images.
    """
    client = _get_infoquest_client()
    return await client.image_search(query)

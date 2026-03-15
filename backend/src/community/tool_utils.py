"""Shared utilities for community tool implementations."""

import json
import logging
from typing import Any

from src.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5
DEFAULT_CONTENT_LIMIT = 4096

WEB_FETCH_DOCSTRING = """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """


def get_tool_extra(tool_name: str, key: str, default: Any = None) -> Any:
    """Read a single extra field from the tool config.

    Args:
        tool_name: The tool name in config.yaml (e.g. "web_search").
        key: The extra field name (e.g. "api_key", "max_results").
        default: Fallback value when missing.

    Returns:
        The resolved value.
    """
    config = get_app_config().get_tool_config(tool_name)
    if config is not None and key in (config.model_extra or {}):
        return config.model_extra.get(key, default)
    return default


def format_search_results(results: list[dict[str, str]]) -> str:
    """Serialize a list of normalized search results to JSON."""
    return json.dumps(results, indent=2, ensure_ascii=False)


def format_tool_success(source: str, data: Any) -> str:
    """Return a normalized success payload for community tools."""
    return json.dumps(
        {
            "ok": True,
            "source": source,
            "data": data,
        },
        indent=2,
        ensure_ascii=False,
    )


def format_tool_error(source: str, message: str, error_type: str = "tool_error") -> str:
    """Return a normalized error payload for community tools."""
    return json.dumps(
        {
            "ok": False,
            "source": source,
            "error": {
                "type": error_type,
                "message": message,
            },
        },
        indent=2,
        ensure_ascii=False,
    )

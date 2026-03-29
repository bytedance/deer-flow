import json
from typing import Any

from langchain.tools import tool

from deerflow.config import get_app_config


DEFAULT_MAX_RESULTS = 5
DEFAULT_MAX_CHARACTERS = 4000
DEFAULT_SEARCH_TYPE = "auto"


def _get_exa_client() -> tuple[Any, dict[str, Any]]:
    config = get_app_config().get_tool_config("exa_search")

    api_key = None
    max_results = DEFAULT_MAX_RESULTS
    max_characters = DEFAULT_MAX_CHARACTERS
    search_type = DEFAULT_SEARCH_TYPE
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None

    if config is not None:
        if "api_key" in config.model_extra:
            api_key = config.model_extra.get("api_key")
        if "max_results" in config.model_extra:
            max_results = config.model_extra.get("max_results")
        if "max_characters" in config.model_extra:
            max_characters = config.model_extra.get("max_characters")
        if "search_type" in config.model_extra:
            search_type = config.model_extra.get("search_type")
        if "include_domains" in config.model_extra:
            include_domains = config.model_extra.get("include_domains")
        if "exclude_domains" in config.model_extra:
            exclude_domains = config.model_extra.get("exclude_domains")

    try:
        from exa_py import Exa
    except ImportError as err:
        raise ImportError("exa_search requires the 'exa-py' package. Install dependencies and restart DeerFlow.") from err

    client = Exa(api_key=api_key)
    options: dict[str, Any] = {
        "type": search_type,
        "num_results": max_results,
        "contents": {
            "highlights": {
                "max_characters": max_characters,
            }
        },
    }
    if include_domains:
        options["include_domains"] = include_domains
    if exclude_domains:
        options["exclude_domains"] = exclude_domains

    return client, options


@tool("exa_search", parse_docstring=True)
def exa_search_tool(query: str) -> str:
    """Search with Exa.

    Args:
        query: Search query text.
    """
    client, options = _get_exa_client()
    response = client.search(query, **options)

    normalized_results = []
    for result in getattr(response, "results", []):
        highlights = getattr(result, "highlights", None)
        if isinstance(highlights, list):
            snippet = "\n".join(highlights)
        else:
            snippet = getattr(result, "text", None) or getattr(result, "summary", None) or ""

        normalized_results.append(
            {
                "title": getattr(result, "title", ""),
                "url": getattr(result, "url", ""),
                "published_date": getattr(result, "published_date", None),
                "author": getattr(result, "author", None),
                "snippet": snippet,
            }
        )

    return json.dumps(normalized_results, indent=2, ensure_ascii=False)

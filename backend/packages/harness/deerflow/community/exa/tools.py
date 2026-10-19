import json
import logging

from exa_py import Exa
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5
DEFAULT_CONTENTS_MAX_CHARACTERS = 1000


def _coerce_positive_int(value: object, default: int, option: str) -> int:
    """Normalize a config value before handing it to the Exa SDK.

    ``$VAR`` references in config.yaml resolve to strings, and exa-py rejects a
    string ``num_results`` outright, so every search would fail. Only an integer
    or an integer-form string is accepted: ``int()`` would silently truncate a
    float such as an unquoted ``3.5`` and turn ``true`` into 1. Anything else
    (blank, non-numeric, fractional, boolean, zero or negative) warns and keeps
    the default instead.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        count = value
    elif isinstance(value, str) and value.strip().isdecimal():
        count = int(value.strip())
    else:
        count = 0
    if count <= 0:
        logger.warning("Invalid Exa %s=%r; using default %s", option, value, default)
        return default
    return count


def _get_exa_client(tool_name: str = "web_search") -> Exa:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return Exa(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = DEFAULT_MAX_RESULTS
        search_type = "auto"
        contents_max_characters = DEFAULT_CONTENTS_MAX_CHARACTERS
        if config is not None:
            max_results = _coerce_positive_int(config.model_extra.get("max_results", max_results), DEFAULT_MAX_RESULTS, "max_results")
            search_type = config.model_extra.get("search_type", search_type)
            contents_max_characters = _coerce_positive_int(
                config.model_extra.get("contents_max_characters", contents_max_characters),
                DEFAULT_CONTENTS_MAX_CHARACTERS,
                "contents_max_characters",
            )

        client = _get_exa_client()
        res = client.search(
            query,
            type=search_type,
            num_results=max_results,
            contents={"highlights": {"max_characters": contents_max_characters}},
        )

        normalized_results = [
            {
                "title": result.title or "",
                "url": result.url or "",
                "snippet": "\n".join(result.highlights) if result.highlights else "",
            }
            for result in res.results
        ]
        json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
        return json_results
    except Exception as e:
        return f"Error: {str(e)}"


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        client = _get_exa_client("web_fetch")
        res = client.get_contents([url], text={"max_characters": 4096})

        if res.results:
            result = res.results[0]
            title = result.title or "Untitled"
            text = result.text or ""
            return f"# {title}\n\n{text[:4096]}"
        else:
            return "Error: No results found"
    except Exception as e:
        return f"Error: {str(e)}"

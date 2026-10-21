"""
Web fetch tool powered by Unbrowse.

Unbrowse is a hosted service that turns websites into APIs for agents. This
provider calls its ``unbrowse.scrape`` tool, which returns a page as markdown:
over plain HTTP when that is enough, or through a cloud browser when the page
needs JavaScript to render. Calls go to Unbrowse's MCP endpoint as a single
JSON-RPC ``tools/call`` POST. An API key is required. Get one at
https://unbrowse.ai/app.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_UNBROWSE_MCP_URL = "https://unbrowse.ai/api/mcp"
_UNBROWSE_SCRAPE_TOOL = "unbrowse.scrape"
_UNBROWSE_TIMEOUT = 90
_UNBROWSE_FETCH_MAX_CHARS = 4096
_DEFAULT_RENDER = "auto"
_RENDER_MODES = ("auto", "never", "always")
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("UNBROWSE_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _resolve_render(value: object) -> str:
    """Return a supported render mode, falling back to the default with a warning."""
    if value is None:
        return _DEFAULT_RENDER
    render = str(value).strip().lower()
    if render in _RENDER_MODES:
        return render
    logger.warning("Ignoring unsupported Unbrowse render %r; using %r (supported: %s)", value, _DEFAULT_RENDER, ", ".join(_RENDER_MODES))
    return _DEFAULT_RENDER


def _missing_key_message(tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("Unbrowse API key is not set for '%s'. Set UNBROWSE_API_KEY in your environment or provide api_key in config.yaml. Get a key at https://unbrowse.ai/app", tool_name)
    return "UNBROWSE_API_KEY is not configured"


def _tool_result_text(result: dict) -> str:
    """Join the text blocks of an MCP tool result."""
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(block["text"] for block in content if isinstance(block, dict) and isinstance(block.get("text"), str))


def _call_unbrowse_tool(name: str, api_key: str, arguments: dict) -> tuple[dict | None, str | None]:
    """Call an Unbrowse MCP tool with one JSON-RPC ``tools/call`` request.

    Returns a ``(data, error)`` tuple: on success ``data`` is the tool's JSON
    payload and ``error`` is ``None``; on failure ``data`` is ``None`` and
    ``error`` is a message the caller can hand back to the model.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }

    try:
        with httpx.Client(timeout=_UNBROWSE_TIMEOUT) as client:
            response = client.post(_UNBROWSE_MCP_URL, headers=headers, json=request)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error("Unbrowse API returned HTTP %s: %s", e.response.status_code, (e.response.text or "")[:500])
        return None, f"Unbrowse API error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error("Unbrowse request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, str(e)[:500]

    if not isinstance(data, dict):
        logger.error("Unbrowse returned an unexpected payload type: %s", type(data).__name__)
        return None, "Unbrowse returned an unexpected response format"

    rpc_error = data.get("error")
    if rpc_error is not None:
        message = rpc_error.get("message") if isinstance(rpc_error, dict) else None
        message = str(message or rpc_error).strip()[:500]
        logger.error("Unbrowse %s failed: %s", name, message)
        return None, f"Unbrowse error: {message}"

    result = data.get("result")
    if not isinstance(result, dict):
        logger.error("Unbrowse returned an unexpected 'result' payload type: %s", type(result).__name__)
        return None, "Unbrowse returned an unexpected response format"

    text = _tool_result_text(result)
    if result.get("isError"):
        message = text.strip()[:500] or "tool call failed"
        logger.error("Unbrowse %s returned a tool error: %s", name, message)
        return None, f"Unbrowse error: {message}"

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured, None

    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        logger.error("Unbrowse %s returned non-JSON content", name)
        return None, "Unbrowse returned an unexpected response format"
    if not isinstance(payload, dict):
        logger.error("Unbrowse %s returned an unexpected content type: %s", name, type(payload).__name__)
        return None, "Unbrowse returned an unexpected response format"
    return payload, None


def _clip(value: object, limit: int) -> str:
    """Coerce a result field to text and truncate it. A limit of 0 means no truncation."""
    text = value if isinstance(value, str) else str(value)
    return text if limit <= 0 else text[:limit]


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
    api_key = _get_api_key("web_fetch")
    if not api_key:
        return f"Error: {_missing_key_message('web_fetch')}"

    config = get_app_config().get_tool_config("web_fetch")
    config_extra = (config.model_extra or {}) if config is not None else {}
    render = _resolve_render(config_extra.get("render"))

    arguments = {"url": url, "formats": ["markdown"], "render": render}
    data, error = _call_unbrowse_tool(_UNBROWSE_SCRAPE_TOOL, api_key, arguments)
    if error is not None:
        return f"Error: {error}"

    content = _clip(data.get("markdown") or "", _UNBROWSE_FETCH_MAX_CHARS)
    if not content:
        return "Error: No content found"

    metadata = data.get("metadata")
    title = (metadata.get("title") if isinstance(metadata, dict) else None) or "Untitled"
    return f"# {title}\n\n{content}"

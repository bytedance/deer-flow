import json
import os

import httpx
from langchain.tools import tool

from src.config import get_app_config


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    config = get_app_config().get_tool_config("web_search")

    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    if not api_key:
        api_key = os.environ.get("PERPLEXITY_API_KEY")

    model = "sonar-pro"
    if config is not None and "model" in config.model_extra:
        model = config.model_extra.get("model")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
    }

    response = httpx.post(
        "https://api.perplexity.ai/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    answer = data["choices"][0]["message"]["content"]
    citations = data.get("citations", [])

    result = {
        "answer": answer,
        "sources": [{"url": url} for url in citations],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)

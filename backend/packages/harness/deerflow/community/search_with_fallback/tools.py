"""Search tool with intelligent fallback based on language and domain.

This module provides search tools that automatically select the best provider
based on query characteristics (language, domain) and fall back to alternatives
when the primary provider fails.

Provider strengths:
- InfoQuest: Good for Chinese content, real-time search
- Firecrawl: Good for English content, markdown extraction
- Exa: Semantic search, good for technical/academic content
- Jina: Good for web page fetching and summarization
"""

import json
import logging
import re
from typing import Any

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5


def _is_chinese_query(query: str) -> bool:
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", query)
    return len(chinese_chars) > len(query) * 0.3


def _is_academic_query(query: str) -> bool:
    academic_keywords = ["research", "paper", "study", "journal", "arxiv", "pubmed", "academic", "scholar", "thesis", "dissertation", "peer-reviewed", "研究", "论文", "学术", "期刊", "文献"]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in academic_keywords)


def _search_with_infoquest(query: str, max_results: int) -> list[dict[str, Any]] | None:
    try:
        from deerflow.community.infoquest.infoquest_client import InfoQuestClient

        config = get_app_config().get_tool_config("web_search")
        api_key = None
        search_time_range = -1
        if config:
            api_key = config.model_extra.get("api_key")
            search_time_range = config.model_extra.get("search_time_range", -1)

        client = InfoQuestClient(api_key=api_key, search_time_range=search_time_range)
        result = client.web_search(query)
        if result and not result.startswith("Error"):
            return json.loads(result)
    except Exception as e:
        logger.warning(f"InfoQuest search failed: {e}")
    return None


def _search_with_firecrawl(query: str, max_results: int) -> list[dict[str, Any]] | None:
    try:
        from firecrawl import FirecrawlApp

        config = get_app_config().get_tool_config("firecrawl_web_search")
        api_key = None
        if config:
            api_key = config.model_extra.get("api_key")

        client = FirecrawlApp(api_key=api_key)
        result = client.search(query, limit=max_results)

        web_results = result.web or []
        return [
            {
                "title": getattr(item, "title", "") or "",
                "url": getattr(item, "url", "") or "",
                "snippet": getattr(item, "description", "") or "",
            }
            for item in web_results
        ]
    except Exception as e:
        logger.warning(f"Firecrawl search failed: {e}")
    return None


def _search_with_exa(query: str, max_results: int) -> list[dict[str, Any]] | None:
    try:
        from exa_py import Exa

        config = get_app_config().get_tool_config("exa_search")
        api_key = None
        if config:
            api_key = config.model_extra.get("api_key")

        client = Exa(api_key=api_key)
        response = client.search(
            query,
            num_results=max_results,
            type="auto",
            contents={"highlights": {"max_characters": 4000}},
        )

        results = []
        for result in getattr(response, "results", []):
            highlights = getattr(result, "highlights", None)
            snippet = "\n".join(highlights) if isinstance(highlights, list) else (getattr(result, "text", None) or "")
            results.append(
                {
                    "title": getattr(result, "title", ""),
                    "url": getattr(result, "url", ""),
                    "snippet": snippet,
                }
            )
        return results
    except Exception as e:
        logger.warning(f"Exa search failed: {e}")
    return None


def _search_with_jina(query: str) -> str | None:
    try:
        from deerflow.community.jina_ai.tools import web_fetch_tool

        search_url = f"https://s.jina.ai/{query}"
        result = web_fetch_tool.invoke({"url": search_url})
        if result and not result.startswith("Error"):
            return result
    except Exception as e:
        logger.warning(f"Jina search failed: {e}")
    return None


@tool("web_search_auto", parse_docstring=True)
def web_search_auto_tool(query: str) -> str:
    """Search the web with automatic provider selection and fallback.

    This tool intelligently selects the best search provider based on query
    characteristics and automatically falls back to alternatives if needed.

    - Chinese queries -> InfoQuest first
    - Academic queries -> Exa first
    - English queries -> Firecrawl first

    Args:
        query: Search query text.
    """
    config = get_app_config().get_tool_config("web_search_auto")
    max_results = DEFAULT_MAX_RESULTS
    if config and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", DEFAULT_MAX_RESULTS)

    is_chinese = _is_chinese_query(query)
    is_academic = _is_academic_query(query)

    if is_chinese:
        chain = [
            ("InfoQuest", lambda: _search_with_infoquest(query, max_results)),
            ("Firecrawl", lambda: _search_with_firecrawl(query, max_results)),
            ("Exa", lambda: _search_with_exa(query, max_results)),
            ("Jina", lambda: _search_with_jina(query)),
        ]
    elif is_academic:
        chain = [
            ("Exa", lambda: _search_with_exa(query, max_results)),
            ("Firecrawl", lambda: _search_with_firecrawl(query, max_results)),
            ("InfoQuest", lambda: _search_with_infoquest(query, max_results)),
            ("Jina", lambda: _search_with_jina(query)),
        ]
    else:
        chain = [
            ("Firecrawl", lambda: _search_with_firecrawl(query, max_results)),
            ("InfoQuest", lambda: _search_with_infoquest(query, max_results)),
            ("Exa", lambda: _search_with_exa(query, max_results)),
            ("Jina", lambda: _search_with_jina(query)),
        ]

    errors = []
    for provider_name, search_func in chain:
        logger.info(f"Trying search provider: {provider_name} for query: {query[:50]}...")
        try:
            result = search_func()
            if result:
                logger.info(f"Search succeeded with provider: {provider_name}")
                if isinstance(result, str):
                    return result
                if isinstance(result, list):
                    return json.dumps(result[:max_results], indent=2, ensure_ascii=False)
                return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            errors.append(f"{provider_name}: {str(e)}")
            continue

    return f"All search providers failed. Errors: {'; '.join(errors)}"


@tool("web_fetch_auto", parse_docstring=True)
def web_fetch_auto_tool(url: str) -> str:
    """Fetch web content with automatic provider selection and fallback.

    This tool tries multiple fetch providers in order and returns content
    from the first successful provider.

    Args:
        url: URL to fetch content from.
    """

    def fetch_infoquest():
        from deerflow.community.infoquest.tools import web_fetch_tool

        return web_fetch_tool.invoke({"url": url})

    def fetch_jina():
        from deerflow.community.jina_ai.tools import web_fetch_tool

        return web_fetch_tool.invoke({"url": url})

    def fetch_firecrawl():
        from firecrawl import FirecrawlApp

        config = get_app_config().get_tool_config("firecrawl_web_fetch")
        api_key = config.model_extra.get("api_key") if config else None
        client = FirecrawlApp(api_key=api_key)
        result = client.scrape(url, formats=["markdown"])
        content = result.markdown or ""
        title = result.metadata.title if result.metadata else "Untitled"
        return f"# {title}\n\n{content[:4096]}" if content else "Error: No content found"

    chain = [
        ("InfoQuest", fetch_infoquest),
        ("Jina", fetch_jina),
        ("Firecrawl", fetch_firecrawl),
    ]

    errors = []
    for provider_name, fetch_func in chain:
        logger.info(f"Trying fetch provider: {provider_name}")
        try:
            result = fetch_func()
            if result and not result.startswith("Error"):
                logger.info(f"Fetch succeeded with provider: {provider_name}")
                return result
        except Exception as e:
            errors.append(f"{provider_name}: {str(e)}")
            continue

    return f"All fetch providers failed. Errors: {'; '.join(errors)}"

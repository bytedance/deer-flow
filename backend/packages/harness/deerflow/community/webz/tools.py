"""Async adapter for the Webz.io News Search context endpoint."""

import asyncio
import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx
from langchain.tools import tool

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.config import get_app_config


def _options() -> dict:
    config = get_app_config().get_tool_config("web_search")
    return dict(config.model_extra or {}) if config else {}


def _count(value: object) -> int:
    try:
        return max(1, min(100, int(value))) if not isinstance(value, bool) else 5
    except (TypeError, ValueError, OverflowError):
        return 5


def _normalize(payload: object, count: int) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Invalid results")
    results = []
    for item in payload["results"][:count]:
        if not isinstance(item, dict) or not isinstance(item.get("article"), dict):
            raise ValueError("Invalid article")
        article = item["article"]
        chunk, metadata = item.get("chunk", {}), item.get("metadata", {})
        if not isinstance(chunk, dict) or not isinstance(metadata, dict):
            raise ValueError("Invalid metadata")
        result = {
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "content": chunk.get("text") or article.get("summary") or "",
            "published_at": article.get("published_at", ""),
        }
        if any(not isinstance(value, str) for value in result.values()):
            raise ValueError("Invalid article fields")
        results.append({**result, "source": metadata})
    return results


@tool("web_search", parse_docstring=True)
async def web_search_tool(
    query: str,
    max_results: int = 5,
    time_range: SearchTimeRange | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    language: list[str] | None = None,
    country: list[str] | None = None,
    source: list[str] | None = None,
    sentiment: list[Literal["positive", "negative", "neutral"]] | None = None,
    category: list[str] | None = None,
) -> str:
    """Search recent news with Webz.io and return matching passages and source metadata.

    This provider searches news, not the general web. Date filters do not extend
    the provider's available news coverage.

    Args:
        query: News search query, at most 750 characters and 100 words.
        max_results: Maximum results, clamped to 1-100; configuration can override it.
        time_range: Optional recency window: day, week, month, or year (UTC).
        published_from: Inclusive lower publication date in YYYY-MM-DD; overrides time_range.
        published_to: Inclusive upper publication date in YYYY-MM-DD.
        language: Optional language names, for example ["english"].
        country: Optional country codes, for example ["US"].
        source: Optional source domains, for example ["cnn.com"].
        sentiment: Optional positive, negative, or neutral sentiments.
        category: Optional news categories.

    Returns:
        JSON containing query, total_results and results, or an error.
    """
    query = query.strip()
    if not query or len(query) > 750 or len(query.split()) > 100:
        return json.dumps({"error": "Webz query must contain 1-750 characters and at most 100 words"})
    if published_from is None and time_range:
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[time_range]
        published_from = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    try:
        for value in (published_from, published_to):
            if value is not None and date.fromisoformat(value).isoformat() != value:
                raise ValueError("Non-canonical date")
        if published_from and published_to and published_from > published_to:
            raise ValueError("Reversed dates")
    except ValueError:
        return json.dumps({"error": "Webz dates must use YYYY-MM-DD with published_from <= published_to"})

    # Lazy configuration resolution can read files; keep it off the event loop.
    options = await asyncio.to_thread(_options)
    key = options.get("api_key")
    key = key.strip() if isinstance(key, str) else ""
    key = key or os.getenv("WEBZ_API_KEY", "").strip()
    if not key:
        return json.dumps({"error": "Webz API key is missing; configure api_key or WEBZ_API_KEY"})
    count = _count(options.get("max_results", max_results))
    body = {"query": query, "k": count}
    filters = {
        name: value
        for name, value in {
            "published_from": published_from,
            "published_to": published_to,
            "language": language,
            "country": country,
            "domain": source,
            "sentiment": sentiment,
            "category": category,
        }.items()
        if value is not None
    }
    if filters:
        body["filters"] = filters
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.post(
                "https://api.webz.io/api/news/context",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                json=body,
            )
            response.raise_for_status()
            results = _normalize(response.json(), count)
    except httpx.HTTPStatusError as exc:
        return json.dumps({"error": f"Webz request failed (HTTP {exc.response.status_code})"})
    except httpx.TimeoutException:
        return json.dumps({"error": "Webz request timed out"})
    except httpx.RequestError:
        return json.dumps({"error": "Webz request failed"})
    except ValueError:
        return json.dumps({"error": "Webz returned an unexpected response"})
    return json.dumps({"query": query, "total_results": len(results), "results": results}, ensure_ascii=False)

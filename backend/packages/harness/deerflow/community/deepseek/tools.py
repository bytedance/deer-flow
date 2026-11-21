"""DeepSeek server-side web search exposed as a DeerFlow search provider."""

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deerflow.agents.middlewares.pii_redaction_middleware import redact_text_excerpts
from deerflow.community.provider_credentials import resolve_api_key
from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.runtime.cancellation import drained_async_context

logger = logging.getLogger(__name__)
_ENDPOINT = "https://api.deepseek.com/chat/completions"
_DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS = 50


class _Options(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    model: str = Field(default="deepseek-flash", min_length=1)
    thinking: bool = False
    timeout_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    max_tokens: int = Field(default=8192, gt=0)

    @field_validator("timeout_seconds", "max_tokens", mode="before")
    @classmethod
    def reject_boolean_limits(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Search limits must be numeric")
        return value


def _objects(value: object, path: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        logger.error(
            "DeepSeek returned malformed %s container of type %s",
            path,
            type(value).__name__,
        )
        raise ValueError
    objects = [item for item in value if isinstance(item, dict)]
    if value and not objects:
        logger.error(
            "DeepSeek returned %s with no object entries (type %s)",
            path,
            type(value[0]).__name__,
        )
        raise ValueError
    return objects


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _normalize(data: object, query: str, max_results: int, pii_config: PiiRedactionConfig) -> dict[str, Any]:
    if not isinstance(data, dict):
        logger.error(
            "DeepSeek returned malformed response container of type %s",
            type(data).__name__,
        )
        raise ValueError
    # DeepSeek 可能在 HTTP 200 响应体中报告生成失败。
    if data.get("error") is not None:
        return {"error": "DeepSeek search generation failed", "query": query}
    choices = _objects(data.get("choices"), "choices")
    message = choices[0].get("message") if choices else None
    if not isinstance(message, dict):
        logger.error(
            "DeepSeek returned malformed choices[0].message container of type %s",
            type(message).__name__,
        )
        raise ValueError
    finish_reason = choices[0].get("finish_reason")
    if finish_reason not in {"stop", "length"}:
        return {"error": "DeepSeek search did not complete", "query": query}

    sources: list[dict[str, Any]] = []
    search_failed = False
    for step in _objects(message.get("server_tool_calls"), "server_tool_calls"):
        for call in _objects(step.get("calls"), "server_tool_calls[].calls"):
            rows = _objects(call.get("sources"), "server_tool_calls[].calls[].sources")
            page = call.get("page")
            if page is not None and not isinstance(page, dict):
                logger.error("DeepSeek returned malformed server_tool_calls[].calls[].page container of type %s", type(page).__name__)
                raise ValueError
            if call.get("status") == "completed":
                sources.extend(rows)
                if page is not None:
                    sources.append(page)
            elif call.get("status") == "failed":
                search_failed = True

    # 引用可能指向深度搜索中打开、但未出现在搜索列表中的网页。
    answer = _text(message.get("content"))
    cited_urls: set[str] = set()
    spans_by_url: dict[str, dict[tuple[int, int], None]] = {}
    for annotation in _objects(message.get("annotations"), "annotations"):
        if annotation.get("type") != "url_citation":
            continue
        citation = annotation.get("url_citation")
        if not isinstance(citation, dict):
            logger.error(
                "DeepSeek returned malformed annotations[].url_citation container of type %s",
                type(citation).__name__,
            )
            raise ValueError
        sources.append(citation)
        url = safe_public_result_url(citation.get("url"))
        cited_urls.add(url)
        start, end = citation.get("start_index"), citation.get("end_index")
        if not url or type(start) is not int or type(end) is not int:
            continue
        if not 0 <= start < end <= len(answer):
            continue
        spans_by_url.setdefault(url, {})[start, end] = None

    results_by_url: dict[str, dict[str, Any]] = {}
    for source in sources:
        url = safe_public_result_url(source.get("url"))
        if not url:
            continue
        result = results_by_url.setdefault(url, {"title": "", "url": url, "snippet": ""})
        for field in ("title", "snippet"):
            if not result[field]:
                result[field] = _text(source.get(field))
    results = list(results_by_url.values())
    if not results:
        if finish_reason == "length":
            return {"error": "DeepSeek search reached max_tokens before returning sources", "query": query}
        return {
            "error": "DeepSeek web search failed" if search_failed else "No results found",
            "query": query,
        }
    # 优先保留回答实际引用的来源，同时保留搜索结果提供的摘要。
    results.sort(key=lambda result: result["url"] not in cited_urls)
    results = results[:max_results]
    output = {
        "query": query,
        "total_results": len(results),
        "results": results,
        "answer": answer,
        "truncated": finish_reason == "length",
    }
    retained_spans = sorted({span for result in results for span in spans_by_url.get(result["url"], {})})
    if retained_spans:
        source_ids_by_span: dict[tuple[int, int], list[int]] = {span: [] for span in retained_spans}
        for source_id, result in enumerate(results, start=1):
            result["source_id"] = source_id
            for span in spans_by_url.get(result["url"], {}):
                source_ids_by_span[span].append(source_id)
        excerpts = redact_text_excerpts(answer, retained_spans, pii_config)
        output["citations"] = [{"excerpt": excerpt, "source_ids": source_ids_by_span[span]} for span, excerpt in zip(retained_spans, excerpts, strict=True)]
    return output


def _prepare() -> tuple[dict[str, Any], httpx.AsyncClient | None, str | None, PiiRedactionConfig]:
    app_config = get_app_config()
    config = app_config.get_tool_config("web_search")
    extras = dict(config.model_extra or {}) if config is not None else {}
    api_key = resolve_api_key(extras.get("api_key")) or resolve_api_key(os.getenv("DEEPSEEK_API_KEY"))
    if not api_key:
        return extras, None, "DEEPSEEK_API_KEY is not configured", app_config.pii_redaction
    # 配置读取与 TLS 初始化统一放到工作线程。
    client = httpx.AsyncClient(headers={"Authorization": f"Bearer {api_key}"})
    return extras, client, None, app_config.pii_redaction


async def _close_prepared_client(preparation: asyncio.Task) -> None:
    try:
        _, client, _, _ = await preparation
        if client is not None:
            await client.aclose()
    except Exception as exc:
        logger.error("DeepSeek search initialization cleanup failed (%s)", type(exc).__name__)


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int = _DEFAULT_MAX_RESULTS) -> str:
    """Search the web using DeepSeek and return an answer with source links.

    Returns JSON with an answer and results containing title, url, and snippet.
    When citations are available, results also have source_id values, and each
    citations entry pairs an excerpt with source_ids referring to those results.
    Resolve source_ids to result titles and URLs when writing Markdown citations.

    Args:
        query: Search keywords or a research question describing what to find.
        max_results: Maximum number of source links to return. Default is 5.
    """
    query = query.strip()
    if not query:
        return json.dumps(
            {"error": "Search query must not be empty", "query": query},
            ensure_ascii=False,
        )
    preparation = asyncio.create_task(asyncio.to_thread(_prepare))
    try:
        extras, client, error, pii_config = await asyncio.shield(preparation)
    except asyncio.CancelledError:
        # 工作线程仍会创建客户端。独立清理任务持有资源，重复取消时也先等它关闭。
        cleanup = asyncio.create_task(_close_prepared_client(preparation))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        raise
    except Exception as exc:
        logger.error("DeepSeek search initialization failed (%s)", type(exc).__name__)
        return json.dumps({"error": "DeepSeek search initialization failed", "query": query}, ensure_ascii=False)
    if error:
        return json.dumps({"error": error, "query": query}, ensure_ascii=False)
    assert client is not None
    async with drained_async_context(client):
        try:
            options = _Options.model_validate(extras)
        except ValidationError:
            logger.error("Invalid DeepSeek search tool configuration")
            return json.dumps(
                {"error": "Invalid DeepSeek search tool configuration", "query": query},
                ensure_ascii=False,
            )
        max_results = min(
            coerce_max_results(
                extras.get("max_results", max_results),
                provider="DeepSeek",
                logger=logger,
            ),
            _MAX_RESULTS,
        )
        payload = {
            "model": options.model,
            "thinking": {"type": "enabled" if options.thinking else "disabled"},
            "tools": [{"type": "deepseek_web_search"}],
            "messages": [
                {
                    "role": "system",
                    "content": "Search the web for the user's query and answer using retrieved sources. Cite your sources.",
                },
                {"role": "user", "content": query},
            ],
            "max_tokens": options.max_tokens,
            "stream": False,
        }
        try:
            async with asyncio.timeout(options.timeout_seconds):
                response = await client.post(_ENDPOINT, json=payload, timeout=options.timeout_seconds)
                response.raise_for_status()
                result = _normalize(response.json(), query, max_results, pii_config)
        except httpx.HTTPStatusError as exc:
            logger.error("DeepSeek search returned HTTP %s", exc.response.status_code)
            result = {
                "error": f"DeepSeek search API error: HTTP {exc.response.status_code}",
                "query": query,
            }
        except (httpx.TimeoutException, TimeoutError):
            result = {"error": "DeepSeek search timed out", "query": query}
        except httpx.HTTPError as exc:
            logger.error("DeepSeek search request failed (%s)", type(exc).__name__)
            result = {"error": "DeepSeek search request failed", "query": query}
        except (ValueError, TypeError):
            logger.error("DeepSeek search returned an invalid response format")
            result = {
                "error": "DeepSeek returned an unexpected response format",
                "query": query,
            }
    return json.dumps(result, ensure_ascii=False)

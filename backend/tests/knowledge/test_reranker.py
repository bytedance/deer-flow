"""Tests for the DashScope qwen3-rerank client.

qwen3-rerank uses the **flat** compatible-api contract (verified against the
Aliyun docs): ``query`` / ``documents`` / ``top_n`` / ``instruct`` sit next to
``model`` — no ``input``/``parameters`` wrapper — and the response carries
``results`` at the top level (no ``output`` envelope, no document bodies).
"""

from __future__ import annotations

import json

import httpx
import pytest

from deerflow.knowledge.reranker import DashScopeReranker, RerankerAuthError, RerankerError


def _transport(recorded: list[httpx.Request], handler_fn) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler_fn(request)

    return httpx.MockTransport(handler)


def _reranker(client: httpx.AsyncClient, **kwargs) -> DashScopeReranker:
    kwargs.setdefault("retry_backoff_seconds", 0.001)
    return DashScopeReranker(model="qwen3-rerank", api_key="test-key", client=client, **kwargs)


@pytest.mark.asyncio
async def test_rerank_returns_index_score_pairs_sorted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "results": [{"index": 2, "relevance_score": 0.93}, {"index": 0, "relevance_score": 0.41}],
                "model": "qwen3-rerank",
                "usage": {"total_tokens": 79},
            },
        )

    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_transport(recorded, handler))

    results = await _reranker(client).rerank("什么是文本排序模型", ["doc-a", "doc-b", "doc-c"], top_n=2)

    assert results == [(2, 0.93), (0, 0.41)]
    assert len(recorded) == 1
    request = recorded[0]
    assert request.url.path == "/compatible-api/v1/reranks"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    # Flat contract: no input/parameters wrapper.
    assert body == {
        "model": "qwen3-rerank",
        "query": "什么是文本排序模型",
        "documents": ["doc-a", "doc-b", "doc-c"],
        "top_n": 2,
        "instruct": "Given a web search query, retrieve relevant passages that answer the query.",
    }


@pytest.mark.asyncio
async def test_rerank_empty_documents_returns_empty():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    assert await _reranker(client).rerank("q", [], top_n=5) == []


@pytest.mark.asyncio
async def test_rerank_auth_error_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"code": "InvalidApiKey", "message": "Invalid API-key provided."})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RerankerAuthError):
        await _reranker(client, max_retries=3).rerank("q", ["d"], top_n=1)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_rerank_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"code": "InternalError", "message": "boom"})
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    results = await _reranker(client, max_retries=2).rerank("q", ["d"], top_n=1)
    assert calls["n"] == 2
    assert results == [(0, 0.5)]


@pytest.mark.asyncio
async def test_rerank_raises_after_retries_exhausted():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(429, json={"code": "Throttling", "message": "slow down"})))
    with pytest.raises(RerankerError, match="429|Throttling"):
        await _reranker(client, max_retries=2).rerank("q", ["d"], top_n=1)


@pytest.mark.asyncio
async def test_rerank_business_error_code_in_200_body():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"code": "InvalidApiKey", "message": "Invalid API-key provided."})))
    with pytest.raises(RerankerAuthError):
        await _reranker(client).rerank("q", ["d"], top_n=1)


@pytest.mark.asyncio
async def test_rerank_missing_api_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_RERANK_API_KEY", raising=False)
    reranker = DashScopeReranker(model="qwen3-rerank", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200))))
    with pytest.raises(RerankerAuthError, match="DASHSCOPE_RERANK_API_KEY"):
        await reranker.rerank("q", ["d"], top_n=1)

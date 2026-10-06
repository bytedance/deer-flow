"""Generic OpenAI-compatible rerank client (spec 2026-09-14 §4.1, shape from §8.4).

The contract is the one vLLM implements (Apache-2.0 source): the request is
``{model, query, documents}`` plus an optional ``top_n`` and deliberately carries **no
``instruct``**; the response is ``{results: [{index, relevance_score, document}], usage}``,
which parses exactly like the DashScope one (we read ``index`` / ``relevance_score``).
"""

from __future__ import annotations

import json

import httpx
import pytest

from deerflow.knowledge.reranker import RerankerAuthError, RerankerError
from deerflow.knowledge.reranker_generic import GenericReranker

BASE_URL = "http://localhost:8000"


def _client(recorded: list[httpx.Request], handler) -> httpx.AsyncClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


async def test_sends_the_generic_shape_and_parses_the_response():
    recorded: list[httpx.Request] = []
    body = {
        "results": [
            {"index": 0, "relevance_score": 0.2, "document": {"text": "a"}},
            {"index": 1, "relevance_score": 0.9, "document": {"text": "b"}},
        ],
        "usage": {"total_tokens": 12},
    }
    reranker = GenericReranker(
        model="bge-reranker",
        base_url=BASE_URL,
        api_key="sk-rerank",
        client=_client(recorded, lambda _request: httpx.Response(200, json=body)),
    )

    pairs = await reranker.rerank("q", ["a", "b"], top_n=2)

    request = recorded[0]
    assert request.url.path == "/rerank"
    assert request.headers["authorization"] == "Bearer sk-rerank"
    sent = json.loads(request.content)
    assert sent == {
        "model": "bge-reranker",
        "query": "q",
        "documents": ["a", "b"],
        "top_n": 2,
    }
    assert "instruct" not in sent
    # Best first, regardless of the order the server returned.
    assert pairs == [(1, 0.9), (0, 0.2)]


async def test_caps_top_n_at_the_document_count():
    recorded: list[httpx.Request] = []
    reranker = GenericReranker(
        model="m",
        base_url=BASE_URL,
        api_key="sk-test",
        client=_client(recorded, lambda _request: httpx.Response(200, json={"results": []})),
    )

    await reranker.rerank("q", ["only"], top_n=5)

    assert json.loads(recorded[0].content)["top_n"] == 1


async def test_empty_documents_never_hit_the_network():
    recorded: list[httpx.Request] = []
    reranker = GenericReranker(
        model="m",
        base_url=BASE_URL,
        api_key="sk-test",
        client=_client(recorded, lambda _request: httpx.Response(500)),
    )

    assert await reranker.rerank("q", []) == []
    assert recorded == []


async def test_retries_a_transient_failure_then_succeeds():
    recorded: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        if len(recorded) == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

    reranker = GenericReranker(
        model="m",
        base_url=BASE_URL,
        api_key="sk-test",
        retry_backoff_seconds=0.0,
        client=_client(recorded, handler),
    )

    assert await reranker.rerank("q", ["a"]) == [(0, 0.5)]
    assert len(recorded) == 2


async def test_auth_failure_is_not_retried_and_is_classified():
    recorded: list[httpx.Request] = []
    reranker = GenericReranker(
        model="m",
        base_url=BASE_URL,
        api_key="sk-test",
        retry_backoff_seconds=0.0,
        client=_client(recorded, lambda _request: httpx.Response(401, json={"error": "nope"})),
    )

    with pytest.raises(RerankerAuthError):
        await reranker.rerank("q", ["a"])
    assert len(recorded) == 1


async def test_exhausted_retries_raise_a_reranker_error():
    recorded: list[httpx.Request] = []
    reranker = GenericReranker(
        model="m",
        base_url=BASE_URL,
        api_key="sk-test",
        max_retries=2,
        retry_backoff_seconds=0.0,
        client=_client(recorded, lambda _request: httpx.Response(429, json={"error": "slow"})),
    )

    with pytest.raises(RerankerError):
        await reranker.rerank("q", ["a"])
    assert len(recorded) == 2


def test_the_endpoint_is_required():
    """A generic provider has no default address to fall back to."""
    with pytest.raises(TypeError):
        GenericReranker(model="m")


def test_the_factory_refuses_a_generic_provider_without_an_address():
    """Where the *deployment* refusal lives (spec 2026-09-17 alignment §3 D1).

    The class above only refuses a missing kwarg; this is the refusal an admin actually meets,
    and it has to arrive as `RagConfigurationError` so the gateway's one handler can answer 400
    (it used to be a bare `ValueError`: a 500 on the recall-test route, a wrapped tool error in
    chat, and the reason visible only in the server log).
    """
    from deerflow.config.app_config import RagConfig
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.reranker_factory import build_reranker

    rag = RagConfig(rerank_provider="generic-rerank")
    assert rag.rerank_base_url is None

    with pytest.raises(RagConfigurationError, match="rerank_base_url") as caught:
        build_reranker(rag=rag)

    # Callers that already catch `ValueError` keep working — the new type is a subclass.
    assert isinstance(caught.value, ValueError)


def test_the_factory_refuses_dashscope_without_an_address_too():
    """Spec 2026-09-25 rag-endpoint-unlock D1 乙: no built-in endpoint fallback any more —
    the address is required whatever the provider (the old message promised one)."""
    from deerflow.config.app_config import RagConfig
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.reranker_factory import build_reranker

    rag = RagConfig(rerank_provider="dashscope", rerank_base_url=None)
    with pytest.raises(RagConfigurationError, match="rerank_base_url") as caught:
        build_reranker(rag=rag)
    assert "built-in endpoint" not in str(caught.value)


@pytest.mark.asyncio
async def test_rerank_accepts_an_ecosystem_base_with_v1():
    """Jina 惯例：base 自带 /v1 ⇒ 结果与今天逐字相同（spec 2026-09-26 rag-endpoint-dedup）。"""
    recorded: list[httpx.Request] = []
    body = {"results": [{"index": 0, "relevance_score": 0.9}]}
    reranker = GenericReranker(
        model="bge-reranker",
        base_url=f"{BASE_URL}/v1",
        api_key="sk-rerank",
        client=_client(recorded, lambda _request: httpx.Response(200, json=body)),
    )
    await reranker.rerank("q", ["a"], top_n=1)

    assert str(recorded[0].url) == f"{BASE_URL}/v1/rerank"


@pytest.mark.asyncio
async def test_rerank_accepts_a_whole_endpoint():
    """整端点形态（照文档把 /rerank 也填上）不再被拼成 /rerank/rerank。"""
    recorded: list[httpx.Request] = []
    body = {"results": [{"index": 0, "relevance_score": 0.9}]}
    reranker = GenericReranker(
        model="bge-reranker",
        base_url=f"{BASE_URL}/rerank",
        api_key="sk-rerank",
        client=_client(recorded, lambda _request: httpx.Response(200, json=body)),
    )
    await reranker.rerank("q", ["a"], top_n=1)

    assert str(recorded[0].url) == f"{BASE_URL}/rerank"


def test_the_factory_refuses_a_missing_rerank_model():
    """A-1 (spec 2026-09-30 D1): the address is present, the model name is not — an undeclared
    model is refused at the construction point instead of silently using a vendor pick."""
    from deerflow.config.app_config import RagConfig
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.reranker_factory import build_reranker

    rag = RagConfig(rerank_provider="generic-rerank", rerank_base_url="http://127.0.0.1:8126").model_copy(update={"rerank_model": None})
    assert rag.rerank_model is None

    with pytest.raises(RagConfigurationError, match="rerank_model") as caught:
        build_reranker(rag=rag)

    assert isinstance(caught.value, ValueError)

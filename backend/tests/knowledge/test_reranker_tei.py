"""TEI rerank client (spec 2026-09-24 §4.3, D3 甲).

Contract — pinned from the upstream source (``huggingface/text-embeddings-inference``):
``POST /rerank`` with ``{"query", "texts", "raw_scores"}`` answers a **bare JSON array**
``[{"index", "score"}, ...]``. There is no ``model`` field (TEI serves exactly one model per
instance — the same rule :class:`~deerflow_knowledge.sparse.TEISparseEncoder` states) and no
``top_n`` (the service has none, so the cap is applied locally); the response is not wrapped in
a ``results`` envelope the way the Cohere/Jina shape is, which is why this is its own allowlist
row rather than a branch inside the generic client.
"""

from __future__ import annotations

import json

import httpx
import pytest
from deerflow_knowledge.reranker import RerankerAuthError, RerankerError
from deerflow_knowledge.reranker_tei import TEIReranker

BASE_URL = "http://localhost:8080"


def _client(recorded: list[httpx.Request], handler) -> httpx.AsyncClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _ok(rows: list[dict]):
    return lambda _request: httpx.Response(200, json=rows)


async def test_sends_the_tei_shape_and_parses_the_bare_array():
    recorded: list[httpx.Request] = []
    reranker = TEIReranker(
        base_url=BASE_URL,
        api_key="sk-tei",
        client=_client(recorded, _ok([{"index": 1, "score": 0.2}, {"index": 0, "score": 0.9}])),
    )

    pairs = await reranker.rerank("q", ["a", "b"], top_n=2)

    request = recorded[0]
    assert request.url.path == "/rerank"
    assert request.headers["authorization"] == "Bearer sk-tei"
    sent = json.loads(request.content)
    assert sent == {"query": "q", "texts": ["a", "b"], "raw_scores": False}
    # None of the other shape's fields: TEI would answer 422 for `model`/`top_n`, and
    # `documents` is the Cohere/Jina spelling.
    assert "model" not in sent and "top_n" not in sent and "documents" not in sent
    # Best first, whatever order the service answered in.
    assert pairs == [(0, 0.9), (1, 0.2)]


async def test_truncates_to_top_n_locally():
    """TEI has no ``top_n``, so the cap is ours — the vector path feeds the return value
    straight to the caller as the final result list."""
    recorded: list[httpx.Request] = []
    reranker = TEIReranker(
        base_url=BASE_URL,
        api_key="sk-tei",
        client=_client(recorded, _ok([{"index": index, "score": float(8 - index)} for index in range(8)])),
    )

    pairs = await reranker.rerank("q", [f"d{index}" for index in range(8)], top_n=3)

    assert json.loads(recorded[0].content)["texts"] == [f"d{index}" for index in range(8)]
    assert pairs == [(0, 8.0), (1, 7.0), (2, 6.0)]


async def test_empty_documents_never_hit_the_network():
    recorded: list[httpx.Request] = []
    reranker = TEIReranker(base_url=BASE_URL, client=_client(recorded, _ok([])))

    assert await reranker.rerank("q", [], top_n=5) == []
    assert recorded == []


@pytest.mark.parametrize("body", [{"results": []}, "not an array", [{"score": 0.5}], [{"index": 0}]])
async def test_a_malformed_response_is_an_error_never_an_empty_ranking(body):
    """非数组，或行里缺 ``index`` / ``score`` ⇒ ``RerankerError``（spec §4.3）。

    ``RerankerError`` is the type both retrieval paths degrade on, so a silently-empty
    ranking would look like "nothing matched" instead of a broken service.
    """
    reranker = TEIReranker(base_url=BASE_URL, client=_client([], _ok(body)))

    with pytest.raises(RerankerError) as caught:
        await reranker.rerank("q", ["a"])

    assert not isinstance(caught.value, RerankerAuthError)


async def test_a_rejected_key_is_an_auth_error_and_is_not_retried():
    recorded: list[httpx.Request] = []
    reranker = TEIReranker(base_url=BASE_URL, api_key="bad", client=_client(recorded, lambda _request: httpx.Response(401, json={"detail": "unauthorized"})))

    with pytest.raises(RerankerAuthError):
        await reranker.rerank("q", ["a"])

    assert len(recorded) == 1


async def test_retries_a_429_then_succeeds():
    recorded: list[httpx.Request] = []
    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, json={"detail": "busy"})
        return httpx.Response(200, json=[{"index": 0, "score": 0.5}])

    reranker = TEIReranker(base_url=BASE_URL, api_key="sk", max_retries=3, retry_backoff_seconds=0, client=_client(recorded, handler))

    assert await reranker.rerank("q", ["a"]) == [(0, 0.5)]
    assert len(recorded) == 2


async def test_an_exhausted_5xx_budget_raises_the_last_error():
    recorded: list[httpx.Request] = []
    reranker = TEIReranker(
        base_url=BASE_URL,
        api_key="sk",
        max_retries=2,
        retry_backoff_seconds=0,
        client=_client(recorded, lambda _request: httpx.Response(500, json={"detail": "boom"})),
    )

    with pytest.raises(RerankerError, match="500"):
        await reranker.rerank("q", ["a"])

    assert len(recorded) == 2


async def test_no_key_means_no_authorization_header(monkeypatch):
    """可选鉴权（spec §4.3）：TEI 端未配 key 时根本不装鉴权中间件，发一个空 Bearer 反被拒。

    ``configured_rag_secret`` 被钉住是必须的 —— 本机仓库根的 rag_config.json 真的存着
    一把重排 key（generic-rerank 那格），否则这条断言会随操作员的机器漂移。
    """
    import deerflow_knowledge.reranker_tei as tei_module

    monkeypatch.setattr(tei_module, "configured_rag_secret", lambda _name: None)
    monkeypatch.delenv("RAG_RERANK_API_KEY", raising=False)
    recorded: list[httpx.Request] = []
    reranker = TEIReranker(base_url=BASE_URL, client=_client(recorded, _ok([{"index": 0, "score": 1.0}])))

    assert await reranker.rerank("q", ["a"]) == [(0, 1.0)]
    assert "authorization" not in recorded[0].headers


# ── the allowlist row and the factory (spec §4.3 贯通面) ──────────────────


def test_the_factory_builds_a_tei_reranker_without_handing_it_a_model():
    """The factory hands ``model`` to every other rerank row; TEI must not receive it.

    ``TEIReranker`` deliberately has no ``model`` parameter (one instance serves one model),
    so a factory that passed it would raise ``TypeError`` before the first request. The
    allowlist row carries ``takes_model=False`` and the factory reads that — never the
    provider id (the same capability-over-name rule the endpoint lock follows).
    """
    from deerflow_knowledge.reranker_factory import build_reranker

    from deerflow.config.app_config import RagConfig

    rag = RagConfig(rerank_provider="tei-rerank", rerank_base_url=BASE_URL)

    assert isinstance(build_reranker(rag=rag), TEIReranker)


def test_the_factory_refuses_a_tei_provider_without_an_address():
    """The row ships no built-in address, so "forgot the endpoint" is a construction error.

    It must arrive as ``RagConfigurationError`` (a ``ValueError``) — the single type the
    gateway maps to a readable 400 — not as a ``TypeError`` from a missing kwarg.
    """
    from deerflow_knowledge.embedder import RagConfigurationError
    from deerflow_knowledge.reranker_factory import build_reranker

    from deerflow.config.app_config import RagConfig

    rag = RagConfig(rerank_provider="tei-rerank")
    assert rag.rerank_base_url is None

    with pytest.raises(RagConfigurationError, match="rerank_base_url") as caught:
        build_reranker(rag=rag)

    assert isinstance(caught.value, ValueError)

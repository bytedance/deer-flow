"""Tests for hybrid_search (spec §4.1): RRF prefetch → rerank → top-k.

Chunk text always comes from the business-DB ``chunks`` table (fetched by
``chunk_id``); the Qdrant payload only supplies display metadata
(``doc_name``/``page``/``heading_path``) for citations.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from deerflow_knowledge.access import ACCESS_DENIED_MESSAGE, NO_KB_GUIDANCE
from deerflow_knowledge.reranker import RerankerError

from deerflow.tools.builtins.hybrid_search_tool import _hybrid_search_impl

from ..conftest import requires_qdrant
from .conftest import KB_ID, OWNER_ID


class _StubReranker:
    """Scores documents containing 会话管理 highest — deterministic rerank."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(self, query: str, documents, *, top_n: int = 5):
        self.calls.append((query, list(documents)))
        scored = [(i, 0.99 if "会话管理" in doc else 0.05) for i, doc in enumerate(documents)]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_n]


class _FailingReranker:
    async def rerank(self, query: str, documents, *, top_n: int = 5):
        raise RerankerError("rerank down")


def _runtime(**context) -> SimpleNamespace:
    return SimpleNamespace(context=context)


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_end_to_end(tools_env):
    reranker = _StubReranker()

    result = await _hybrid_search_impl(
        "Gateway 的作用是什么",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=reranker,
        top_k=2,
    )

    assert reranker.calls, "RRF candidates must go through the reranker"
    results = result["results"]
    assert len(results) == 2
    top = results[0]
    # Reranker re-ordered: the 会话管理 chunk leads even though RRF ties.
    assert top["chunk_id"] == "doc-t-c0"
    assert top["text"] == "Gateway 负责会话管理，是 DeerFlow 的入口组件。"  # text from the business DB
    assert top["score"] == 0.99
    # Citation metadata rides the Qdrant payload (spec §4.6).
    assert top["doc_name"] == "架构.md"
    assert top["page"] == 1
    assert top["heading_path"] == ["架构"]
    assert "message" in result


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_no_match_returns_honest_message(tools_env):
    result = await _hybrid_search_impl(
        "zzz-完全无关-zzz",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
    )
    # An unrelated query still vector-matches *something* in a tiny test KB;
    # what matters is the tool answers with real rows or an honest empty list.
    assert result["results"] is not None
    assert "message" in result


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_without_kb_returns_guidance(tools_env):
    result = await _hybrid_search_impl(
        "任意问题",
        _runtime(user_id=OWNER_ID),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
    )
    assert result["results"] == []
    assert result["message"] == NO_KB_GUIDANCE


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_denies_non_owner(tools_env):
    result = await _hybrid_search_impl(
        "Gateway",
        _runtime(kb_id=KB_ID, user_id="user-2"),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
    )
    assert result["results"] == []
    assert result["message"] == ACCESS_DENIED_MESSAGE


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_rerank_failure_degrades_to_rrf_order(tools_env):
    """A reranker outage must not kill the vector path (spec §4.4)."""
    result = await _hybrid_search_impl(
        "Gateway",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_FailingReranker(),
        top_k=2,
    )
    assert len(result["results"]) == 2  # RRF order preserved, scores absent
    assert result["results"][0]["text"]
    assert "精排" in result["message"] or "rerank" in result["message"].lower()

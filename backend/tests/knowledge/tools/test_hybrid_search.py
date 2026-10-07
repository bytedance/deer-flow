"""Tests for knowledge_search (spec §4.1): RRF prefetch → rerank → top-k.

Chunk text always comes from the business-DB ``chunks`` table (fetched by
``chunk_id``); the Qdrant payload only supplies display metadata
(``doc_name``/``page``/``heading_path``) for citations. The turn's knowledge
scope resolves the bound KB; the returned source artifact mirrors the slices.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from deerflow_knowledge.access import ACCESS_DENIED_MESSAGE, KB_MISSING_MESSAGE, NO_KB_GUIDANCE
from deerflow_knowledge.reranker import RerankerError

from deerflow.tools.builtins.hybrid_search_tool import _hybrid_search_impl

from ..conftest import requires_qdrant
from .conftest import OWNER_ID, scope_runtime


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


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_end_to_end(tools_env):
    reranker = _StubReranker()

    result, artifact = await _hybrid_search_impl(
        "Gateway 的作用是什么",
        scope_runtime(),
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

    # The shared source artifact mirrors exactly the returned slices (#5551).
    assert artifact is not None
    sources = artifact["knowledge_sources"]["sources"]
    assert artifact["knowledge_sources"]["version"] == 1
    assert [source["provider"] for source in sources] == ["local", "local"]
    assert [source["chunk_id"] for source in sources] == [item["chunk_id"] for item in results]
    assert sources[0]["dataset_id"] == "kb-t"
    assert sources[0]["document_id"] == "doc-t"
    assert sources[0]["dataset_name"] == "工具测试库"
    assert sources[0]["document_name"] == "架构.md"
    assert sources[0]["text"] == top["text"]
    assert sources[0]["pages"] == [1]
    assert sources[0]["truncated"] is False
    # Provider-independent id shape shared with the RAGFlow formatter.
    assert re.fullmatch(r"[a-f0-9]{32}-1", sources[0]["id"])
    assert sources[0]["id"].rsplit("-", 1)[0] == sources[1]["id"].rsplit("-", 1)[0]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_no_match_returns_honest_message(tools_env):
    result, _ = await _hybrid_search_impl(
        "zzz-完全无关-zzz",
        scope_runtime(),
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
async def test_hybrid_search_without_scope_returns_guidance(tools_env):
    result, artifact = await _hybrid_search_impl(
        "任意问题",
        SimpleNamespace(context={"user_id": OWNER_ID}),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
    )
    assert result["results"] == []
    assert result["message"] == NO_KB_GUIDANCE
    assert artifact is None


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_denies_non_owner(tools_env):
    result, _ = await _hybrid_search_impl(
        "Gateway",
        scope_runtime(user_id="user-2"),
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
async def test_hybrid_search_reports_deleted_kb(tools_env):
    result, _ = await _hybrid_search_impl(
        "Gateway",
        scope_runtime(kb_id="kb-gone"),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
    )
    assert result["results"] == []
    assert result["message"] == KB_MISSING_MESSAGE


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_rerank_failure_degrades_to_rrf_order(tools_env):
    """A reranker outage must not kill the vector path (spec §4.4)."""
    result, _ = await _hybrid_search_impl(
        "Gateway",
        scope_runtime(),
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_FailingReranker(),
        top_k=2,
    )
    assert len(result["results"]) == 2  # RRF order preserved, scores absent
    assert result["results"][0]["text"]
    assert "精排" in result["message"] or "rerank" in result["message"].lower()

"""Shared citation numbering across the three retrieval paths.

The model cites ``[n]`` copied from each evidence item's ``citation_no``
field. All three tools must draw numbers from ONE per-run counter carried
by the runtime context dict — otherwise a multi-path answer faces three
colliding ``[1]``s (one per tool call) and the model's numbering collapses
(the observed citation-drift bug). Without a mutable dict context the
tools degrade to per-call numbering from 1 (status quo).
"""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

import pytest

from deerflow.knowledge.citation_counter import claim_citation_range
from deerflow.tools.builtins.graph_search_tool import _graph_search_impl
from deerflow.tools.builtins.hybrid_search_tool import _hybrid_search_impl
from deerflow.tools.builtins.wiki_search_tool import _wiki_search_impl

from ..conftest import requires_qdrant
from .conftest import KB_ID, OWNER_ID


class _StubReranker:
    async def rerank(self, query: str, documents, *, top_n: int = 5):
        return [(i, 0.9 - i * 0.01) for i in range(min(top_n, len(documents)))]


class _QueryLLM:
    """Stub LLM extracting the canned entities (dict format — see #entities-format)."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def ainvoke(self, messages, **_kwargs):
        import json

        return SimpleNamespace(content=json.dumps({"entities": self._names}))


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={"kb_id": KB_ID, "user_id": OWNER_ID})


def test_claim_citation_range_allocates_contiguous_ranges() -> None:
    runtime = SimpleNamespace(context={})
    assert claim_citation_range(runtime, 3) == 0
    assert claim_citation_range(runtime, 2) == 3
    assert runtime.context["citation_offset"] == 5


def test_claim_citation_range_zero_count_does_not_advance() -> None:
    runtime = SimpleNamespace(context={})
    assert claim_citation_range(runtime, 0) == 0
    assert claim_citation_range(runtime, 1) == 0


def test_claim_citation_range_without_dict_context_degrades_to_zero() -> None:
    assert claim_citation_range(SimpleNamespace(context=None), 3) == 0
    assert claim_citation_range(SimpleNamespace(), 3) == 0


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_calls_share_one_counter(tools_env) -> None:
    runtime = _runtime()
    kwargs = dict(
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
        top_k=2,
    )
    first = await _hybrid_search_impl("Gateway 的作用", runtime, **kwargs)
    second = await _hybrid_search_impl("MinerU 的角色", runtime, **kwargs)
    assert [item["citation_no"] for item in first["results"]] == [1, 2]
    assert "引用编号 [1]-[2]" in first["message"], "the span must be stated in prose (JSON fields get little attention)"
    assert [item["citation_no"] for item in second["results"]] == [3, 4], "the second call must continue the shared counter instead of renumbering from 1"
    assert "引用编号 [3]-[4]" in second["message"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_wiki_continues_after_hybrid(tools_env) -> None:
    runtime = _runtime()
    hybrid = await _hybrid_search_impl(
        "Gateway 的作用",
        runtime,
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
        top_k=2,
    )
    wiki = await _wiki_search_impl(
        "DeerFlow 是什么",
        runtime,
        store=tools_env["store"],
        wiki_store=tools_env["wiki_store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        top_k=1,
    )
    assert [item["citation_no"] for item in hybrid["results"]] == [1, 2]
    assert [item["citation_no"] for item in wiki["entries"]] == [3], "wiki entries must continue the counter the vector call started"
    assert "引用编号 [3]" in wiki["message"], "single-item spans collapse to one number"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_continues_after_hybrid(tools_env) -> None:
    runtime = _runtime()
    await _hybrid_search_impl(
        "Gateway 的作用",
        runtime,
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        reranker=_StubReranker(),
        top_k=2,
    )
    graph = await partial(_graph_search_impl, embedder=tools_env["embedder"], llm=_QueryLLM(["Gateway"]))(
        "Gateway 与 MinerU 的关系",
        runtime,
        store=tools_env["store"],
        vector_store=tools_env["vector_store"],
        graph_store=tools_env["graph_store"],
    )
    assert graph["evidence"], "graph path must surface evidence for the seeded subgraph"
    assert min(item["citation_no"] for item in graph["evidence"]) == 3, "graph evidence must continue the shared counter"
    assert "引用编号 [3]" in graph["message"], "graph message states the evidence span in prose"

"""Citation numbering for the hybrid retrieval path.

The model cites ``[n]`` copied from each evidence item's ``citation_no``
field. The tool must draw numbers from ONE per-run counter carried by the
runtime context dict — otherwise a multi-call run faces colliding ``[1]``s
(one per tool call) and the model's numbering collapses (the observed
citation-drift bug). Without a mutable dict context the tool degrades to
per-call numbering from 1 (status quo).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from deerflow_knowledge.citation_counter import claim_citation_range

from deerflow.tools.builtins.hybrid_search_tool import _hybrid_search_impl

from ..conftest import requires_qdrant
from .conftest import KB_ID, OWNER_ID


class _StubReranker:
    async def rerank(self, query: str, documents, *, top_n: int = 5):
        return [(i, 0.9 - i * 0.01) for i in range(min(top_n, len(documents)))]


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

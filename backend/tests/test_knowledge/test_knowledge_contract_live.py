"""Opt-in validation against real LightRAG /query/data evidence; no uploads."""

import os

import pytest

from deerflow.community.lightrag.client import LightRAGClient
from deerflow.community.lightrag.formatting import normalize_retrieval_result
from deerflow.knowledge import format_result, sources_from_messages


@pytest.mark.live
@pytest.mark.anyio
async def test_lightrag_live_evidence_contract() -> None:
    if os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1":
        pytest.skip("live knowledge checks are opt-in")
    base_url, query = os.getenv("LIGHTRAG_BASE_URL"), os.getenv("LIGHTRAG_EVIDENCE_QUERY")
    if not base_url or not query:
        pytest.skip("set LIGHTRAG_BASE_URL and LIGHTRAG_EVIDENCE_QUERY for an indexed workspace")
    result = await LightRAGClient(base_url=base_url, api_key=os.getenv("LIGHTRAG_API_KEY")).query_data(query, mode="mix", chunk_top_k=8)
    normalized = normalize_retrieval_result(result)
    assert any(hit.source for hit in normalized.hits), "Live query must retrieve attributable document text"
    text, artifact = format_result(normalized)
    sources = sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}])
    assert sources, "At least one real retrieved source must fit the default budget"
    for source in sources:
        assert any(hit.source and hit.source.title == source.title and source.excerpt.rstrip("…") in hit.content for hit in normalized.hits)
        assert source.provider == "lightrag"
        assert source.page is None  # /query/data does not supply page evidence

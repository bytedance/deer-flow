"""Synthetic LightRAG v1.5.7 graph evidence; no live service required."""

import json
import re
from pathlib import Path

import httpx
import pytest

from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-lightrag"))
    from deerflow_extension_lightrag import LightRAGProvider

    monkeypatch.setenv("LR_TEST_KEY", "synthetic-key")
    state = {
        "entities": [{"entity_name": "Cedar", "description": "A tree"}],
        "relationships": [{"src_id": "Cedar", "tgt_id": "Forest", "description": "grows in", "source_id": "chunk-1"}],
        "chunks": [{"chunk_id": "chunk-1", "file_path": "trees.md", "content": "Cedar grows in forests."}],
        "references": [],
    }
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.path == "/query/data"
        assert request.headers["X-API-Key"] == "synthetic-key"
        assert json.loads(request.content)["mode"] == "hybrid"
        return httpx.Response(200, json={"status": "success", "data": state})

    return LightRAGProvider({"base_url": "https://lr.example", "api_key_env": "LR_TEST_KEY", "user_ids": ["alice"]}, transport=httpx.MockTransport(handle)), calls, state


@pytest.mark.parametrize("field", ["timeout", "top_k"])
@pytest.mark.parametrize("value", [True, False])
def test_numeric_settings_reject_booleans(monkeypatch, field, value):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-lightrag"))
    from deerflow_extension_lightrag.provider import Settings

    with pytest.raises(ValueError, match="must not be a boolean"):
        Settings.model_validate({"base_url": "https://lr.example", "api_key_env": "LR_TEST_KEY", "user_ids": ["alice"], field: value})


@pytest.mark.asyncio
async def test_relationship_only_cites_joined_real_chunks(graph):
    provider, _, state = graph
    result = await provider.relations_search("Cedar", context=KnowledgeRequestContext("alice"))
    content, artifact = format_result(result)
    assert "Cedar — Forest" in content
    sources = sources_from_messages([{"type": "tool", "name": "entity_relations_search", "content": content, "artifact": artifact}])
    assert len(sources) == 1 and sources[0].excerpt == "Cedar grows in forests."
    assert sources[0].page is None and sources[0].url is None
    state["relationships"][0]["source_id"] = "missing"
    content, artifact = format_result(await provider.relations_search("Cedar", context=KnowledgeRequestContext("alice")))
    assert "Cedar — Forest" in content
    assert sources_from_messages([{"type": "tool", "content": content, "artifact": artifact}]) == []


@pytest.mark.asyncio
async def test_graph_rejects_scope_and_identity_before_network(graph):
    provider, calls, _ = graph
    with pytest.raises(PermissionError):
        await provider.relations_search("q", context=KnowledgeRequestContext("mallory"))
    for scope in ({"version": 1, "mode": "disabled"}, {"version": 1, "mode": "selected", "dataset_ids": ["kb"]}):
        with pytest.raises(ValueError):
            await provider.relations_search("q", context=KnowledgeRequestContext("alice", scope=scope))
    assert calls == []


@pytest.mark.asyncio
async def test_graph_does_not_infer_edges_or_cite_unrelated_chunks(graph):
    provider, _, state = graph
    state["relationships"] = []
    result = await provider.relations_search("Cedar", context=KnowledgeRequestContext("alice"))
    assert all(hit.source is None for hit in result.hits)
    assert all("one edge" not in hit.content for hit in result.hits)


@pytest.mark.asyncio
async def test_graph_redacts_secrets_and_rejects_malformed_relations(graph):
    provider, _, state = graph
    state["relationships"][0]["description"] = "synthetic-key"
    state["chunks"][0]["content"] = "synthetic-key evidence"
    result = await provider.relations_search("Cedar", context=KnowledgeRequestContext("alice"))
    assert "synthetic-key" not in result.model_dump_json()
    state["relationships"] = {"invalid": "shape"}
    with pytest.raises(ValueError):
        await provider.relations_search("Cedar", context=KnowledgeRequestContext("alice"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 500])
async def test_graph_upstream_failure_never_retries(graph, status):
    provider, _, _ = graph
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://other.invalid"}, text="synthetic-key")

    provider._transport = httpx.MockTransport(handle)
    with pytest.raises((PermissionError, RuntimeError)) as exc:
        await provider.relations_search("Cedar", context=KnowledgeRequestContext("alice"))
    assert len(requests) == 1
    assert "synthetic-key" not in str(exc.value)


@pytest.mark.asyncio
async def test_shared_chunk_is_emitted_once_with_each_edge_attributed_within_budget(graph):
    provider, _, state = graph
    state["chunks"][0]["content"] = "Shared evidence. " * 60
    state["relationships"] = [{"src_id": f"Node{i}", "tgt_id": "Forest", "description": "grows in", "source_id": "chunk-1<SEP>chunk-1"} for i in range(20)]
    result = await provider.relations_search("forest", context=KnowledgeRequestContext("alice"))
    assert len([hit for hit in result.hits if hit.source]) == 1
    content, artifact = format_result(result)
    for i in range(20):
        assert f"Node{i} — Forest" in content
    assert content.count("Evidence: result [1].") == 20
    assert len(artifact["knowledge_sources"]) == 1
    assert len(content) <= 8000
    short, short_artifact = format_result(result, max_total_chars=1100)
    if "Evidence: result [1]." in short:
        assert short_artifact["knowledge_sources"]


@pytest.mark.asyncio
async def test_edges_reference_only_their_own_chunks_and_reuse_shared_positions(graph):
    provider, _, state = graph
    state["chunks"].append({"chunk_id": "chunk-2", "file_path": "second.md", "content": "Second evidence."})
    state["relationships"] = [
        {"src_id": "A", "tgt_id": "B", "source_id": "chunk-1"},
        {"src_id": "B", "tgt_id": "C", "source_id": "chunk-2<SEP>chunk-1"},
        {"src_id": "C", "tgt_id": "D", "source_id": "missing"},
    ]
    result = await provider.relations_search("q", context=KnowledgeRequestContext("alice"))
    assert result.hits[1].content.startswith("Evidence: result [1].")
    assert result.hits[3].content.startswith("Evidence: result [3], result [1].")
    assert "No retrieved document evidence" in result.hits[4].content
    assert len([hit for hit in result.hits if hit.source]) == 2
    for budget in [0, 50, 200, 500, 8000]:
        content, _ = format_result(result, max_total_chars=budget)
        for ref in re.findall(r"result \[(\d+)\]", content):
            assert f"[{ref}] [citation:" in content


@pytest.mark.asyncio
async def test_hit_budget_distinguishes_omitted_evidence_from_missing_evidence(graph):
    provider, _, state = graph
    state["chunks"] = [{"chunk_id": f"c{i}", "file_path": "evidence.md", "content": f"Evidence {i}."} for i in range(50)]
    state["relationships"] = [{"src_id": f"A{i}", "tgt_id": "B", "source_id": f"c{i}"} for i in range(50)]
    result = await provider.relations_search("q", context=KnowledgeRequestContext("alice"))
    assert len(result.hits) == 100
    tail_edge = result.hits[-2].content
    assert "A49 — B" in tail_edge
    assert "Evidence omitted for this edge: bounded view." in tail_edge
    assert "No retrieved document evidence" not in tail_edge

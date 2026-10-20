"""Synthetic LightRAG v1.5.7 graph evidence; no live service required."""

import json
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

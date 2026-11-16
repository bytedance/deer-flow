"""Synthetic LightRAG v1.5.7 graph evidence; no live service required."""

import json
import re
from pathlib import Path

import httpx
import pytest

from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages

pytestmark = pytest.mark.bundled_extension


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
    assert result.hits[1].depends_on == [1]
    assert result.hits[3].depends_on == [3, 1]
    assert result.hits[4].depends_on == []
    assert "No retrieved document evidence" in result.hits[4].content
    assert len([hit for hit in result.hits if hit.source]) == 2
    content, _ = format_result(result)
    assert "Evidence: result [1].\nUpstream relation (one edge): A — B" in content
    assert "Evidence: result [3], result [1].\nUpstream relation (one edge): B — C" in content
    for budget in [0, 50, 200, 500, 8000]:
        content, _ = format_result(result, max_total_chars=budget)
        for ref in re.findall(r"result \[(\d+)\]", content):
            assert f"[{ref}] [citation:" in content


@pytest.mark.asyncio
async def test_relation_keeps_inline_references_on_hosts_without_dependency_metadata(graph, monkeypatch):
    from deerflow_extension_lightrag import provider as lightrag_provider

    monkeypatch.setattr(lightrag_provider, "_SUPPORTS_EVIDENCE_DEPENDENCIES", False)
    provider, _, _ = graph
    result = await provider.relations_search("forest", context=KnowledgeRequestContext("alice"))
    assert result.hits[1].content.startswith("Evidence: result [1].\n")
    assert "depends_on" not in result.hits[1].model_dump()


async def _call_relation_search(provider, budget=None, *, thread_data=None):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.tool_config import ToolConfig
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, ExtensionRegistry
    from deerflow.knowledge.tools import entity_relations_search_tool

    registry = ExtensionRegistry()
    with registry.attributed_to("lightrag-test:install"):
        registry.knowledge_provider("lightrag-relations", provider)
    name = "entity_relations_search"
    config = AppConfig(
        sandbox=SandboxConfig(use="example:Sandbox"),
        tools=[ToolConfig(name=name, group="knowledge", use=f"deerflow.knowledge.tools:{name}_tool", provider="lightrag-relations")],
    )

    class State(MessagesState, total=False):
        thread_data: dict

    builder = StateGraph(State, context_schema=dict)
    builder.add_node("tools", ToolNode([entity_relations_search_tool], awrap_tool_call=budget.awrap_tool_call if budget else None))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)

    result = await builder.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "relations", "name": name, "args": {"query": "forest"}}])], "thread_data": thread_data or {}},
        context={"app_config": config, "user_id": "alice", "agent_name": "researcher", EXTENSION_SNAPSHOT_CONTEXT_KEY: registry.build()},
    )
    return result["messages"][-1]


@pytest.mark.asyncio
async def test_agent_budget_preserves_only_relations_with_retained_evidence(graph):
    provider, calls, state = graph
    state["chunks"] = [{"chunk_id": f"c{i}", "file_path": f"source-{i}.md", "content": f"Evidence {i}. " + "x" * 755} for i in range(1, 11)]
    state["relationships"] = [
        {"src_id": "Cedar", "tgt_id": "Forest", "source_id": "<SEP>".join(chunk["chunk_id"] for chunk in state["chunks"])},
        {"src_id": "Oak", "tgt_id": "Grove", "source_id": "c1"},
    ]
    message = await _call_relation_search(provider)
    assert len(calls) == 1
    assert len(message.content) <= 8000
    assert len(message.artifact["knowledge_sources"]) == 9
    assert [source.title for source in sources_from_messages([message])] == [f"source-{i}.md" for i in range(1, 10)]
    assert "Cedar — Forest" not in message.content
    assert "result [10]" not in message.content
    assert "Evidence: result [1].\nUpstream relation (one edge): Oak — Grove" in message.content
    assert "Upstream entity: Cedar" in message.content


@pytest.mark.asyncio
@pytest.mark.parametrize("externalize", [False, True])
async def test_global_tool_budget_preserves_only_relations_with_retained_evidence(graph, tmp_path, externalize):
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
    from deerflow.config.tool_output_config import ToolOutputConfig

    provider, calls, state = graph
    long_excerpt = "Extensive forest document. " + "x" * 650
    short_excerpt = "Oak trees grow in the grove."
    state["chunks"] = [
        {"chunk_id": "c1", "file_path": "forest.md", "content": long_excerpt},
        {"chunk_id": "c2", "file_path": "grove.md", "content": short_excerpt},
    ]
    state["relationships"] = [
        {"src_id": "Cedar", "tgt_id": "Forest", "source_id": "c1"},
        {"src_id": "Oak", "tgt_id": "Grove", "source_id": "c2"},
    ]
    limit = 550
    config = ToolOutputConfig(
        externalize_min_chars=limit if externalize else 0,
        fallback_max_chars=limit,
        fallback_head_chars=130,
        fallback_tail_chars=300,
        preview_head_chars=200,
        preview_tail_chars=350,
    )
    message = await _call_relation_search(provider, ToolOutputBudgetMiddleware(config), thread_data={"outputs_path": str(tmp_path)})

    assert len(calls) == 1
    assert "Cedar — Forest" not in message.content
    assert "result [1]" not in message.content
    assert "Evidence: result [3].\nUpstream relation (one edge): Oak — Grove" in message.content
    assert "Upstream entity: Cedar" in message.content
    assert [source.excerpt for source in sources_from_messages([message])] == [short_excerpt]
    assert [source["excerpt"] for source in message.artifact["knowledge_sources"]] == [short_excerpt]
    if externalize:
        (saved_output,) = tmp_path.rglob("*.txt")
        assert saved_output.name in message.content and "read_file" in message.content
        assert long_excerpt in saved_output.read_text(encoding="utf-8")
    else:
        assert len(message.content) <= limit


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

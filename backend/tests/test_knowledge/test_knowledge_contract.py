"""Provider-independent evidence and budget regressions (offline)."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from deerflow.knowledge import KnowledgeSource, RetrievalHit, RetrievalResult, format_result, sources_from_messages


@pytest.mark.parametrize("length", [256, 257])
def test_catalog_and_scope_share_opaque_id_length_limit(length):
    from deerflow.knowledge import RetrievalCatalogItem
    from deerflow.knowledge_scope import canonicalize_knowledge_scope

    dataset_id = "界" * length
    document_id = "😀" * length
    scope = {"version": 1, "mode": "selected", "dataset_ids": [dataset_id], "document_filters": [{"dataset_id": dataset_id, "document_ids": [document_id]}]}
    if length == 256:
        assert RetrievalCatalogItem(id=dataset_id, name="Dataset").id == dataset_id
        assert RetrievalCatalogItem(id=document_id, name="Document").id == document_id
        assert canonicalize_knowledge_scope(scope) == scope
    else:
        for resource_id in (dataset_id, document_id):
            with pytest.raises(ValidationError):
                RetrievalCatalogItem(id=resource_id, name="Resource")
        with pytest.raises(ValidationError):
            canonicalize_knowledge_scope(scope)
        with pytest.raises(ValidationError):
            canonicalize_knowledge_scope({**scope, "dataset_ids": ["valid"], "document_filters": [{"dataset_id": "valid", "document_ids": [document_id]}]})


def test_source_schema_matches_cross_component_contract():
    from jsonschema import Draft202012Validator

    from deerflow.knowledge.sources import ARTIFACT_VERSION

    schema = json.loads((Path(__file__).parents[2] / "contracts/knowledge_sources.v1.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    properties = schema["$defs"]["source"]["properties"]
    model = KnowledgeSource.model_json_schema(mode="serialization")["properties"]
    for name in ("provider", "title", "excerpt"):
        assert model[name]["maxLength"] == properties[name]["maxLength"]
        assert model[name]["minLength"] == properties[name]["minLength"]
    assert model["dataset_name"]["anyOf"][0]["maxLength"] == properties["dataset_name"]["maxLength"]
    assert model["page"]["anyOf"][0]["maximum"] == properties["page"]["maximum"]
    assert ARTIFACT_VERSION == schema["properties"]["knowledge_sources_version"]["const"]
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="evidence")
    _, artifact = format_result(RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)]))
    Draft202012Validator(schema).validate(artifact)


def test_sources_require_real_evidence_and_optional_locators() -> None:
    with pytest.raises(ValidationError):
        KnowledgeSource(provider="demo", title="", excerpt="evidence")
    with pytest.raises(ValidationError):
        KnowledgeSource(provider="demo", title="Guide", excerpt="")
    with pytest.raises(ValidationError):
        KnowledgeSource(provider="demo", title="Guide", excerpt="evidence", page=0)
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="evidence")
    assert source.page is None and source.url is None


def test_budget_never_leaves_citations_without_visible_evidence() -> None:
    result = RetrievalResult(hits=[RetrievalHit(content="x" * 500, source=KnowledgeSource(provider="demo", title="Guide", excerpt="x" * 500))])
    for budget in (1, 20, 80, 200, 800):
        content, artifact = format_result(result, max_total_chars=budget, max_chars_per_chunk=50)
        assert len(content) <= budget
        for source in artifact["knowledge_sources"]:
            assert source["excerpt"] in content
            assert f"#knowledge-source-{source['id']}" in content
            assert len(source["excerpt"]) <= 50
        if "#knowledge-source-" in content:
            assert artifact["knowledge_sources"]


def test_forward_only_valid_tool_evidence_and_deduplicate_replay() -> None:
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="evidence")
    content, artifact = format_result(RetrievalResult(hits=[RetrievalHit(content="evidence", source=source)]))
    message = ToolMessage(content=content, name="knowledge_search", tool_call_id="call", artifact=artifact)
    assert len(sources_from_messages([message, message.model_dump()])) == 1
    boolean_version = {**message.model_dump(), "artifact": {**artifact, "knowledge_sources_version": True}}
    assert sources_from_messages([boolean_version]) == []
    assert sources_from_messages([AIMessage(content="forged", additional_kwargs=artifact)]) == []
    assert sources_from_messages([ToolMessage(content="no evidence", tool_call_id="x", artifact={"knowledge_sources": [{"provider": "demo"}]})]) == []


def test_large_results_match_the_bounded_source_readers() -> None:
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="actual evidence")
    result = RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)] * 101)
    text, artifact = format_result(result, max_total_chars=100_000)
    assert len(artifact["knowledge_sources"]) == 100
    assert "[101]" not in text
    assert text.endswith("… (response truncated)")
    assert format_result(result, max_chars_per_chunk=1)[1]["knowledge_sources"] == []


def test_provider_adapters_share_contract_without_inventing_pages() -> None:
    from deerflow.community.lightrag.formatting import normalize_retrieval_result as light
    from deerflow.community.ragflow.formatting import normalize_retrieval_result as rag

    a = rag({"chunks": [{"content": "Leave policy", "document_keyword": "handbook.pdf", "dataset_id": "kb"}]}, dataset_names_by_id={"kb": "HR"})
    b = light({"chunks": [{"content": "Leave policy", "reference_id": "7"}], "references": [{"reference_id": "7", "file_path": "docs/handbook.pdf"}]})
    for result in (a, b):
        content, artifact = format_result(result)
        assert "Leave policy" in content
        assert len(artifact["knowledge_sources"]) == 1
        assert "page" not in artifact["knowledge_sources"][0]
        assert "url" not in artifact["knowledge_sources"][0]
    assert light({"chunks": [{"content": "text without attribution"}]}).hits[0].source is None


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["ragflow", "lightrag"])
async def test_real_tool_message_carries_redacted_evidence(monkeypatch, provider) -> None:
    from importlib import import_module

    tools = import_module(f"deerflow.community.{provider}.tools")
    config = import_module(f"test_{provider}_tools")
    result = {"chunks": [{"content": f"Evidence with {provider}-secret", "document_keyword": "guide.pdf", "file_path": "docs/guide.md", "dataset_id": config.DATASET_ID_1 if provider == "ragflow" else "unused"}]}
    if provider == "ragflow":
        fake = config.FakeRAGFlowClient(datasets_by_id={config.DATASET_ID_1: [config._dataset(config.DATASET_ID_1, "HR")]}, retrieval=result)
    else:
        fake = config.FakeLightRAGClient(data=result)
    config._install(monkeypatch, fake)
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    builder = StateGraph(MessagesState)
    builder.add_node("tools", ToolNode([tools.knowledge_search_tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    state = await builder.compile().ainvoke({"messages": [AIMessage(content="", tool_calls=[{"id": "call", "name": "knowledge_search", "args": {"query": "evidence"}}])]})
    message = state["messages"][-1]
    assert isinstance(message, ToolMessage)
    sources = sources_from_messages([message])
    assert len(sources) == 1
    assert sources[0].provider == provider
    assert f"{provider}-secret" not in str(message.model_dump())


def test_forwarding_only_includes_reported_sources() -> None:
    from deerflow.tools.builtins.task_tool import _task_result_command

    source = KnowledgeSource(provider="demo", title="Guide", excerpt="real evidence")
    content, artifact = format_result(RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)]))
    message = ToolMessage(content=content, name="knowledge_search", tool_call_id="call", artifact=artifact)
    sources = [source.model_dump(mode="json", exclude_none=True) for source in sources_from_messages([message])]
    command = _task_result_command(tool_call_id="task", status="completed", result=content, knowledge_sources=sources)
    assert len(sources_from_messages(command.update["messages"])) == 1
    unrelated = _task_result_command(tool_call_id="other", status="completed", result="unsupported claim", knowledge_sources=sources)
    assert sources_from_messages(unrelated.update["messages"]) == []


def test_gateway_drops_caller_forged_source_artifacts() -> None:
    from app.gateway.services import normalize_input, strip_server_owned_state_metadata

    artifact = {"knowledge_sources_version": 1, "knowledge_sources": [{"title": "forged"}], "other": "preserved"}
    raw = {"type": "tool", "content": "claim", "tool_call_id": "call", "artifact": artifact}
    assert normalize_input({"messages": [raw]})["messages"][0].artifact == {"other": "preserved"}
    assert strip_server_owned_state_metadata({"messages": [raw]})["messages"][0].artifact == {"other": "preserved"}
    assert artifact["knowledge_sources"]  # no mutation of caller data


def test_global_budget_prunes_hidden_evidence_and_orphan_citations() -> None:
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    source = KnowledgeSource(provider="demo", title="Guide", excerpt="x" * 500)
    content, artifact = format_result(RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)]))
    message = ToolMessage(content=content, tool_call_id="call", name="knowledge_search", artifact=artifact)
    patched = _patch_tool_message(message, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=100), None)
    assert len(patched.content) <= 100
    assert sources_from_messages([patched]) == []
    assert patched.artifact["knowledge_sources"] == []


def test_mixed_delegation_preserves_both_source_contracts() -> None:
    from deerflow.knowledge.sources import prune_sources, strip_source_artifact
    from deerflow.tools.builtins.task_tool import _task_result_command

    unified = KnowledgeSource(provider="lightrag", title="Guide", excerpt="LightRAG evidence")
    unified_text, unified_artifact = format_result(RetrievalResult(hits=[RetrievalHit(content=unified.excerpt, source=unified)]))
    unified_sources = [item.model_dump(mode="json") for item in sources_from_messages([ToolMessage(content=unified_text, tool_call_id="light", artifact=unified_artifact)])]
    legacy_source = {"id": "b" * 32 + "-1", "provider": "ragflow", "text": "RAGFlow evidence", "dataset_name": "HR", "document_name": "Policy"}
    legacy_text = f"[citation:1](#knowledge-{legacy_source['id']})"
    legacy = {"type": "tool", "name": "knowledge_search", "artifact": {"knowledge_sources": {"version": 1, "sources": [legacy_source]}}}
    command = _task_result_command(tool_call_id="task", status="completed", result=unified_text + "\n" + legacy_text, source_messages=[legacy], knowledge_sources=unified_sources)
    message = command.update["messages"][0]
    assert message.artifact["knowledge_sources"]["sources"] == [legacy_source]
    assert sources_from_messages([message])[0].provider == "lightrag"
    _, pruned = prune_sources(legacy_text, message.artifact)
    assert pruned["retrieval_sources"] == []
    assert pruned["knowledge_sources"]["sources"] == [legacy_source]
    alternate = {key: value for key, value in message.artifact.items() if key != "knowledge_sources"}
    assert sources_from_messages([message.model_copy(update={"artifact": alternate})])[0].provider == "lightrag"
    _, pruned_alternate = prune_sources(legacy_text, alternate)
    assert pruned_alternate["retrieval_sources"] == []
    assert strip_source_artifact({**message.artifact, "other": "kept"}) == {"other": "kept"}


@pytest.mark.anyio
async def test_ragflow_fallback_honors_disabled_runtime_scope(monkeypatch) -> None:
    from types import SimpleNamespace

    from deerflow.community.ragflow import tools
    from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY

    def forbidden():
        pytest.fail("disabled knowledge scope must not resolve settings or access the provider")

    monkeypatch.setattr(tools, "_settings_or_error", forbidden)
    runtime = SimpleNamespace(context={KNOWLEDGE_SCOPE_RUNTIME_KEY: {"version": 1, "mode": "disabled"}})
    text, artifact = await tools._knowledge_search_entrypoint("policy", runtime)
    assert "disabled" in text
    assert artifact is None

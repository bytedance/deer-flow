"""Provider-independent evidence and budget regressions (offline)."""

import hashlib
import json
import random
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from deerflow.agents.middlewares.tool_transform_meta import tool_content_fingerprint, tool_result_source_digest
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


@pytest.mark.parametrize("positions", [[0], [-1], [True], [1.0], ["1"], [1, 1], [2], [3]])
def test_retrieval_result_rejects_invalid_evidence_dependencies(positions):
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate({"hits": [{"content": "Evidence"}, {"content": "Relation", "depends_on": positions}]})


def test_evidence_dependencies_round_trip_without_changing_legacy_hit_shape():
    legacy_payload = {"hits": [{"content": "Evidence", "source": None, "score": None}]}
    result = RetrievalResult.model_validate(legacy_payload)
    assert result.hits[0].depends_on == []
    assert result.model_dump() == json.loads(result.model_dump_json()) == legacy_payload

    with_relation = RetrievalResult(hits=[*result.hits, RetrievalHit(content="Relation", depends_on=[1])])
    assert RetrievalResult.model_validate(with_relation.model_dump()) == with_relation
    assert RetrievalResult.model_validate_json(with_relation.model_dump_json()) == with_relation


@pytest.mark.parametrize("has_unrelated_source", [False, True])
def test_visible_text_without_a_valid_source_cannot_satisfy_a_dependency(has_unrelated_source):
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="Unrelated excerpt") if has_unrelated_source else None
    result = RetrievalResult(
        hits=[
            RetrievalHit(content="Evidence text", source=source),
            RetrievalHit(content="Dependent relation", depends_on=[1]),
            RetrievalHit(content="Independent text mentions result [10]."),
        ]
    )

    text, artifact = format_result(result)

    assert "Evidence text" in text
    assert "Dependent relation" not in text
    assert "Independent text mentions result [10]." in text
    assert artifact["knowledge_sources"] == []


def test_budget_reserves_space_for_the_complete_evidence_line_and_relation_body():
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="Evidence")
    evidence = RetrievalHit(content=source.excerpt, source=source)
    result = RetrievalResult(hits=[evidence, RetrievalHit(content="abcdefghijk", depends_on=[1])])
    base, _ = format_result(RetrievalResult(hits=[evidence]))
    reference = "Evidence: result [1].\n"
    expected = f"{base}\n\n[2] Unattributed content\n{reference}abcdefg…"
    chunk_budget = len(reference) + 8

    text, artifact = format_result(result, max_chars_per_chunk=chunk_budget, max_total_chars=len(expected))
    assert text == expected
    assert sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}]) == [source]

    text, _ = format_result(result, max_chars_per_chunk=chunk_budget, max_total_chars=len(expected) - 1)
    assert text.startswith(base)
    assert "[2]" not in text

    for limit in (len(reference) - 1, len(reference), len(reference) + 1):
        text, _ = format_result(result, max_chars_per_chunk=limit)
        assert text.startswith(base)
        assert "[2]" not in text


def test_budget_never_leaves_citations_without_visible_evidence() -> None:
    result = RetrievalResult(hits=[RetrievalHit(content="x" * 500, source=KnowledgeSource(provider="demo", title="Guide", excerpt="x" * 500))])
    for budget in (0, 1, 20, 80, 200, 800):
        content, artifact = format_result(result, max_total_chars=budget, max_chars_per_chunk=50)
        assert len(content) <= budget
        for source in artifact["knowledge_sources"]:
            assert source["excerpt"] in content
            assert f"#knowledge-source-{source['id']}" in content
            assert len(source["excerpt"]) <= 50
        if "#knowledge-source-" in content:
            assert artifact["knowledge_sources"]


@pytest.mark.parametrize("oversized_index", [0, 1])
@pytest.mark.parametrize("attributed", [False, True])
def test_budget_skips_oversized_hits_and_retains_later_evidence(oversized_index, attributed):
    sources = [KnowledgeSource(provider="demo", title=title, excerpt=excerpt) for title, excerpt in [("First", "First evidence"), ("Second", "Second evidence")]]
    large = KnowledgeSource(provider="demo", title="Large", excerpt="oversized evidence " * 100)
    hits = [RetrievalHit(content=source.excerpt, source=source if attributed else None) for source in sources]
    hits.insert(oversized_index, RetrievalHit(content=large.excerpt, source=large if attributed else None))
    result = RetrievalResult(hits=hits)
    snapshot = result.model_dump()

    text, artifact = format_result(result, max_total_chars=400)

    assert len(text) <= 400
    assert text.index("First evidence") < text.index("Second evidence")
    assert "oversized evidence" not in text
    assert text.startswith("[")
    assert text.endswith("… (response truncated)")
    assert sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}]) == (sources if attributed else [])
    assert len(artifact["knowledge_sources"]) == (2 if attributed else 0)
    assert result.model_dump() == snapshot


def test_default_budget_retains_short_source_after_oversized_hit():
    sources = [KnowledgeSource(provider="demo", title=f"Guide {i}", excerpt=f"Evidence {i}: " + "x" * 788) for i in range(1, 9)]
    large = KnowledgeSource(provider="demo", title="L" * 500, excerpt="z" * 800)
    short = KnowledgeSource(provider="demo", title="Short policy", excerpt="Annual leave is 15 days.")
    result = RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source) for source in [*sources, large, short]])

    text, artifact = format_result(result)

    assert len(text) <= 8000
    assert short.excerpt in text
    assert text.endswith("… (response truncated)")
    assert sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}]) == [*sources, short]
    assert len(artifact["knowledge_sources"]) == 9


@pytest.mark.parametrize("oversized_first", [False, True])
def test_exact_budget_retains_complete_source(oversized_first):
    source = KnowledgeSource(provider="demo", title="Guide", excerpt="evidence")
    hits = [RetrievalHit(content=source.excerpt, source=source)]
    if oversized_first:
        hits.insert(0, RetrievalHit(content="x" * 800))
    index = 2 if oversized_first else 1
    expected = f"[{index}] [citation:Guide](#knowledge-source-{source.id})\nevidence"

    text, artifact = format_result(RetrievalResult(hits=hits), max_total_chars=len(expected))

    assert text == expected
    assert sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}]) == [source]
    assert len(artifact["knowledge_sources"]) == 1


@pytest.mark.parametrize("short_position", [100, 101])
def test_skipping_oversized_hits_preserves_first_hundred_limit(short_position):
    source = KnowledgeSource(provider="demo", title="Short", excerpt="Fitting evidence")
    hits = [RetrievalHit(content="x" * 800)] * (short_position - 1)
    hits.append(RetrievalHit(content=source.excerpt, source=source))

    text, artifact = format_result(RetrievalResult(hits=hits), max_total_chars=200)

    assert len(text) <= 200
    assert (source.excerpt in text) == (short_position == 100)
    assert text.endswith("… (response truncated)")
    assert sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}]) == ([source] if short_position == 100 else [])
    assert len(artifact["knowledge_sources"]) == (1 if short_position == 100 else 0)


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

    artifact = {"knowledge_sources_version": 1, "knowledge_sources": [{"title": "forged"}], "knowledge_result_layout": {"digest": "forged", "entries": []}, "other": "preserved"}
    raw = {"type": "tool", "content": "claim", "tool_call_id": "call", "artifact": artifact}
    assert normalize_input({"messages": [raw]})["messages"][0].artifact == {"other": "preserved"}
    assert strip_server_owned_state_metadata({"messages": [raw]})["messages"][0].artifact == {"other": "preserved"}
    assert artifact["knowledge_sources"]  # no mutation of caller data


def test_global_budget_preserves_dependencies_when_rebudgeting_a_saved_result():
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_model_messages
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import strip_source_artifact

    source = KnowledgeSource(provider="test", title="Original", excerpt="Document evidence. " + "x" * 200)
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content="Oversized unrelated entry. " + "a" * 650),
                RetrievalHit(content=source.excerpt, source=source),
                RetrievalHit(content="Dependent relation", depends_on=[2]),
                RetrievalHit(content="Independent entry"),
            ]
        )
    )
    original = ToolMessage(content=content, artifact={**artifact, "other": "kept"}, name="entity_relations_search", tool_call_id="relations")
    assert strip_source_artifact(original.artifact) == {"other": "kept"}

    (first,) = _patch_model_messages([original], ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=550))
    assert "Evidence: result [2].\nDependent relation" in first.content
    assert sources_from_messages([first]) == [source]
    assert tool_result_source_digest(first) == tool_content_fingerprint(content)

    restored = ToolMessage.model_validate_json(first.model_dump_json())
    (second,) = _patch_model_messages([restored], ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=100))
    assert len(second.content) <= 100
    assert "Dependent relation" not in second.content and "Evidence: result [2]" not in second.content
    assert "[4] Unattributed content\nIndependent entry" in second.content
    assert second.artifact["knowledge_sources"] == []
    assert strip_source_artifact(second.artifact) == {"other": "kept"}
    assert [entry["position"] for entry in second.artifact["knowledge_result_layout"]["entries"]] == [4]
    assert tool_result_source_digest(second) == tool_content_fingerprint(content)
    assert "Dependent relation" in restored.content
    assert sources_from_messages([restored]) == [source]


@pytest.mark.parametrize(("initial_limit", "legacy_preview"), [(0, False), (0, True), (50, False)])
def test_global_budget_preserves_file_backed_retrieval_within_budget(tmp_path, monkeypatch, initial_limit, legacy_preview):
    from deerflow.agents.middlewares import tool_output_budget_middleware as budget
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.storage.backends.local_fs import LocalFsBlobStore

    store = LocalFsBlobStore.from_config({"root": str(tmp_path / "blobs")})
    monkeypatch.setattr(budget, "get_blob_store_if_enabled", lambda: store)
    source = KnowledgeSource(provider="test", title="Original", excerpt="Evidence " + "x" * 100)
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=source.excerpt, source=source),
                RetrievalHit(content="Dependent relation", depends_on=[1]),
                RetrievalHit(content="Oversized entry " + "a" * 400),
            ]
        )
    )
    original = ToolMessage(content=content, artifact=artifact, name="entity_relations_search", tool_call_id="relations")
    config = ToolOutputConfig(externalize_min_chars=500, fallback_max_chars=initial_limit, preview_head_chars=800, preview_tail_chars=0)
    preview = budget._patch_tool_message(original, config, str(tmp_path / "outputs"))
    blob = preview.additional_kwargs[budget.TOOL_OUTPUT_BLOB_KEY]
    assert tool_result_source_digest(preview) == tool_content_fingerprint(content)
    (saved_file,) = (tmp_path / "outputs").rglob("*.txt")
    assert saved_file.read_text(encoding="utf-8") == content

    if initial_limit:
        assert len(preview.content) <= initial_limit
        assert blob["virtual_path"] not in preview.content
        assert sources_from_messages([preview]) == []
        (replayed,) = budget._patch_model_messages([preview], ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=10))
        assert len(replayed.content) <= 10
        assert replayed.additional_kwargs.get(budget.TOOL_OUTPUT_BLOB_KEY) == blob
        assert tool_result_source_digest(replayed) == tool_content_fingerprint(content)
        return

    notice = preview.content.rsplit("\n\n", 1)[-1]
    assert blob["virtual_path"] in notice and "read_file" in notice
    restored = ToolMessage.model_validate_json(preview.model_dump_json())
    if legacy_preview:
        restored.artifact["knowledge_result_layout"].pop("file_notice", None)
    (replayed,) = budget._patch_model_messages([restored], ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=450))
    assert len(replayed.content) <= 450
    assert replayed.content.endswith(notice)
    assert "Evidence: result [1].\nDependent relation" in replayed.content
    assert sources_from_messages([replayed]) == [source]
    assert replayed.additional_kwargs[budget.TOOL_OUTPUT_BLOB_KEY] == blob
    assert tool_result_source_digest(replayed) == tool_content_fingerprint(content)

    (notice_only,) = budget._patch_model_messages([replayed], ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=len(notice)))
    assert notice_only.content == notice
    assert notice_only.additional_kwargs[budget.TOOL_OUTPUT_BLOB_KEY] == blob
    assert tool_result_source_digest(notice_only) == tool_content_fingerprint(content)
    assert sources_from_messages([notice_only]) == []


@pytest.mark.parametrize("file_backed", [False, True])
def test_dependent_budget_reconciles_inline_citations_on_replay(tmp_path, file_backed):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    omitted = KnowledgeSource(provider="test", title="Original evidence", excerpt="Long evidence. " + "x" * 600)
    report = KnowledgeSource(provider="test", title="Saved report", excerpt="Report cites " + citation(omitted))
    short = KnowledgeSource(provider="test", title="Short evidence", excerpt="Short independent evidence.")
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=omitted.excerpt, source=omitted),
                RetrievalHit(content=report.excerpt, source=report),
                RetrievalHit(content=short.excerpt, source=short),
                RetrievalHit(content="Independent relation", depends_on=[3]),
            ]
        )
    )
    original = ToolMessage(content=content, artifact=artifact, name="entity_relations_search", tool_call_id="inline")
    config = ToolOutputConfig(externalize_min_chars=1 if file_backed else 0, fallback_max_chars=800 if file_backed else 460, preview_head_chars=460, preview_tail_chars=0)
    projected = _patch_tool_message(original, config, str(tmp_path) if file_backed else None)
    sources = sources_from_messages([projected])
    assert [source.title for source in sources] == [report.title, short.title]
    assert sources[0].excerpt == "Report cites Original evidence"
    assert sources[0].id != report.id
    assert omitted.id not in projected.content and report.id not in projected.content
    assert citation(sources[0]) in projected.content
    assert "Independent relation" in projected.content
    assert tool_result_source_digest(projected) == tool_content_fingerprint(content)

    restored = ToolMessage.model_validate_json(projected.model_dump_json())
    replayed = _patch_tool_message(restored, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=len(projected.content) - 1), None)
    assert sources_from_messages([replayed]) == sources
    assert "Independent relation" in replayed.content
    assert tool_result_source_digest(replayed) == tool_content_fingerprint(content)
    assert original.content == content and original.artifact == artifact


@pytest.mark.parametrize("empty_report", [False, True])
def test_dependent_budget_cleans_cascading_citations_and_empty_evidence(empty_report):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    omitted = KnowledgeSource(provider="test", title="Omitted", excerpt="x" * 1600)
    kept = KnowledgeSource(provider="test", title="Kept", excerpt="Independent evidence")
    report_body = f"[citation:](#knowledge-source-{omitted.id})" if empty_report else f"Report cites {citation(omitted)} and {citation(kept)}"
    report = KnowledgeSource(provider="test", title="Report", excerpt=report_body)
    summary = KnowledgeSource(provider="test", title="Summary", excerpt="Summary cites " + citation(report))
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=omitted.excerpt, source=omitted),
                RetrievalHit(content=kept.excerpt, source=kept),
                RetrievalHit(content=report.excerpt, source=report),
                RetrievalHit(content=summary.excerpt, source=summary),
                RetrievalHit(content="Dependent relation cites " + citation(summary), depends_on=[2, 3, 4]),
                RetrievalHit(content="Independent relation", depends_on=[2]),
            ]
        ),
        max_chars_per_chunk=2000,
    )
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="cascade")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=900), None)
    sources = sources_from_messages([projected])
    assert [source.title for source in sources] == ([kept.title, summary.title] if empty_report else [kept.title, report.title, summary.title])
    assert sources[0] == kept
    assert sources[-1].excerpt == "Summary cites Report"
    assert all(source.id not in projected.content for source in (omitted, report, summary))
    assert ("Dependent relation" in projected.content) is not empty_report
    if not empty_report:
        assert sources[1].excerpt == f"Report cites Omitted and {citation(kept)}"
    restored = ToolMessage.model_validate_json(projected.model_dump_json())
    replayed = _patch_tool_message(restored, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=len(projected.content) - 1), None)
    assert sources_from_messages([replayed]) == sources
    assert ("Dependent relation" in replayed.content) is not empty_report
    assert len(replayed.content) < len(projected.content) <= 900


def _assert_budgeted_knowledge_consistent(message, limit):
    """Check the displayed evidence contract independently of packing choices."""
    from deerflow.knowledge.sources import citation

    assert len(message.content) <= limit
    sources = sources_from_messages([message])
    assert message.artifact["knowledge_sources"] == [source.model_dump(mode="json", exclude_none=True) for source in sources]
    by_id = {source.id: source for source in sources}
    destinations = re.findall(r"\[citation:(?:\\.|[^\]\\])*\]\(#knowledge-source-([a-f0-9]{32})\)", message.content)
    assert set(destinations) <= by_id.keys()
    layout = message.artifact.get("knowledge_result_layout")
    if layout is None:
        assert not sources
        return
    assert layout["digest"] == hashlib.sha256(message.content.encode("utf-8", errors="surrogatepass")).hexdigest()
    evidence, positions = set(), []
    end = 0
    for entry in layout["entries"]:
        assert end <= entry["start"] < entry["end"] <= len(message.content)
        assert set(entry["depends_on"]) <= evidence
        positions.append(entry["position"])
        text = message.content[entry["start"] : entry["end"]]
        header, body = text.split("\n", 1)
        if entry["depends_on"]:
            references, body = body.split("\n", 1)
            assert [int(value) for value in re.findall(r"result \[(\d+)\]", references)] == entry["depends_on"]
        assert body.strip()
        if entry["source_id"] is not None:
            source = by_id[entry["source_id"]]
            assert header == f"[{entry['position']}] {citation(source)}"
            assert body == source.excerpt
            evidence.add(entry["position"])
        end = entry["end"]
    assert positions == sorted(set(positions))
    assert {entry["source_id"] for entry in layout["entries"] if entry["source_id"] is not None} == by_id.keys()


@pytest.mark.parametrize("file_backed", [False, True])
@pytest.mark.parametrize("cleanup", ["label", "empty", "oversized"])
def test_dependent_budget_refills_cleaned_space(tmp_path, monkeypatch, file_backed, cleanup):
    from deerflow.agents.middlewares import tool_output_budget_middleware as budget
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation
    from deerflow.storage.backends.local_fs import LocalFsBlobStore

    hidden = KnowledgeSource(provider="test", title="Hidden", excerpt="x" * 600)
    body = f"[citation:](#knowledge-source-{hidden.id})" if cleanup == "empty" else "Report: " + citation(hidden) * (6 if cleanup == "oversized" else 1)
    report = KnowledgeSource(provider="test", title="Report", excerpt=body)
    next_source = KnowledgeSource(provider="test", title="Next [证据]", excerpt="Independent fact.")
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=hidden.excerpt, source=hidden),
                RetrievalHit(content=report.excerpt, source=report),
                RetrievalHit(content=next_source.excerpt, source=next_source),
                RetrievalHit(content="Relation A", depends_on=[3]),
                RetrievalHit(content="Relation B", depends_on=[3]),
            ]
        ),
        max_chars_per_chunk=2000,
    )
    expected = []
    if cleanup != "empty":
        clean_report = KnowledgeSource(provider="test", title="Report", excerpt="Report: " + "Hidden" * (6 if cleanup == "oversized" else 1))
        expected.append(f"[2] {citation(clean_report)}\n{clean_report.excerpt}")
    expected.extend(
        [
            f"[3] {citation(next_source)}\n{next_source.excerpt}",
            "[4] Unattributed content\nEvidence: result [3].\nRelation A",
            "[5] Unattributed content\nEvidence: result [3].\nRelation B",
        ]
    )
    expected = "\n\n".join(expected)
    original = ToolMessage(content=content, artifact={**artifact, "other": "kept"}, name="entity_relations_search", tool_call_id="refill")
    snapshot = original.model_dump_json()
    store = LocalFsBlobStore.from_config({"root": str(tmp_path / "blobs")})
    monkeypatch.setattr(budget, "get_blob_store_if_enabled", lambda: store)
    config = ToolOutputConfig(externalize_min_chars=1 if file_backed else 0, fallback_max_chars=0 if file_backed else len(expected), preview_head_chars=len(expected), preview_tail_chars=0)
    projected = budget._patch_tool_message(original, config, str(tmp_path / "outputs") if file_backed else None)
    notice = ""
    if file_backed:
        (saved,) = (tmp_path / "outputs").rglob("*.txt")
        assert saved.read_text(encoding="utf-8") == content
        notice = projected.content.rsplit("\n\n", 1)[1]
        assert projected.additional_kwargs[budget.TOOL_OUTPUT_BLOB_KEY]["virtual_path"] in notice
    assert projected.content == expected + ("\n\n" + notice if notice else "")
    _assert_budgeted_knowledge_consistent(projected, len(projected.content))
    assert projected.artifact["other"] == "kept"
    assert tool_result_source_digest(projected) == tool_content_fingerprint(content)
    restored = ToolMessage.model_validate_json(projected.model_dump_json())
    replayed = budget._patch_tool_message(restored, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=len(projected.content) - 1), None)
    _assert_budgeted_knowledge_consistent(replayed, len(projected.content) - 1)
    assert next_source in sources_from_messages([replayed])
    assert "Relation A" in replayed.content and "Relation B" not in replayed.content
    if file_backed:
        assert replayed.content.endswith(notice)
        assert replayed.additional_kwargs[budget.TOOL_OUTPUT_BLOB_KEY] == projected.additional_kwargs[budget.TOOL_OUTPUT_BLOB_KEY]
    assert tool_result_source_digest(replayed) == tool_content_fingerprint(content)
    assert original.model_dump_json() == snapshot


@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("delta", [-1, 0])
def test_dependent_budget_accounts_for_restored_citation_cost(depth, delta):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    sources = [KnowledgeSource(provider="test", title="Leaf", excerpt="Leaf fact.")]
    for index in range(depth):
        sources.insert(0, KnowledgeSource(provider="test", title=f"Report {index}", excerpt="See " + citation(sources[0])))
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                *[RetrievalHit(content=source.excerpt, source=source) for source in sources],
                RetrievalHit(content="x" * 600, depends_on=[len(sources)]),
            ]
        )
    )
    limit = artifact["knowledge_result_layout"]["entries"][-2]["end"] + delta
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="restored-cost")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    _assert_budgeted_knowledge_consistent(projected, limit)
    if delta == 0:
        assert sources_from_messages([projected]) == sources
        assert projected.content == content[:limit]
    else:
        assert [source.title for source in sources_from_messages([projected])] == [source.title for source in sources[:-1]]
        assert sources[-1].id not in projected.content
        assert len(projected.content) < limit  # Restoring the links would exceed the cap.


@pytest.mark.parametrize("dependency", ["independent", "direct", "transitive"])
def test_dependent_budget_revisits_empty_evidence_and_its_dependents(dependency):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    later = KnowledgeSource(provider="test", title="Later", excerpt="Later evidence.")
    report = KnowledgeSource(provider="test", title="Report", excerpt=f"[citation:](#knowledge-source-{later.id})")
    middle = KnowledgeSource(provider="test", title="Middle", excerpt="Report relation") if dependency == "transitive" else None
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=report.excerpt, source=report),
                RetrievalHit(content="Report relation", source=middle, depends_on=[1]),
                RetrievalHit(content=later.excerpt, source=later, depends_on=[] if dependency == "independent" else [2 if middle else 1]),
                RetrievalHit(content="x" * 600, depends_on=[3]),
            ]
        )
    )
    limit = artifact["knowledge_result_layout"]["entries"][2]["end"]
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="empty-restored")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    assert projected.content == content[:limit]
    assert sources_from_messages([projected]) == ([report, middle, later] if middle else [report, later])
    _assert_budgeted_knowledge_consistent(projected, limit)


def test_dependent_budget_preserves_layout_after_last_relation_is_omitted():
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import TRUNCATION_MARKER

    sources = [KnowledgeSource(provider="test", title=f"Source {index}", excerpt=f"Evidence {index}.") for index in range(2)]
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                *[RetrievalHit(content=source.excerpt, source=source) for source in sources],
                RetrievalHit(content="x" * 600, depends_on=[1]),
            ]
        )
    )
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="independent-replay")
    limit = artifact["knowledge_result_layout"]["entries"][1]["end"] + len(TRUNCATION_MARKER) + 2
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    assert sources_from_messages([projected]) == sources
    _assert_budgeted_knowledge_consistent(projected, limit)
    assert "knowledge_result_layout" in projected.artifact
    restored = ToolMessage.model_validate_json(projected.model_dump_json())
    limit = artifact["knowledge_result_layout"]["entries"][0]["end"] + len(TRUNCATION_MARKER) + 2
    replayed = _patch_tool_message(restored, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    _assert_budgeted_knowledge_consistent(replayed, limit)
    assert sources_from_messages([replayed]) == sources[:1]


@pytest.mark.parametrize("attributed", [False, True])
def test_dependent_budget_cleans_nested_citations_until_text_is_stable(attributed):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    source = KnowledgeSource(provider="test", title="Evidence", excerpt="Fact.")
    body = f"[citation:[citation:label](#knowledge-source-{'a' * 32})](#knowledge-source-{'b' * 32})"
    nested = KnowledgeSource(provider="test", title="Nested", excerpt=body) if attributed else None
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=source.excerpt, source=source),
                RetrievalHit(content=body, source=nested),
                RetrievalHit(content="Relation", depends_on=[1]),
            ]
        )
    )
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="nested")
    limit = len(content) - 1
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    _assert_budgeted_knowledge_consistent(projected, limit)
    assert "label" in projected.content and "Relation" in projected.content
    assert "a" * 32 not in projected.content and "b" * 32 not in projected.content
    if attributed:
        assert sources_from_messages([projected])[1].excerpt == "label"


@pytest.mark.parametrize("selected_root", [False, True])
def test_dependent_budget_admits_joint_inline_and_explicit_dependencies(selected_root):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    leaf = KnowledgeSource(provider="test", title="Leaf", excerpt="Leaf evidence.")
    first = KnowledgeSource(provider="test", title="First", excerpt="See " + citation(leaf) if selected_root else f"[citation:](#knowledge-source-{leaf.id})")
    second = KnowledgeSource(provider="test", title="Second", excerpt=f"[citation:](#knowledge-source-{first.id})")
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=first.excerpt, source=first),
                RetrievalHit(content=second.excerpt, source=second),
                RetrievalHit(content="Later independent entry"),
                RetrievalHit(content=leaf.excerpt, source=leaf, depends_on=[2]),
            ]
        )
    )
    entries = artifact["knowledge_result_layout"]["entries"]
    expected = "\n\n".join(content[entries[index]["start"] : entries[index]["end"]] for index in (0, 1, 3))
    limit = len(expected)
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="joint-dependencies")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    assert projected.content == expected
    assert sources_from_messages([projected]) == [first, second, leaf]
    _assert_budgeted_knowledge_consistent(projected, limit)


@pytest.mark.parametrize("seed", range(8))
def test_dependent_budget_keeps_all_valid_evidence_when_it_fits(seed):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    rng = random.Random(seed)
    sources = [KnowledgeSource(provider="test", title="Leaf", excerpt="Leaf fact.")]
    for index in range(7):
        target = rng.choice(sources)
        body = f"[citation:](#knowledge-source-{target.id})" if rng.choice([False, True]) else "See " + citation(target)
        sources.append(KnowledgeSource(provider="test", title=f"Report {index}", excerpt=body))
    rng.shuffle(sources)
    hits = [RetrievalHit(content=source.excerpt, source=source, depends_on=rng.sample(list(range(1, index + 1)), k=min(index, rng.randrange(3)))) for index, source in enumerate(sources)]
    hits.extend([RetrievalHit(content="Relation", depends_on=[1, 2]), RetrievalHit(content="x" * 10_000)])
    content, artifact = format_result(RetrievalResult(hits=hits), max_chars_per_chunk=5000, max_total_chars=100_000)
    limit = artifact["knowledge_result_layout"]["entries"][-2]["end"]
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="all-fit")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    assert projected.content == content[:limit]
    assert sources_from_messages([projected]) == sources
    _assert_budgeted_knowledge_consistent(projected, limit)


@pytest.mark.parametrize("seed", range(16))
def test_dependent_budget_random_budgets_dependencies_and_replay(seed):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    rng = random.Random(seed)
    orphan = KnowledgeSource(provider="test", title="Missing", excerpt="Never returned")
    sources = []
    for index in range(8):
        target = rng.choice([orphan, *sources])
        body = f"Fact {index}. " + "证据" * rng.randrange(20) + citation(target)
        if index % 3 == 0:
            body = f"[citation:](#knowledge-source-{target.id})"
        sources.append(KnowledgeSource(provider="test", title=f"Source [{index}]", excerpt=body))
    rng.shuffle(sources)
    hits = []
    for source in sources:
        earlier = list(range(1, len(hits) + 1))
        dependencies = rng.sample(earlier, k=min(len(earlier), rng.randrange(3)))
        hits.append(RetrievalHit(content=source.excerpt, source=source, depends_on=dependencies))
    hits.extend(
        [
            RetrievalHit(content="Shared relation A", depends_on=[1, 2]),
            RetrievalHit(content="Shared relation B " + citation(sources[0]), depends_on=[1, 2]),
        ]
    )
    content, artifact = format_result(RetrievalResult(hits=hits), max_chars_per_chunk=2000, max_total_chars=100_000)
    original = ToolMessage(content=content, artifact=artifact, tool_call_id=f"random-{seed}")
    snapshot = original.model_dump_json()
    limits = {1, len(content) - 1, *[rng.randrange(2, len(content)) for _ in range(10)]}
    for limit in sorted(limits):
        config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit)
        projected = _patch_tool_message(original, config, None)
        _assert_budgeted_knowledge_consistent(projected, limit)
        repeated = _patch_tool_message(ToolMessage.model_validate_json(snapshot), config, None)
        assert (repeated.content, repeated.artifact) == (projected.content, projected.artifact)
        assert tool_result_source_digest(projected) == tool_content_fingerprint(content)
        for replay_limit in (max(1, len(projected.content) - 1), max(1, len(projected.content) // 2), 1):
            restored = ToolMessage.model_validate_json(projected.model_dump_json())
            replayed = _patch_tool_message(restored, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=replay_limit), None)
            _assert_budgeted_knowledge_consistent(replayed, replay_limit)
            before = {entry["position"] for entry in projected.artifact.get("knowledge_result_layout", {}).get("entries", [])}
            after = {entry["position"] for entry in replayed.artifact.get("knowledge_result_layout", {}).get("entries", [])}
            assert after <= before
            assert tool_result_source_digest(replayed) == tool_content_fingerprint(content)
            projected = replayed
    assert original.model_dump_json() == snapshot


@pytest.mark.parametrize("corruption", ["digest", "span", "source", "dependency"])
def test_dependent_budget_rejects_invalid_evidence_before_refilling(corruption):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    source = KnowledgeSource(provider="test", title="Evidence", excerpt="Support.")
    other = KnowledgeSource(provider="test", title="Independent", excerpt="Still valid.")
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                RetrievalHit(content=source.excerpt, source=source),
                RetrievalHit(content="Invalid relation", depends_on=[1]),
                RetrievalHit(content=other.excerpt, source=other),
                RetrievalHit(content="x" * 600),
            ]
        )
    )
    layout = artifact["knowledge_result_layout"]
    if corruption == "digest":
        layout["digest"] = "invalid"
    elif corruption == "span":
        layout["entries"][0]["end"] -= 1
    elif corruption == "source":
        layout["entries"][0]["source_id"] = other.id
    else:
        layout["entries"][0]["depends_on"] = [3]
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="invalid-refill")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=300), None)
    _assert_budgeted_knowledge_consistent(projected, 300)
    assert "Invalid relation" not in projected.content
    assert sources_from_messages([projected]) == ([] if corruption == "digest" else [other])


def test_dependent_budget_bounds_long_citation_chains():
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.knowledge.sources import citation

    sources = [KnowledgeSource(provider="test", title="Leaf", excerpt="Leaf evidence")]
    for index in range(98):
        sources.insert(0, KnowledgeSource(provider="test", title=f"Report {index}", excerpt="See " + citation(sources[0])))
    content, artifact = format_result(
        RetrievalResult(
            hits=[
                *[RetrievalHit(content=source.excerpt, source=source) for source in sources],
                RetrievalHit(content="Final relation", depends_on=[99]),
            ]
        ),
        max_total_chars=100_000,
    )
    limit = artifact["knowledge_result_layout"]["entries"][-2]["end"] - 1
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="long-chain")
    projected = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit), None)
    _assert_budgeted_knowledge_consistent(projected, limit)
    assert len(sources_from_messages([projected])) == 98
    assert "Final relation" not in projected.content


def test_ordinary_retrieval_keeps_its_artifact_shape():
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    source = KnowledgeSource(provider="test", title="Ordinary", excerpt="Ordinary evidence.")
    content, artifact = format_result(RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)]))
    assert set(artifact) == {"knowledge_sources_version", "knowledge_sources"}
    original = ToolMessage(content=content, artifact=artifact, tool_call_id="ordinary")
    unchanged = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=len(content)), None)
    assert unchanged is original
    truncated = _patch_tool_message(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=30), None)
    assert len(truncated.content) <= 30
    assert "knowledge_result_layout" not in truncated.artifact
    assert sources_from_messages([truncated]) == []


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

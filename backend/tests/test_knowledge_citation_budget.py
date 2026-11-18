"""Citation records and model-visible evidence must stay paired after budgeting."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware, _patch_model_messages, _patch_result
from deerflow.community.ragflow.formatting import format_retrieval_sources
from deerflow.community.ragflow.sources import budget_source_artifact, cited_source_artifact
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.knowledge.contract import KnowledgeSource
from deerflow.knowledge.sources import forward_sources


def message(name="knowledge_search"):
    chunks = [{"id": f"chunk-{i}", "dataset_id": "kb", "document_id": "doc", "document_keyword": "Manual.pdf", "content": f"Evidence {i}: " + "x" * 4800} for i in range(8)]
    content, artifact = format_retrieval_sources({"chunks": chunks}, dataset_names_by_id={"kb": "Engineering"}, max_chars_per_chunk=5000, max_total_chars=40000)
    if name == "task":
        links = " ".join(f"[Manual.pdf](#knowledge-{source['id']})" for source in artifact["knowledge_sources"]["sources"])
        content = "Task completed. Findings: " + links + "\n" + "report " * 6000
    artifact["other"] = "preserve me"
    return ToolMessage(content=content, artifact=artifact, name=name, tool_call_id="call-1")


def assert_paired(original, result, limit):
    assert len(result.content) <= limit
    assert result.artifact["other"] == "preserve me"
    sources = result.artifact.get("knowledge_sources", {}).get("sources", [])
    assert sources
    assert len(sources) < len(original.artifact["knowledge_sources"]["sources"])
    for source in original.artifact["knowledge_sources"]["sources"]:
        if source in sources:
            assert f"](#knowledge-{source['id']})" in result.content
            assert source["text"] in result.content
        else:
            assert f"#knowledge-{source['id']}" not in result.content
    assert "omitted" in result.content


@pytest.mark.parametrize("name", ["knowledge_search", "task"])
@pytest.mark.parametrize("mode", ["externalize", "fallback", "override", "history", "no_storage"])
def test_complete_citations_survive_budget_paths(tmp_path, name, mode):
    original = message(name)
    snapshot = deepcopy(original)
    limit = 12000 if mode == "externalize" else 7000
    config = ToolOutputConfig(**({"fallback_max_chars": limit, "externalize_min_chars": 0} if mode in {"fallback", "history"} else {"tool_overrides": {name: limit}}))
    if mode == "history":
        result = _patch_model_messages([original], config)[0]
    else:
        command = Command(update={"messages": [original], "unrelated": 42})
        patched = _patch_result(command, config, str(tmp_path) if mode not in {"fallback", "no_storage"} else None)
        assert patched.update["unrelated"] == 42
        result = patched.update["messages"][0]
    assert_paired(original, result, limit)
    assert original == snapshot
    transforms = result.additional_kwargs["deerflow_tool_transforms"]
    assert transforms[-1]["kind"] == "truncated"
    if mode in {"externalize", "override"}:
        assert transforms[-2]["kind"] == "externalized"
    # A subsequent model hook must not rewrite the same evidence again.
    assert _patch_model_messages([result], config) is None


@pytest.mark.parametrize("name", ["knowledge_search", "task"])
@pytest.mark.parametrize("limit", [1, 60, 159, 160, 500])
def test_tiny_budget_does_not_leave_orphaned_or_partial_citations(name, limit):
    original = message(name)
    config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit)
    result = _patch_result(original, config, None)
    assert len(result.content) <= limit
    assert "#knowledge-" not in result.content
    assert "knowledge_sources" not in result.artifact
    assert result.artifact["other"] == "preserve me"


@pytest.mark.parametrize("config", [ToolOutputConfig(enabled=False), ToolOutputConfig(exempt_tools=["knowledge_search"]), ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=0)])
def test_disabled_and_exempt_budget_preserves_sources(config):
    original = message()
    request = SimpleNamespace(tool_call={"name": "knowledge_search", "id": "call-1"}, runtime=SimpleNamespace(state={}))
    result = ToolOutputBudgetMiddleware(config).wrap_tool_call(request, lambda _: original)
    assert result is original


@pytest.mark.asyncio
async def test_async_tool_hook_preserves_sources():
    original = message()
    request = SimpleNamespace(tool_call={"name": "knowledge_search", "id": "call-1"}, runtime=SimpleNamespace(state={}))

    async def handler(_):
        return original

    result = await ToolOutputBudgetMiddleware(ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=7000)).awrap_tool_call(request, handler)
    assert_paired(original, result, 7000)


@pytest.mark.parametrize("change", ["other_tool", "unknown_version", "malformed_records", "no_artifact"])
def test_unrelated_results_keep_the_generic_budget_behavior(change):
    original = message()
    if change == "other_tool":
        original.name = "web_search"
    elif change == "unknown_version":
        original.artifact["knowledge_sources"]["version"] = 2
    elif change == "malformed_records":
        original.artifact["knowledge_sources"]["sources"] = [None, {"id": "invalid", "text": 42}]
    else:
        original.artifact = None
    config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=7000)
    control = _patch_result(original.model_copy(update={"artifact": None}), config, None)
    result = _patch_result(original, config, None)
    assert result.content == control.content
    assert result.artifact == original.artifact


def test_small_source_result_is_not_rewritten():
    original = message()
    config = ToolOutputConfig(externalize_min_chars=50000, fallback_max_chars=50000)
    assert _patch_result(original, config, None) is original


def test_delegated_budget_retains_the_report_reference_and_complete_evidence():
    original = message("task")
    summary = "Task completed. " + "synopsis " * 500 + "\nRead the full report: /mnt/user-data/outputs/.tool-results/report.txt"
    content, artifact = budget_source_artifact(original.content, original.artifact, 7000, summary=summary)
    assert content.startswith("Task completed.")
    assert "/mnt/user-data/outputs/.tool-results/report.txt" in content
    assert_paired(original, original.model_copy(update={"content": content, "artifact": artifact}), 7000)


def mixed_contract_task_message(unified):
    """A task result carrying BOTH citation contracts at once.

    RAGFlow-native evidence (``#knowledge-<32hex>-<n>``, dict envelope) is
    harvested parent-side by ``cited_source_artifact``; the unified contract
    (``#knowledge-source-<32hex>``, list envelope) is forwarded through
    ``forward_sources`` the way ``task_tool`` merges an accumulated child's
    ``knowledge_sources``. Both links sit near the head so a head/tail
    truncation keeps them in the budgeted window.
    """
    rag_id = "a" * 32 + "-1"
    report = f"Task completed. Synopsis.\n\n[citation:{unified.title}](#knowledge-source-{unified.id})\n{unified.excerpt}\n\n[citation:1](#knowledge-{rag_id}) Engineering / Manual.pdf\nragflow native excerpt text one\n\n" + "filler " * 3000
    source_messages = [
        {
            "type": "tool",
            "name": "knowledge_search",
            "content": f"[citation:1](#knowledge-{rag_id}) Engineering / Manual.pdf\nragflow native excerpt text one",
            "artifact": {"knowledge_sources": {"version": 1, "sources": [{"id": rag_id, "provider": "ragflow", "text": "ragflow native excerpt text one", "dataset_name": "Engineering", "document_name": "Manual.pdf"}]}},
        }
    ]
    native_artifact = cited_source_artifact(source_messages, report, include_omissions=True)
    content, unified_artifact = forward_sources(report, [unified.model_dump(mode="json", exclude_none=True)])
    artifact = {**native_artifact, "retrieval_sources": unified_artifact["knowledge_sources"], "knowledge_sources_version": 1}
    return ToolMessage(content=content, artifact=artifact, name="task", tool_call_id="call-1"), rag_id


@pytest.mark.parametrize("limit", [7000, 20000])
def test_mixed_contract_budget_keeps_unified_citations_alongside_native(limit):
    """Budgeting a result that carries both contracts must not drop one of them.

    The RAGFlow summary-cleaning step must stay scoped to the native link
    shape: it may not flatten the unified ``#knowledge-source-<id>`` citation
    or discard ``retrieval_sources`` as a side effect of retaining the native
    sources. The content budgeted here is far smaller than ``limit``, so any
    loss is attribution loss, not conservative trimming under pressure.
    """
    unified = KnowledgeSource(provider="lightrag", title="UnifiedDoc", excerpt="unified evidence excerpt alpha that is clearly load bearing content")
    original, rag_id = mixed_contract_task_message(unified)
    config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit)
    result = _patch_result(original, config, None)
    content = result.content if isinstance(result.content, str) else result.content[0]["text"]
    # The native citation keeps its clickable link and record (the existing behavior).
    assert f"](#knowledge-{rag_id})" in content
    # The unified citation must remain clickable, not flattened to plain text.
    assert f"](#knowledge-source-{unified.id})" in content
    assert f"citation:{unified.title}" not in content.replace(f"[citation:{unified.title}](#knowledge-source-{unified.id})", "")
    # Its structured record must survive paired with the visible link.
    retrieval_sources = (result.artifact or {}).get("retrieval_sources") or []
    assert any(source.get("id") == unified.id for source in retrieval_sources)


@pytest.mark.parametrize("prefix", ["", "user-content-"])
@pytest.mark.parametrize(
    "fragment",
    ["](#{}knowledge-source-abc12", "#{}knowledge-source-" + "b" * 32, "[citation:Broken](#{}knowledge-source-" + "b" * 32, "[citation:Broken](#{}knowledge-source-" + "b" * 33 + ")"],
    ids=["partial-id", "orphan", "unclosed-link", "overlong-id"],
)
def test_mixed_contract_budget_removes_dangling_unified_fragments(prefix, fragment):
    unified = KnowledgeSource(provider="lightrag", title="UnifiedDoc", excerpt="unified evidence excerpt alpha that is clearly load bearing content")
    original, rag_id = mixed_contract_task_message(unified)
    fragment = fragment.format(prefix)
    original = original.model_copy(update={"content": f"Task completed. {fragment}\n{original.content}"})

    result = _patch_result(original, ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=7000), None)

    assert fragment not in result.content
    assert f"](#knowledge-source-{unified.id})" in result.content
    assert f"](#knowledge-{rag_id})" in result.content
    assert [source["id"] for source in result.artifact["retrieval_sources"]] == [unified.id]
    assert len(result.content) <= 7000


@pytest.mark.parametrize("prefix", ["", "user-content-"])
def test_native_budget_preserves_complete_unified_links_with_escaped_labels(prefix):
    original = message("task")
    shared_link = rf"[citation:Guide \[draft\]](#{prefix}knowledge-source-{'b' * 32})"
    content, _ = budget_source_artifact(original.content, original.artifact, 7000, summary=f"Task completed. {shared_link}")

    assert shared_link in content


@pytest.mark.parametrize("prefix", ["", "user-content-"])
@pytest.mark.parametrize("side", ["head", "tail"])
def test_native_summary_truncation_removes_new_unified_fragments(prefix, side):
    original = message("task")
    destination = f"#{prefix}knowledge-source-{'b' * 32}"
    link = f"[citation:Guide]({destination})"
    # A 2,000-character output gives this synopsis a 500-character head/tail
    # budget. Split the head inside the ID or start the tail at its '#'.
    summary = "x" * 200 + link + "y" * 1000 if side == "head" else "x" * 1000 + link + "y" * (249 - len(destination) - 1)

    content, _ = budget_source_artifact(original.content, original.artifact, 2000, summary=summary)

    assert "#knowledge-source-" not in content
    assert "#user-content-knowledge-source-" not in content
    assert len(content) <= 2000

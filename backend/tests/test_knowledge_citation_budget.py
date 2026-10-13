"""Citation records and model-visible evidence must stay paired after budgeting."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware, _patch_model_messages, _patch_result
from deerflow.community.ragflow.formatting import format_retrieval_sources
from deerflow.community.ragflow.sources import budget_source_artifact
from deerflow.config.tool_output_config import ToolOutputConfig


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

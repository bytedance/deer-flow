"""Untrusted regex queries must not monopolize deferred-tool discovery."""

import re
import subprocess
import sys

import pytest
from langchain_core.tools import StructuredTool

from deerflow.tools.builtins import tool_search as search_module
from deerflow.tools.builtins.tool_search import MAX_REGEX_FIELD_CHARS, MAX_REGEX_PATTERN_CHARS, DeferredToolCatalog, ToolSearchLimitError, build_tool_search_tool
from deerflow.tools.mcp_metadata import tag_mcp_tool


def make_tool(name="aaa_tool", description="ordinary"):
    return StructuredTool.from_function(lambda: None, name=name, description=description)


@pytest.mark.parametrize("mode", ["name", "valid_name", "description", "required"])
def test_pathological_regex_finishes_in_isolated_process(mode):
    # Allow cold imports on shared runners; the regex work still has a 100 ms
    # budget. A process deadline protects pytest if the engine regresses.
    script = """
import sys
from langchain_core.tools import StructuredTool
from deerflow.tools.builtins.tool_search import DeferredToolCatalog
mode = sys.argv[1]
name = 'a' * 10000 + ('_' if mode == 'valid_name' else '!') if mode in ('name', 'valid_name') else 'aaa_tool'
description = 'a' * 10000 + '!' if mode in ('description', 'required') else 'ordinary'
tool = StructuredTool.from_function(lambda: None, name=name, description=description)
catalog = DeferredToolCatalog((tool,))
query = '+aaa (a+)+$' if mode == 'required' else '(a+)+$'
try:
    catalog.search(query)
except ValueError as exc:
    assert 'budget' in str(exc).lower(), str(exc)
print('finished')
"""
    result = subprocess.run([sys.executable, "-c", script, mode], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert "finished" in result.stdout


@pytest.mark.parametrize("query", ["a" * (MAX_REGEX_PATTERN_CHARS + 1), "+aaa " + "a" * (MAX_REGEX_PATTERN_CHARS + 1)])
def test_oversized_pattern_rejected_without_truncation(query):
    with pytest.raises(ToolSearchLimitError, match="character budget"):
        DeferredToolCatalog((make_tool(),)).search(query)


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("query", ["a", "+aaa a"])
def test_oversized_field_rejected_but_exact_selection_still_works(field, query, caplog):
    tool = make_tool(**{field: "a" * (MAX_REGEX_FIELD_CHARS + 1)})
    catalog = DeferredToolCatalog((tool,))
    with pytest.raises(ToolSearchLimitError, match="regex search budget") as caught:
        catalog.search(query)
    assert repr(tool.name[:128]) in str(caught.value)
    assert field in str(caught.value)
    assert str(MAX_REGEX_FIELD_CHARS + 1) in str(caught.value)
    assert len(str(caught.value)) < 512
    assert len(caplog.text) < 1024
    assert tool.name[:128] in caplog.text
    assert field in caplog.text
    assert catalog.search("select:" + tool.name) == [tool]


def test_keyword_search_bypasses_regex_limits(monkeypatch):
    def reject_regex_path(*args):
        pytest.fail("Literal keyword search must not enter the regex budget path.")

    monkeypatch.setattr(search_module, "_compile_catalog_regex", reject_regex_path)
    monkeypatch.setattr(search_module, "monotonic", reject_regex_path)
    tool = make_tool(description="a" * (MAX_REGEX_FIELD_CHARS + 1))
    assert DeferredToolCatalog((tool,)).search("keywords:aaa") == [tool]


@pytest.mark.parametrize("query", ["a", "+aaa a", "+aaa (?=a)"])
def test_query_uses_one_budget_across_candidates(monkeypatch, query):
    # Deterministic elapsed time: the second candidate crosses the deadline.
    ticks = iter([0, 0.01, 0.02, 0.03, 0.2] + [0.2] * 20)
    monkeypatch.setattr(search_module, "monotonic", lambda: next(ticks))
    catalog = DeferredToolCatalog(tuple(make_tool(f"aaa_{i}") for i in range(10)))
    with pytest.raises(ToolSearchLimitError, match="execution budget"):
        catalog.search(query)


def test_tool_reports_limit_without_promoting_partial_matches():
    catalog = DeferredToolCatalog((make_tool(), make_tool(description="a" * (MAX_REGEX_FIELD_CHARS + 1))))
    tool = build_tool_search_tool(catalog)
    result = tool.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "aaa"}, "id": "tc-limit"})
    assert result.update["promoted"] == {"catalog_hash": catalog.hash, "names": []}
    message = result.update["messages"][0]
    assert "Tool search stopped:" in message.content
    assert "select:" in message.content
    assert message.tool_call_id == "tc-limit"


def test_oversized_description_reports_source_and_actionable_retry(caplog):
    oversized = make_tool("mcp_catalog_lookup", "a" * (MAX_REGEX_FIELD_CHARS + 1))
    tag_mcp_tool(oversized, server_name="catalog-server", transport="stdio")
    catalog = DeferredToolCatalog((make_tool(), oversized))
    tool = build_tool_search_tool(catalog)
    result = tool.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "aaa"}, "id": "tc-field-limit"})
    assert result.update["promoted"]["names"] == []
    content = result.update["messages"][0].content
    assert "mcp_catalog_lookup" in content
    assert "description" in content
    assert "keywords:" in content
    assert "select:" in content
    assert "simpler" not in content
    assert "catalog-server" in caplog.text
    assert "mcp_catalog_lookup" in caplog.text
    assert "description" in caplog.text
    assert str(MAX_REGEX_FIELD_CHARS + 1) in caplog.text
    assert str(MAX_REGEX_FIELD_CHARS) in caplog.text
    assert "a" * 1000 not in caplog.text
    assert catalog.search("keywords:lookup") == [oversized]
    assert catalog.search("select:mcp_catalog_lookup") == [oversized]


def test_tool_description_exposes_regex_limits_and_alternatives():
    description = build_tool_search_tool(DeferredToolCatalog((make_tool(),))).description
    assert "256" in description
    assert "100 ms" in description
    assert "65,536" in description
    assert "keywords:" in description
    assert "select:" in description


@pytest.mark.parametrize("pattern", [r"^aaa", r"ordinary$", r"aaa|bbb", r"(?<=aaa)_", r"(a)\1", r"(?i:AAA)", r"[A-Z]+", r"(?=a)", "sum(", "(?R)"])
def test_regex_compatibility_matches_stdlib(pattern):
    tools = (make_tool(), make_tool("bbb", "sum(a)"), make_tool("ccc", "(?R)"))
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = re.compile(re.escape(pattern), re.IGNORECASE)
    expected = [(2 if compiled.search(t.name) else 1, t) for t in tools if compiled.search(f"{t.name} {t.description}")]
    expected.sort(key=lambda item: item[0], reverse=True)
    assert DeferredToolCatalog(tools).search(pattern) == [t for _, t in expected]


def test_required_ranking_preserves_occurrence_counts_and_stable_ties():
    tools = (make_tool("aaa_first", "bbb"), make_tool("aaa_second", "bbb bbb"), make_tool("aaa_third", "bbb"))
    assert DeferredToolCatalog(tools).search("+aaa (bbb)") == [tools[1], tools[0], tools[2]]

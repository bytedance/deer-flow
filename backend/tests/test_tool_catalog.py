"""Unit tests for ToolCatalog BM25 and regex search."""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.tools.catalog import ToolCatalog, ToolEntry, _json_type_to_python, _tokenize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyInput(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, description="Max results")


class RichInput(BaseModel):
    """Input schema with various types for testing parameter extraction."""

    name: str = Field(description="The name")
    count: int = Field(description="Number of items")
    score: float = Field(default=0.5, description="Score value")
    enabled: bool = Field(default=True, description="Whether enabled")
    tags: list[str] = Field(default_factory=list, description="List of tags")
    metadata: dict = Field(default_factory=dict, description="Extra metadata")


class DummyTool(BaseTool):
    """Minimal tool for testing catalog indexing."""

    name: str = "dummy"
    description: str = "A dummy tool"
    args_schema: type[BaseModel] | None = None

    def _run(self, **kwargs):
        return "ok"


def _make_tool(name: str, description: str, schema: type[BaseModel] | None = None) -> DummyTool:
    return DummyTool(name=name, description=description, args_schema=schema)


def _make_catalog(
    tools: list[DummyTool],
    core_names: set[str] | None = None,
    mcp_map: dict[str, str] | None = None,
) -> ToolCatalog:
    return ToolCatalog.from_tools(
        tools=tools,
        core_tool_names=core_names or set(),
        mcp_server_map=mcp_map,
    )


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_basic_splitting(self):
        tokens = _tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_underscore_splitting(self):
        tokens = _tokenize("web_search_tool")
        assert tokens == ["web", "search", "tool"]

    def test_hyphen_splitting(self):
        tokens = _tokenize("clinical-trials-search")
        assert tokens == ["clinical", "trials", "search"]

    def test_mixed_separators(self):
        tokens = _tokenize("search/web_data-analysis")
        assert tokens == ["search", "web", "data", "analysis"]

    def test_case_lowering(self):
        tokens = _tokenize("WebSearch TOOL")
        assert tokens == ["websearch", "tool"]

    def test_empty_string(self):
        tokens = _tokenize("")
        assert tokens == []


# ---------------------------------------------------------------------------
# ToolCatalog.from_tools
# ---------------------------------------------------------------------------


class TestCatalogFromTools:
    def test_basic_indexing(self):
        tools = [
            _make_tool("bash", "Execute shell commands"),
            _make_tool("web_search", "Search the web for information"),
        ]
        catalog = _make_catalog(tools)

        assert len(catalog.entries) == 2
        assert "bash" in catalog.entries
        assert "web_search" in catalog.entries

    def test_parameter_extraction(self):
        tool = _make_tool("search", "Search things", schema=DummyInput)
        catalog = _make_catalog([tool])

        entry = catalog.entries["search"]
        assert "query" in entry.parameter_names
        assert "limit" in entry.parameter_names

    def test_core_tool_marking(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("mcp_stock", "Get stock prices"),
        ]
        catalog = _make_catalog(tools, core_names={"bash"})

        assert catalog.entries["bash"].is_core is True
        assert catalog.entries["mcp_stock"].is_core is False

    def test_mcp_server_mapping(self):
        tools = [
            _make_tool("ncbi_search", "Search NCBI"),
            _make_tool("bash", "Run commands"),
        ]
        catalog = _make_catalog(tools, mcp_map={"ncbi_search": "ncbi"})

        assert catalog.entries["ncbi_search"].server_name == "ncbi"
        assert catalog.entries["bash"].server_name is None

    def test_skips_non_basetool(self):
        tools = [
            _make_tool("bash", "Run commands"),
            {"name": "dict_tool"},  # type: ignore[list-item]
        ]
        catalog = _make_catalog(tools)
        assert len(catalog.entries) == 1

    def test_empty_tools(self):
        catalog = _make_catalog([])
        assert len(catalog.entries) == 0

    def test_tokens_populated(self):
        tool = _make_tool("web_search", "Search the web")
        catalog = _make_catalog([tool])

        entry = catalog.entries["web_search"]
        assert len(entry.tokens) > 0
        assert "web" in entry.tokens
        assert "search" in entry.tokens


# ---------------------------------------------------------------------------
# BM25 search
# ---------------------------------------------------------------------------


class TestBM25Search:
    @pytest.fixture()
    def catalog(self) -> ToolCatalog:
        tools = [
            _make_tool("ncbi_search", "Search NCBI PubMed for biomedical research articles"),
            _make_tool("clinical_trials_search", "Search ClinicalTrials.gov for clinical studies"),
            _make_tool("stock_price", "Get real-time stock market prices and financial data"),
            _make_tool("bash", "Execute shell commands in the sandbox"),
            _make_tool("web_search", "Search the web for general information"),
        ]
        return _make_catalog(tools, core_names={"bash"})

    def test_relevant_results_ranked_first(self, catalog: ToolCatalog):
        results = catalog.search_bm25("biomedical research articles")
        assert len(results) > 0
        assert results[0].name == "ncbi_search"

    def test_clinical_trials_query(self, catalog: ToolCatalog):
        results = catalog.search_bm25("clinical trials studies")
        assert len(results) > 0
        assert results[0].name == "clinical_trials_search"

    def test_financial_query(self, catalog: ToolCatalog):
        results = catalog.search_bm25("stock market price financial")
        assert len(results) > 0
        assert results[0].name == "stock_price"

    def test_max_results_limit(self, catalog: ToolCatalog):
        results = catalog.search_bm25("search", max_results=2)
        assert len(results) <= 2

    def test_empty_query(self, catalog: ToolCatalog):
        results = catalog.search_bm25("")
        assert results == []

    def test_no_match_query(self, catalog: ToolCatalog):
        results = catalog.search_bm25("quantum cryptography blockchain")
        # May return some results with low scores, but nothing highly relevant
        # The important thing is it doesn't crash
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Regex search
# ---------------------------------------------------------------------------


class TestRegexSearch:
    @pytest.fixture()
    def catalog(self) -> ToolCatalog:
        tools = [
            _make_tool("ncbi_search", "Search NCBI"),
            _make_tool("ncbi_fetch", "Fetch records from NCBI"),
            _make_tool("clinical_trials_search", "Search clinical trials"),
            _make_tool("bash", "Execute commands"),
        ]
        return _make_catalog(tools)

    def test_exact_name_match(self, catalog: ToolCatalog):
        results = catalog.search_regex("ncbi_search")
        assert len(results) >= 1
        assert any(e.name == "ncbi_search" for e in results)

    def test_pattern_match(self, catalog: ToolCatalog):
        results = catalog.search_regex("ncbi.*")
        assert len(results) >= 2
        names = {e.name for e in results}
        assert "ncbi_search" in names
        assert "ncbi_fetch" in names

    def test_description_match(self, catalog: ToolCatalog):
        results = catalog.search_regex("clinical trials")
        assert len(results) >= 1
        assert any(e.name == "clinical_trials_search" for e in results)

    def test_case_insensitive(self, catalog: ToolCatalog):
        results = catalog.search_regex("NCBI")
        assert len(results) >= 1

    def test_max_results(self, catalog: ToolCatalog):
        results = catalog.search_regex(".*", max_results=2)
        assert len(results) == 2

    def test_invalid_regex(self, catalog: ToolCatalog):
        results = catalog.search_regex("[invalid")
        assert results == []


# ---------------------------------------------------------------------------
# Unified search (auto mode)
# ---------------------------------------------------------------------------


class TestUnifiedSearch:
    @pytest.fixture()
    def catalog(self) -> ToolCatalog:
        tools = [
            _make_tool("web_search", "Search the web"),
            _make_tool("ncbi_search", "Search NCBI"),
        ]
        return _make_catalog(tools)

    def test_auto_mode_regex(self, catalog: ToolCatalog):
        """Queries with regex special chars should use regex mode."""
        results = catalog.search("ncbi.*", mode="auto")
        assert len(results) >= 1

    def test_auto_mode_bm25(self, catalog: ToolCatalog):
        """Plain queries should use BM25 mode."""
        results = catalog.search("search the web", mode="auto")
        assert len(results) >= 1

    def test_explicit_regex_mode(self, catalog: ToolCatalog):
        results = catalog.search("web", mode="regex")
        assert len(results) >= 1

    def test_explicit_bm25_mode(self, catalog: ToolCatalog):
        results = catalog.search("web", mode="bm25")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Deferred entries
# ---------------------------------------------------------------------------


class TestDeferredEntries:
    def test_get_deferred_entries(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("web_search", "Search the web"),
            _make_tool("mcp_tool_1", "MCP tool 1"),
            _make_tool("mcp_tool_2", "MCP tool 2"),
        ]
        catalog = _make_catalog(tools, core_names={"bash", "web_search"})

        deferred = catalog.get_deferred_entries()
        assert len(deferred) == 2
        names = {e.name for e in deferred}
        assert names == {"mcp_tool_1", "mcp_tool_2"}

    def test_no_deferred_when_all_core(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("web_search", "Search the web"),
        ]
        catalog = _make_catalog(tools, core_names={"bash", "web_search"})

        deferred = catalog.get_deferred_entries()
        assert len(deferred) == 0


# ---------------------------------------------------------------------------
# Catalog summary
# ---------------------------------------------------------------------------


class TestCatalogSummary:
    def test_format_with_servers(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("ncbi_search", "Search NCBI"),
            _make_tool("ncbi_fetch", "Fetch from NCBI"),
            _make_tool("stock_price", "Get stock prices"),
        ]
        catalog = _make_catalog(
            tools,
            core_names={"bash"},
            mcp_map={"ncbi_search": "ncbi", "ncbi_fetch": "ncbi", "stock_price": "finance"},
        )

        summary = catalog.format_catalog_summary()
        assert "<tool_search_system>" in summary
        assert "ncbi" in summary
        assert "finance" in summary
        assert "tool_search" in summary

    def test_empty_when_no_deferred(self):
        tools = [_make_tool("bash", "Execute commands")]
        catalog = _make_catalog(tools, core_names={"bash"})

        summary = catalog.format_catalog_summary()
        assert summary == ""


# ---------------------------------------------------------------------------
# ToolEntry post_init
# ---------------------------------------------------------------------------


class TestToolEntry:
    def test_auto_tokenize(self):
        entry = ToolEntry(
            name="web_search",
            description="Search the web",
            parameter_names=["query"],
            server_name=None,
            is_core=False,
        )
        assert "web" in entry.tokens
        assert "search" in entry.tokens
        assert "query" in entry.tokens

    def test_custom_tokens(self):
        entry = ToolEntry(
            name="test",
            description="test",
            parameter_names=[],
            server_name=None,
            is_core=False,
            tokens=["custom", "tokens"],
        )
        assert entry.tokens == ["custom", "tokens"]


# ---------------------------------------------------------------------------
# merge_discovered_tools reducer
# ---------------------------------------------------------------------------


class TestMergeDiscoveredTools:
    def test_both_none(self):
        from src.agents.thread_state import merge_discovered_tools
        assert merge_discovered_tools(None, None) == []

    def test_existing_none(self):
        from src.agents.thread_state import merge_discovered_tools
        assert merge_discovered_tools(None, ["a", "b"]) == ["a", "b"]

    def test_new_none(self):
        from src.agents.thread_state import merge_discovered_tools
        assert merge_discovered_tools(["a", "b"], None) == ["a", "b"]

    def test_union(self):
        from src.agents.thread_state import merge_discovered_tools
        result = merge_discovered_tools(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_preserves_order(self):
        from src.agents.thread_state import merge_discovered_tools
        result = merge_discovered_tools(["x", "y"], ["z", "x"])
        assert result == ["x", "y", "z"]

    def test_deduplicates(self):
        from src.agents.thread_state import merge_discovered_tools
        result = merge_discovered_tools(["a", "a"], ["a"])
        assert result == ["a"]


# ---------------------------------------------------------------------------
# JSON type mapping
# ---------------------------------------------------------------------------


class TestJsonTypeToPython:
    def test_string(self):
        assert _json_type_to_python({"type": "string"}) == "str"

    def test_integer(self):
        assert _json_type_to_python({"type": "integer"}) == "int"

    def test_number(self):
        assert _json_type_to_python({"type": "number"}) == "float"

    def test_boolean(self):
        assert _json_type_to_python({"type": "boolean"}) == "bool"

    def test_null(self):
        assert _json_type_to_python({"type": "null"}) == "None"

    def test_array_of_strings(self):
        assert _json_type_to_python({"type": "array", "items": {"type": "string"}}) == "list[str]"

    def test_array_of_ints(self):
        assert _json_type_to_python({"type": "array", "items": {"type": "integer"}}) == "list[int]"

    def test_array_no_items(self):
        assert _json_type_to_python({"type": "array"}) == "list[Any]"

    def test_object(self):
        assert _json_type_to_python({"type": "object"}) == "dict"

    def test_any_of_union(self):
        result = _json_type_to_python({"anyOf": [{"type": "string"}, {"type": "integer"}]})
        assert result == "str | int"

    def test_any_of_with_null(self):
        # Optional[str] → anyOf [string, null]
        result = _json_type_to_python({"anyOf": [{"type": "string"}, {"type": "null"}]})
        assert result == "str"

    def test_unknown_type(self):
        assert _json_type_to_python({"type": "custom_thing"}) == "Any"

    def test_missing_type(self):
        assert _json_type_to_python({}) == "Any"


# ---------------------------------------------------------------------------
# ToolParameterSchema extraction
# ---------------------------------------------------------------------------


class TestParameterSchemaExtraction:
    def test_basic_schema_extraction(self):
        tool = _make_tool("search", "Search things", schema=DummyInput)
        catalog = _make_catalog([tool])
        entry = catalog.entries["search"]

        assert len(entry.parameters) == 2
        param_map = {p.name: p for p in entry.parameters}

        query_param = param_map["query"]
        assert query_param.type_hint == "str"
        assert query_param.description == "Search query"
        assert query_param.required is True
        assert query_param.default is None

        limit_param = param_map["limit"]
        assert limit_param.type_hint == "int"
        assert limit_param.description == "Max results"
        assert limit_param.required is False
        assert limit_param.default == "10"

    def test_rich_schema_extraction(self):
        tool = _make_tool("rich_tool", "Tool with many types", schema=RichInput)
        catalog = _make_catalog([tool])
        entry = catalog.entries["rich_tool"]

        param_map = {p.name: p for p in entry.parameters}

        assert param_map["name"].type_hint == "str"
        assert param_map["name"].required is True

        assert param_map["count"].type_hint == "int"
        assert param_map["count"].required is True

        assert param_map["score"].type_hint == "float"
        assert param_map["score"].required is False
        assert param_map["score"].default == "0.5"

        assert param_map["enabled"].type_hint == "bool"
        assert param_map["enabled"].required is False
        assert param_map["enabled"].default == "True"

        assert param_map["tags"].type_hint == "list[str]"
        assert param_map["metadata"].type_hint == "dict"

    def test_no_schema_no_parameters(self):
        tool = _make_tool("simple", "No schema")
        catalog = _make_catalog([tool])
        entry = catalog.entries["simple"]
        assert entry.parameters == []
        assert entry.parameter_names == []

    def test_parameter_names_match_parameters(self):
        tool = _make_tool("search", "Search", schema=DummyInput)
        catalog = _make_catalog([tool])
        entry = catalog.entries["search"]
        assert set(entry.parameter_names) == {p.name for p in entry.parameters}


# ---------------------------------------------------------------------------
# get_tools_by_server
# ---------------------------------------------------------------------------


class TestGetToolsByServer:
    def test_groups_by_server(self):
        tools = [
            _make_tool("ncbi_search", "Search NCBI"),
            _make_tool("ncbi_fetch", "Fetch from NCBI"),
            _make_tool("stock_price", "Get stock prices"),
            _make_tool("bash", "Execute commands"),
        ]
        catalog = _make_catalog(
            tools,
            mcp_map={"ncbi_search": "ncbi", "ncbi_fetch": "ncbi", "stock_price": "finance"},
        )

        by_server = catalog.get_tools_by_server()

        assert "ncbi" in by_server
        assert len(by_server["ncbi"]) == 2
        ncbi_names = {e.name for e in by_server["ncbi"]}
        assert ncbi_names == {"ncbi_search", "ncbi_fetch"}

        assert "finance" in by_server
        assert len(by_server["finance"]) == 1
        assert by_server["finance"][0].name == "stock_price"

        # Non-MCP tool goes under None
        assert None in by_server
        assert len(by_server[None]) == 1
        assert by_server[None][0].name == "bash"

    def test_empty_catalog(self):
        catalog = _make_catalog([])
        assert catalog.get_tools_by_server() == {}

    def test_all_none_servers(self):
        tools = [
            _make_tool("bash", "Run commands"),
            _make_tool("ls", "List files"),
        ]
        catalog = _make_catalog(tools)
        by_server = catalog.get_tools_by_server()
        assert list(by_server.keys()) == [None]
        assert len(by_server[None]) == 2

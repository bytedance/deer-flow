"""Opt-in literal intent search for deferred tools."""

import pytest
from langchain_core.tools import StructuredTool

from deerflow.tools.builtins.tool_search import DeferredToolCatalog, build_tool_search_tool


def make_tool(name, description="A deferred tool."):
    return StructuredTool.from_function(lambda query="": query, name=name, description=description)


@pytest.mark.parametrize("query", ["keywords:notebook jupyter", "keywords:JUPYTER notebook", "keywords: notebook\tJupyter notebook "])
def test_keywords_find_reordered_notebook_intent(query):
    notebook = make_tool("jupyter_notebook", "Create and edit notebooks in Jupyter")
    catalog = DeferredToolCatalog((make_tool("unrelated"), notebook))
    assert catalog.search(query) == [notebook]


def test_keywords_rank_coverage_then_name_hits_with_stable_ties():
    partial = make_tool("notebook")
    description = make_tool("editor", "Jupyter notebook")
    mixed = make_tool("jupyter", "Edit a notebook")
    first = make_tool("jupyter_notebook")
    second = make_tool("notebook_jupyter")
    catalog = DeferredToolCatalog((partial, description, mixed, first, second))
    expected = [first, second, mixed, description, partial]
    assert catalog.search("keywords:notebook jupyter") == expected
    assert catalog.search("keywords:jupyter notebook") == expected
    assert catalog.search("keywords:jupyter jupyter notebook") == expected


@pytest.mark.parametrize("query", ["keywords:", "keywords:   ", "keywords:unmatched"])
def test_keywords_empty_and_unmatched_return_empty(query):
    assert DeferredToolCatalog((make_tool("jupyter_notebook"),)).search(query) == []


def test_keywords_treat_regex_metacharacters_literally():
    literal = make_tool("literal", "Use a+b and [draft]")
    other = make_tool("aaab", "draft")
    catalog = DeferredToolCatalog((other, literal))
    assert catalog.search("keywords:a+b [draft]") == [literal]
    assert catalog.search("keywords:.*") == []
    assert catalog.search("a+b") == [other]


def test_keywords_casefold_unicode():
    tool = make_tool("strasse", "笔记本")
    assert DeferredToolCatalog((tool,)).search("keywords:STRAẞE 笔记本") == [tool]


def test_keywords_cap_preserves_catalog_order():
    tools = tuple(make_tool(f"notebook_{i}") for i in range(8))
    catalog = DeferredToolCatalog(tools)
    assert catalog.search("keywords:notebook") == list(tools[:5])
    assert catalog.search("select:" + ",".join(t.name for t in tools)) == list(tools)
    assert catalog.search("select:NOTEBOOK_0") == []


def test_keywords_bound_query_characters_and_unique_terms():
    target = make_tool("target")
    catalog = DeferredToolCatalog((target,))
    assert catalog.search("keywords:" + "x" * 256 + " target") == []
    assert catalog.search("keywords:" + " ".join(f"x{i}" for i in range(16)) + " target") == []
    assert catalog.search("keywords:" + "x " * 16 + "target") == [target]


def test_keywords_do_not_change_legacy_required_name_or_regex():
    tool = make_tool("jupyter_notebook", "Create and edit notebooks in Jupyter")
    catalog = DeferredToolCatalog((tool,))
    assert catalog.search("notebook jupyter") == []
    assert catalog.search("jupyter.*notebook") == [tool]
    assert catalog.search("+jupyter notebook") == [tool]


def test_keywords_promote_full_schema_through_tool_call():
    notebook = make_tool("jupyter_notebook", "Create and edit notebooks in Jupyter")
    catalog = DeferredToolCatalog((notebook,))
    search = build_tool_search_tool(catalog)
    result = search.invoke({"type": "tool_call", "id": "keyword-call", "name": "tool_search", "args": {"query": "keywords:notebook jupyter"}})
    assert result.update["promoted"] == {"catalog_hash": catalog.hash, "names": [notebook.name]}
    assert '"name": "jupyter_notebook"' in result.update["messages"][0].content

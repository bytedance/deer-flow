import pytest
from langchain_core.tools import tool as as_tool

from deerflow.tools.builtins.tool_search import DeferredToolCatalog


@as_tool
def alpha_search(query: str) -> str:
    "Search alpha records by query."
    return query


@as_tool
def beta_translate(text: str) -> str:
    "Translate beta text."
    return text


@pytest.fixture
def catalog() -> DeferredToolCatalog:
    return DeferredToolCatalog((alpha_search, beta_translate))


def test_names(catalog):
    assert catalog.names == frozenset({"alpha_search", "beta_translate"})


def test_search_select(catalog):
    got = catalog.search("select:alpha_search")
    assert [t.name for t in got] == ["alpha_search"]


def test_search_plus_keyword(catalog):
    got = catalog.search("+beta translate")
    assert [t.name for t in got] == ["beta_translate"]


def test_search_regex_on_description(catalog):
    got = catalog.search("translate")
    assert "beta_translate" in [t.name for t in got]


def test_search_invalid_regex_falls_back_to_literal():
    @as_tool
    def calc(expr: str) -> str:
        "Compute sum(a, b) style expressions."
        return expr

    cat = DeferredToolCatalog((calc, alpha_search))
    # "sum(" is an invalid regex (unbalanced paren). search() must not raise; it
    # falls back to a literal match, which finds calc's "sum(" in its description.
    assert [t.name for t in cat.search("sum(")] == ["calc"]
    # A literal with no match is deterministically empty (and still must not raise).
    assert cat.search("zzz(") == []


def test_hash_stable_across_instances():
    c1 = DeferredToolCatalog((alpha_search, beta_translate))
    c2 = DeferredToolCatalog((beta_translate, alpha_search))
    assert c1.hash == c2.hash


def test_hash_changes_with_membership():
    c1 = DeferredToolCatalog((alpha_search, beta_translate))
    c2 = DeferredToolCatalog((alpha_search,))
    assert c1.hash != c2.hash

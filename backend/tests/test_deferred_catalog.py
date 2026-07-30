import pytest
from langchain_core.tools import StructuredTool
from langchain_core.tools import tool as as_tool

from deerflow.tools.builtins.tool_search import MAX_RESULTS, DeferredToolCatalog


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


def _make_tool(name: str):
    @as_tool(name)
    def _t(query: str) -> str:
        "A searchable deferred tool."
        return query

    return _t


@pytest.fixture
def wide_catalog() -> DeferredToolCatalog:
    """More tools than ``MAX_RESULTS`` so the cap boundary is reachable."""
    return DeferredToolCatalog(tuple(_make_tool(f"tool_{c}") for c in "abcdefgh"))


def test_search_select_returns_all_requested(wide_catalog):
    """``select:`` returns every named tool without capping.

    Mirrors ``test_skill_catalog.py::test_select_returns_all_requested``. The
    two catalogs share the same query grammar and the same ``MAX_RESULTS = 5``;
    ``select:`` names its targets explicitly, so capping it silently drops
    schemas the model asked for by name -- and picks the survivors by catalog
    order, not request order.
    """
    wanted = [f"tool_{c}" for c in "abcdef"]  # 6 > MAX_RESULTS
    got = [t.name for t in wide_catalog.search("select:" + ",".join(wanted))]

    assert got == wanted


@pytest.mark.parametrize("query", ["+tool_", "searchable"])
def test_search_ranked_modes_stay_capped(wide_catalog, query):
    """Only ``select:`` is uncapped; the ranked modes keep their ``MAX_RESULTS`` cap.

    Guards the fix from being widened into the branches whose docstring does
    promise "up to max_results best matches".
    """
    got = wide_catalog.search(query)

    assert len(got) == MAX_RESULTS


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


def test_search_empty_query_returns_empty(catalog):
    # An empty / whitespace-only query is meaningless; rather than let the empty
    # regex match every tool, search() returns nothing so the model gets a clear
    # "no match" signal and re-queries instead of acting on noise.
    assert catalog.search("") == []
    assert catalog.search("   ") == []


def test_search_bare_plus_returns_empty(catalog):
    # A "+" prefix with no required token is malformed model input. It must
    # return no matches, not raise IndexError on parts[0]. " + " strips to "+",
    # so it routes here too and must be handled the same way.
    assert catalog.search("+") == []
    assert catalog.search(" + ") == []
    assert catalog.search("+   ") == []


def test_hash_stable_across_instances():
    c1 = DeferredToolCatalog((alpha_search, beta_translate))
    c2 = DeferredToolCatalog((beta_translate, alpha_search))
    assert c1.hash == c2.hash


def test_hash_changes_with_membership():
    c1 = DeferredToolCatalog((alpha_search, beta_translate))
    c2 = DeferredToolCatalog((alpha_search,))
    assert c1.hash != c2.hash


def test_search_select_not_capped_at_max_results():
    """select: must return ALL requested tools, even when >MAX_RESULTS."""
    tools = tuple(StructuredTool.from_function(func=lambda q="": q, name=f"tool_{i:02d}", description=f"Tool {i}") for i in range(8))
    cat = DeferredToolCatalog(tools)
    names_csv = ",".join(f"tool_{i:02d}" for i in range(8))
    got = cat.search(f"select:{names_csv}")
    assert len(got) == 8
    assert [t.name for t in got] == [f"tool_{i:02d}" for i in range(8)]

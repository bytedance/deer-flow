"""Ownership gate for shared ``max_results`` coercion and deferred patterns.

#5865 audited every bundled provider's ``max_results`` coercion against the
#5852 rule and found seven copies that diverged on booleans, non-integral
floats and ``OverflowError``. Those audits had to be read file by file because
each provider owned its own copy of the answer.

``deerflow.community.search_max_results`` owns coercion for the migrated
providers. These tests pin three things the
refactor must not silently give back:

1. the shared function's behaviour, value by value (the bar itself);
2. that a folded provider does not grow a private copy again, and still warns
   under its own historical label and its own logger;
3. that the known local coercion patterns match the declared deferred providers.
   The AST census recognizes private helpers through their code and call sites,
   plus inline integer assignments; it ignores documentation. New copies using
   those patterns and deferred providers migrating away both fail. It is a
   source-pattern gate, not a semantic proof of arbitrary provider code.
"""

import ast
import logging
import sys
from pathlib import Path

import pytest

from deerflow.community.ddg_search import tools as ddg_search_tools
from deerflow.community.fastcrw import tools as fastcrw_tools
from deerflow.community.firecrawl import tools as firecrawl_tools
from deerflow.community.image_search import tools as image_search_tools
from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.youcom import tools as youcom_tools

COMMUNITY_ROOT = Path(ddg_search_tools.__file__).resolve().parent.parent

# Providers folded onto the shared owner, with the exact provider text their
# warning used before the extraction. The label is kept so existing log-based
# tests (tests/test_fastcrw_tools.py, tests/test_firecrawl_tools.py) stay
# meaningful; the module is imported so a coercer cannot come back at runtime.
SHARED_OWNER_PROVIDERS = {
    "ddg_search": ("DDG Search", ddg_search_tools),
    "image_search": ("DDG image search", image_search_tools),
    "fastcrw": ("fastCRW", fastcrw_tools),
    "firecrawl": ("Firecrawl", firecrawl_tools),
    "youcom": ("You.com", youcom_tools),
}

# Providers that still normalize locally, including Exa's generic helper and
# SearXNG's inline validation. Their differing bounds or rejection profiles mean
# folding them is a behaviour change
# that #5865's follow-up has to settle first. The equality assertion in
# test_deferral_list_matches_the_providers_that_still_copy is what forces this
# list to shrink as they land -- see PRs #5866 / #5867.
DEFERRED_PROVIDERS = {
    "brave",
    "exa",
    "groundroute",
    "searxng",
    "serper",
    "serply",
    "sofya",
    "tencent_wsa",
}


def _module_ast(provider: str) -> ast.Module:
    path = COMMUNITY_ROOT / provider / "tools.py"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _code_nodes(tree: ast.AST):
    """Walk executable syntax, excluding module/class/function docstrings."""
    yield tree
    docstring = None
    if isinstance(tree, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(tree) is not None:
        docstring = tree.body[0]
    for child in ast.iter_child_nodes(tree):
        if child is not docstring:
            yield from _code_nodes(child)


def _references_max_results(tree: ast.AST) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id == "max_results") or (isinstance(node, ast.Constant) and isinstance(node.value, str) and "max_results" in node.value) or (isinstance(node, ast.keyword) and node.arg == "max_results")
        for node in _code_nodes(tree)
    )


def _local_coercer_names(tree: ast.Module) -> set[str]:
    """Find local helpers and inline integer assignments for ``max_results``."""
    calls = [node for node in _code_nodes(tree) if isinstance(node, ast.Call)]
    called_for_max_results = {getattr(call.func, "id", None) for call in calls if _references_max_results(call)}
    owned: set[str] = set()
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function.name.startswith("_coerce") and ("max_results" in function.name or _references_max_results(function) or function.name in called_for_max_results):
            owned.add(function.name)
        for node in _code_nodes(function):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if node.value is not None and any(_references_max_results(target) for target in targets):
                if any(isinstance(call, ast.Call) and getattr(call.func, "id", None) == "int" for call in _code_nodes(node.value)):
                    owned.add(function.name)
    return owned


def _shared_calls(tree: ast.Module) -> list[ast.Call]:
    """Every call to the shared owner, with its keyword arguments intact."""
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "coerce_max_results":
            calls.append(node)
    return calls


def _imports_shared_owner(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "deerflow.community.search_max_results":
            return True
    return False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        ("5", 5),
        (4.0, 4),  # integral floats are a valid way to write 4
        (True, DEFAULT_MAX_RESULTS),  # bool is an int subclass: never 1
        (False, DEFAULT_MAX_RESULTS),
        (3.5, DEFAULT_MAX_RESULTS),  # never silently truncated to 3
        ("abc", DEFAULT_MAX_RESULTS),
        ("", DEFAULT_MAX_RESULTS),
        (None, DEFAULT_MAX_RESULTS),
        (0, DEFAULT_MAX_RESULTS),
        (-2, DEFAULT_MAX_RESULTS),
        (float("inf"), DEFAULT_MAX_RESULTS),  # int() would raise OverflowError
        (10_000, 10_000),  # no upper bound: that policy is still per-provider
    ],
)
def test_shared_owner_is_the_bar_for_every_value(value, expected, caplog):
    with caplog.at_level(logging.WARNING):
        assert coerce_max_results(value, provider="Probe", logger=logging.getLogger("probe")) == expected


def test_every_folded_provider_delegates_instead_of_copying():
    for provider, (_label, module) in sorted(SHARED_OWNER_PROVIDERS.items()):
        tree = _module_ast(provider)
        assert not _local_coercer_names(tree), f"{provider} grew a private max_results coercer again"
        assert _imports_shared_owner(tree), f"{provider} no longer imports the shared owner"
        assert not any(name.startswith("_coerce_max_results") for name in vars(module)), f"{provider} rebound a private coercer"


def test_folded_providers_keep_their_historical_warning_label():
    for provider, (label, _module) in sorted(SHARED_OWNER_PROVIDERS.items()):
        calls = _shared_calls(_module_ast(provider))
        assert calls, f"{provider} no longer calls the shared owner"
        for call in calls:
            kwargs = {kw.arg: kw.value for kw in call.keywords}
            assert isinstance(kwargs["provider"], ast.Constant), f"{provider}: provider label must stay a literal"
            assert kwargs["provider"].value == label, f"{provider}: warning label drifted to {kwargs['provider'].value!r}"
            assert getattr(kwargs["logger"], "id", None) == "logger", f"{provider}: must pass its module logger"


def test_warnings_stay_on_the_calling_provider_logger(caplog):
    """Records must keep module attribution: tests/test_ddg_search_tools.py filters on ``record.name``."""
    provider_logger = logging.getLogger("deerflow.community.example")
    with caplog.at_level(logging.WARNING):
        coerce_max_results("abc", provider="Example", logger=provider_logger)
    assert [record.name for record in caplog.records] == ["deerflow.community.example"]
    assert "Invalid Example max_results='abc'; using default 5" in caplog.text


def test_deferral_list_matches_the_providers_that_still_copy():
    found = set()
    for tools_path in sorted(COMMUNITY_ROOT.glob("*/tools.py")):
        provider = tools_path.parent.name
        if provider in SHARED_OWNER_PROVIDERS:
            continue
        if _local_coercer_names(_module_ast(provider)):
            found.add(provider)
    assert found == DEFERRED_PROVIDERS, f"providers hand-rolling max_results coercion drifted; newly copied: {sorted(found - DEFERRED_PROVIDERS)}, folded but still declared: {sorted(DEFERRED_PROVIDERS - found)}"


@pytest.mark.parametrize("provider", ["exa", "searxng"])
def test_census_includes_generic_and_inline_provider_coercion(provider):
    assert _local_coercer_names(_module_ast(provider)), f"{provider}'s existing max_results normalization escaped the census"


@pytest.mark.parametrize(
    "source",
    [
        "def _coerce_max_results(value):\n    return int(value)\n",
        'def _coerce_positive_int(value, default, option):\n    return int(value)\n\ndef search(config):\n    return _coerce_positive_int(config.get("max_results"), 5, "max_results")\n',
        'def _coerce_positive_int(value, *, option):\n    return int(value)\n\ndef search(config):\n    return _coerce_positive_int(config["max_results"], option="max_results")\n',
        (
            "async def search(config):\n"
            '    raw = config.get("max_results", 5)\n'
            "    try:\n"
            "        max_results = int(raw)\n"
            "    except ValueError:\n"
            '        logger.warning("Invalid Search max_results=%r; using default %s", raw, 5)\n'
            "    return max_results\n"
        ),
        "def search(raw):\n    max_results: int = int(raw)\n    return max_results\n",
    ],
    ids=["named-helper", "generic-positional", "generic-keyword", "inline-warning", "inline-without-warning"],
)
def test_census_rejects_undeclared_coercion_patterns(tmp_path, monkeypatch, source):
    provider_dir = tmp_path / "copycat"
    provider_dir.mkdir()
    (provider_dir / "tools.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "COMMUNITY_ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "DEFERRED_PROVIDERS", set())

    with pytest.raises(AssertionError, match="newly copied:.*copycat"):
        test_deferral_list_matches_the_providers_that_still_copy()


@pytest.mark.parametrize(
    "source",
    [
        'def _coerce_timeout(value):\n    """max_results is normalized elsewhere."""\n    return int(value)\n',
        'def _coerce_timeout(value):\n    """max_results"""\n    return int(value)\n\ndef search(config):\n    return _coerce_timeout(config.get("timeout", 30))\n',
        'def search(config):\n    max_results = config.get("max_results", 5)\n    return client.search(max_results=max_results)\n',
    ],
    ids=["docstring-mention", "exact-docstring", "pass-through"],
)
def test_census_ignores_documentation_and_pass_through(source):
    assert not _local_coercer_names(ast.parse(source))

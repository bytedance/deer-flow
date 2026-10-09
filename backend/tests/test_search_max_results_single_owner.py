"""Ownership gate: the bundled search providers share one ``max_results`` bar.

#5865 audited every bundled provider's ``max_results`` coercion against the
#5852 rule and found seven copies that diverged on booleans, non-integral
floats and ``OverflowError``. Those audits had to be read file by file because
each provider owned its own copy of the answer.

``deerflow.community.search_max_results`` is now that single owner, and the
providers whose copies were byte-identical have been folded into it. These
tests pin three things the refactor must not silently give back:

1. the shared function's behaviour, value by value (the bar itself);
2. that a folded provider does not grow a private copy again, and still warns
   under its own historical label and its own logger;
3. that the list of providers which *do* still hand-roll a coercer is exactly
   the declared one — a new provider copying the pattern, or a deferred one
   being folded away without updating this list, both fail.
"""

import ast
import logging
from pathlib import Path

import pytest

from deerflow.community.ddg_search import tools as ddg_search_tools
from deerflow.community.fastcrw import tools as fastcrw_tools
from deerflow.community.firecrawl import tools as firecrawl_tools
from deerflow.community.image_search import tools as image_search_tools
from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results

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
}

# Providers that still own a private ``_coerce_max_results``. Each has a
# *different* bound or rejection profile, so folding them is a behaviour change
# that #5865's follow-up has to settle first. The equality assertion in
# test_deferral_list_matches_the_providers_that_still_copy is what forces this
# list to shrink as they land -- see PRs #5866 / #5867.
DEFERRED_PROVIDERS = {
    "brave",
    "groundroute",
    "serper",
    "serply",
    "sofya",
    "tencent_wsa",
}


def _module_ast(provider: str) -> ast.Module:
    path = COMMUNITY_ROOT / provider / "tools.py"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _local_coercer_names(tree: ast.Module) -> set[str]:
    """Names of module-level functions that coerce ``max_results`` themselves."""
    owned = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_coerce") and "max_results" in ast.unparse(node):
            owned.add(node.name)
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

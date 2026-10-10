"""Unit tests for the DDGS community web search tool."""

import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.ddg_search import tools


@pytest.mark.parametrize(
    ("configured_limit", "env_value", "call_args", "expected_count", "warns"),
    [
        pytest.param("$DDG_TEST_MAX_RESULTS", "3", {"max_results": 2}, 3, False, id="environment-variable"),
        pytest.param("3", "3", {"max_results": 2}, 3, False, id="numeric-string"),
        pytest.param(3, "3", {"max_results": 2}, 3, False, id="integer-config"),
        pytest.param(None, "3", {"max_results": 2}, 2, False, id="call-argument"),
        pytest.param(None, "3", {}, 5, False, id="default"),
        pytest.param("$DDG_TEST_MAX_RESULTS", "abc", {"max_results": 2}, 5, True, id="invalid-env"),
        pytest.param("$DDG_TEST_MAX_RESULTS", "", {"max_results": 2}, 5, True, id="empty-env"),
        pytest.param("$DDG_TEST_MAX_RESULTS", "3.5", {"max_results": 2}, 5, True, id="fractional-env"),
        pytest.param(3.5, "3", {"max_results": 2}, 5, True, id="fractional-config"),
        pytest.param(True, "3", {"max_results": 2}, 5, True, id="boolean-config"),
        pytest.param("$DDG_TEST_MAX_RESULTS", "0", {"max_results": 2}, 5, True, id="zero-env"),
        pytest.param("$DDG_TEST_MAX_RESULTS", "-2", {"max_results": 2}, 5, True, id="negative-env"),
        pytest.param(0, "3", {}, 5, True, id="zero-config"),
        pytest.param(-2, "3", {}, 5, True, id="negative-config"),
        pytest.param([], "3", {}, 5, True, id="invalid-config-type"),
        pytest.param(None, "3", {"max_results": 0}, 5, True, id="zero-call-argument"),
        pytest.param(None, "3", {"max_results": -2}, 5, True, id="negative-call-argument"),
    ],
)
def test_web_search_tool_max_results_with_real_ddgs(monkeypatch, caplog, configured_limit, env_value, call_args, expected_count, warns) -> None:
    """Exercise SDK count arithmetic and slicing without contacting search engines."""
    from ddgs.ddgs import DDGS
    from ddgs.results import TextResult

    from deerflow.config.app_config import AppConfig
    from deerflow.config.tool_config import ToolConfig

    monkeypatch.setenv("DDG_TEST_MAX_RESULTS", env_value)
    caplog.set_level(logging.WARNING, logger=tools.__name__)
    raw_config = {"name": "web_search", "group": "web", "use": "deerflow.community.ddg_search.tools:web_search_tool"}
    if configured_limit is not None:
        raw_config["max_results"] = configured_limit
    tool_config = ToolConfig.model_validate(AppConfig.resolve_env_variables(raw_config))
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: tool_config))

    rows = [TextResult(title=f"Result {i}", href=f"https://example.com/{i}", body=f"Snippet {i}") for i in range(10)]
    engine = SimpleNamespace(provider="offline", name="offline", search=MagicMock(return_value=rows))
    monkeypatch.setattr(DDGS, "_get_network_client", lambda self: None)
    monkeypatch.setattr(DDGS, "_get_engines", lambda self, category, backend: [engine])

    parsed = json.loads(tools.web_search_tool.invoke({"query": "Result", **call_args}))

    assert "error" not in parsed
    assert parsed["total_results"] == len(parsed["results"]) == expected_count
    assert all(result["url"].startswith("https://example.com/") for result in parsed["results"])
    engine.search.assert_called_once()
    warnings = [record for record in caplog.records if record.name == tools.__name__ and record.levelno == logging.WARNING]
    assert len(warnings) == int(warns)
    if warns:
        assert "max_results" in warnings[0].getMessage()
        assert "using default 5" in warnings[0].getMessage()


def test_resolve_ddgs_region_maps_worldwide_chinese_query_for_wikipedia() -> None:
    assert tools._resolve_ddgs_region("\u4e16\u754c\u676f\u65b0\u95fb 2026", "wt-wt", "auto") == "cn-zh"


def test_resolve_ddgs_region_uses_english_fallback_for_worldwide_query() -> None:
    assert tools._resolve_ddgs_region("latest world cup news", "wt-wt", "auto") == "us-en"


def test_resolve_ddgs_region_preserves_worldwide_for_non_wikipedia_backend() -> None:
    assert tools._resolve_ddgs_region("latest world cup news", "wt-wt", "duckduckgo") == "wt-wt"


def test_resolve_ddgs_region_maps_common_ddg_locale_aliases() -> None:
    assert tools._resolve_ddgs_region("\u65e5\u672c \u30cb\u30e5\u30fc\u30b9", "jp-jp", "auto") == "jp-ja"
    assert tools._resolve_ddgs_region("\ud55c\uad6d \ub274\uc2a4", "kr-kr", "auto") == "kr-ko"
    assert tools._resolve_ddgs_region("\u53f0\u7063\u65b0\u805e", "tw-tzh", "auto") == "tw-zh"


def test_search_text_passes_wikipedia_safe_region_to_ddgs(monkeypatch) -> None:
    calls = {}

    class FakeDDGS:
        def __init__(self, timeout: int) -> None:
            calls["timeout"] = timeout

        def text(self, query: str, **kwargs):
            calls["query"] = query
            calls.update(kwargs)
            return [{"title": "Result", "href": "https://example.com", "body": "Snippet"}]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))

    results = tools._search_text("\u4e16\u754c\u676f\u65b0\u95fb 2026", backend="auto")

    assert results == [{"title": "Result", "href": "https://example.com", "body": "Snippet"}]
    assert calls["timeout"] == 30
    assert calls["region"] == "cn-zh"
    assert calls["backend"] == "auto"
    assert "timelimit" not in calls


@pytest.mark.parametrize(
    ("time_range", "expected_timelimit"),
    [
        ("day", "d"),
        ("week", "w"),
        ("month", "m"),
        ("year", "y"),
    ],
)
def test_search_text_maps_time_range_to_ddgs_timelimit(monkeypatch, time_range: str, expected_timelimit: str) -> None:
    calls = {}

    class FakeDDGS:
        def __init__(self, timeout: int) -> None:
            calls["timeout"] = timeout

        def text(self, query: str, **kwargs):
            calls["query"] = query
            calls.update(kwargs)
            return [{"title": "Result", "href": "https://example.com", "body": "Snippet"}]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))

    results = tools._search_text("latest release", backend="duckduckgo", time_range=time_range)

    assert results == [{"title": "Result", "href": "https://example.com", "body": "Snippet"}]
    assert calls["timelimit"] == expected_timelimit


def test_search_text_time_range_replaces_auto_with_filter_capable_backends(monkeypatch) -> None:
    calls = {}

    class FakeDDGS:
        def __init__(self, timeout: int) -> None:
            calls["timeout"] = timeout

        def text(self, query: str, **kwargs):
            calls.update(kwargs)
            return []

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))

    tools._search_text("latest release", backend="auto", time_range="week")

    assert calls["backend"] == "brave,duckduckgo,yahoo"
    assert calls["region"] == "wt-wt"
    assert calls["timelimit"] == "w"


@pytest.mark.parametrize(
    ("configured_backend", "expected_backend"),
    [
        ("wikipedia,duckduckgo,yandex", "duckduckgo"),
        ("wikipedia", "brave,duckduckgo,yahoo"),
        ("all", "brave,duckduckgo,yahoo"),
    ],
)
def test_search_text_time_range_excludes_explicit_filter_agnostic_backends(
    monkeypatch,
    configured_backend: str,
    expected_backend: str,
) -> None:
    calls = {}

    class FakeDDGS:
        def __init__(self, timeout: int) -> None:
            calls["timeout"] = timeout

        def text(self, query: str, **kwargs):
            calls.update(kwargs)
            return []

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))

    tools._search_text("latest release", backend=configured_backend, time_range="day")

    assert calls["backend"] == expected_backend


def test_web_search_tool_reads_ddgs_options_from_config() -> None:
    with patch("deerflow.community.ddg_search.tools.get_app_config") as mock_config:
        tool_config = MagicMock()
        tool_config.model_extra = {
            "max_results": 3,
            "region": "us-en",
            "safesearch": "off",
            "backend": "auto",
        }
        mock_config.return_value.get_tool_config.return_value = tool_config

        with patch("deerflow.community.ddg_search.tools._search_text") as mock_search:
            mock_search.return_value = [{"title": "Result", "href": "https://example.com", "body": "Snippet"}]

            result = tools.web_search_tool.invoke({"query": "latest news", "max_results": 8, "time_range": "week"})
            parsed = json.loads(result)

    assert parsed["total_results"] == 1
    mock_search.assert_called_once_with(
        query="latest news",
        max_results=3,
        region="us-en",
        safesearch="off",
        backend="auto",
        time_range="week",
    )


def test_web_search_tool_reports_search_failure_instead_of_no_results(monkeypatch, caplog) -> None:
    """A failed search must not masquerade as a genuinely empty result set."""

    class FailingDDGS:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def text(self, query: str, **kwargs):
            msg = "HTTP 429 Too Many Requests"
            raise RuntimeError(msg)

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FailingDDGS))
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))
    caplog.set_level(logging.ERROR, logger=tools.__name__)

    parsed = json.loads(tools.web_search_tool.invoke({"query": "latest news"}))

    assert parsed["query"] == "latest news"
    assert "No results found" not in parsed["error"]
    assert "429" in parsed["error"]
    assert any(record.getMessage().startswith("DuckDuckGo search failed") for record in caplog.records)


def test_web_search_tool_reports_missing_ddgs_dependency(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "ddgs", None)
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))

    parsed = json.loads(tools.web_search_tool.invoke({"query": "latest news"}))

    assert "not installed" in parsed["error"]


def test_search_text_raises_on_execution_failure(monkeypatch) -> None:
    from ddgs.exceptions import DDGSException

    class FailingDDGS:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def text(self, query: str, **kwargs):
            raise DDGSException("TimeoutException: search timed out")

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FailingDDGS))

    with pytest.raises(tools.DDGSearchError, match="timed out"):
        tools._search_text("latest news")


def test_search_text_keeps_sdk_no_results_sentinel_empty(monkeypatch) -> None:
    from ddgs.exceptions import DDGSException

    class EmptyDDGS:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def text(self, query: str, **kwargs):
            raise DDGSException("No results found.")

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=EmptyDDGS))

    assert tools._search_text("latest news") == []


def test_search_text_treats_only_the_exact_sdk_sentinel_as_empty(monkeypatch) -> None:
    """A failure message that merely embeds the sentinel phrase stays an error."""
    from ddgs.exceptions import DDGSException

    class AmbiguousDDGS:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def text(self, query: str, **kwargs):
            raise DDGSException("No results found for 'latest news': HTTP 429")

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=AmbiguousDDGS))

    with pytest.raises(tools.DDGSearchError, match="429"):
        tools._search_text("latest news")

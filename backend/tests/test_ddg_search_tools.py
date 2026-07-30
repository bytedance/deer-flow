"""Unit tests for the DDGS community web search tool."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deerflow.community.ddg_search import tools


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

            result = tools.web_search_tool.invoke({"query": "latest news", "max_results": 8})
            parsed = json.loads(result)

    assert parsed["total_results"] == 1
    mock_search.assert_called_once_with(
        query="latest news",
        max_results=3,
        region="us-en",
        safesearch="off",
        backend="auto",
    )

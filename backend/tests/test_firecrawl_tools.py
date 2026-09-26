"""Unit tests for the Firecrawl community tools."""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestCoerceMaxResults:
    def test_returns_value_when_valid_positive_int(self):
        from deerflow.community.firecrawl.tools import _coerce_max_results

        assert _coerce_max_results(3) == 3

    def test_returns_value_for_numeric_string(self):
        from deerflow.community.firecrawl.tools import _coerce_max_results

        assert _coerce_max_results("7") == 7

    def test_returns_value_for_integral_float(self):
        from deerflow.community.firecrawl.tools import _coerce_max_results

        assert _coerce_max_results(4.0) == 4

    @pytest.mark.parametrize(
        "raw",
        [True, False, 3.5, float("inf"), float("-inf"), "oops", None, 0, -2],
        ids=["bool-true", "bool-false", "fractional", "inf", "neg-inf", "string", "none", "zero", "negative"],
    )
    def test_falls_back_to_default_on_invalid_input(self, raw):
        from deerflow.community.firecrawl.tools import _coerce_max_results

        assert _coerce_max_results(raw) == 5


class TestWebSearchTool:
    @patch("deerflow.community.firecrawl.tools.FirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_search_uses_web_search_config(self, mock_get_app_config, mock_firecrawl_cls):
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "firecrawl-search-key", "max_results": 7}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = [
            MagicMock(title="Result", url="https://example.com", description="Snippet"),
        ]
        mock_firecrawl_cls.return_value.search.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})

        assert json.loads(result) == [
            {
                "title": "Result",
                "url": "https://example.com",
                "snippet": "Snippet",
            }
        ]
        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_search")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-search-key")
        mock_firecrawl_cls.return_value.search.assert_called_once_with("test query", limit=7)


class TestWebFetchTool:
    @patch("deerflow.community.firecrawl.tools.FirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_fetch_uses_web_fetch_config(self, mock_get_app_config, mock_firecrawl_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {"api_key": "firecrawl-fetch-key"}

        def get_tool_config(name):
            if name == "web_fetch":
                return fetch_config
            return None

        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Fetched markdown"
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_firecrawl_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_get_app_config.return_value.get_tool_config.assert_any_call("web_fetch")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-fetch-key")
        mock_firecrawl_cls.return_value.scrape.assert_called_once_with(
            "https://example.com",
            formats=["markdown"],
        )


class TestFirecrawlBaseUrl:
    @patch("deerflow.community.firecrawl.tools.FirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_fetch_passes_base_url_as_api_url(self, mock_get_app_config, mock_firecrawl_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {"base_url": "http://192.168.0.47:3002"}

        def get_tool_config(name):
            if name == "web_fetch":
                return fetch_config
            return None

        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Fetched markdown"
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_firecrawl_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_firecrawl_cls.assert_called_once_with(api_key=None, api_url="http://192.168.0.47:3002")

    @patch("deerflow.community.firecrawl.tools.FirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_search_passes_base_url_and_api_key(self, mock_get_app_config, mock_firecrawl_cls):
        search_config = MagicMock()
        search_config.model_extra = {
            "api_key": "firecrawl-key",
            "base_url": "http://192.168.0.47:3002",
            "max_results": 5,
        }
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = []
        mock_firecrawl_cls.return_value.search.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_search_tool

        web_search_tool.invoke({"query": "test query"})

        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-key", api_url="http://192.168.0.47:3002")

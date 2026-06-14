"""Unit tests for the fastCRW community tools."""

import json
from unittest.mock import MagicMock, patch


class TestWebSearchTool:
    @patch.dict("os.environ", {}, clear=False)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_search_uses_web_search_config(self, mock_get_app_config, mock_fastcrw_cls):
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "fastcrw-search-key", "max_results": 7}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = [
            MagicMock(title="Result", url="https://example.com", description="Snippet"),
        ]
        mock_fastcrw_cls.return_value.search.return_value = mock_result

        from deerflow.community.fastcrw.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})

        assert json.loads(result) == [
            {
                "title": "Result",
                "url": "https://example.com",
                "snippet": "Snippet",
            }
        ]
        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_search")
        mock_fastcrw_cls.assert_called_once_with(api_key="fastcrw-search-key", api_url="https://fastcrw.com/api")
        mock_fastcrw_cls.return_value.search.assert_called_once_with("test query", limit=7)


class TestWebFetchTool:
    @patch.dict("os.environ", {}, clear=False)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_fetch_uses_web_fetch_config(self, mock_get_app_config, mock_fastcrw_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {"api_key": "fastcrw-fetch-key", "base_url": "http://localhost:3000"}

        def get_tool_config(name):
            if name == "web_fetch":
                return fetch_config
            return None

        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Fetched markdown"
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_fastcrw_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.fastcrw.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_get_app_config.return_value.get_tool_config.assert_any_call("web_fetch")
        mock_fastcrw_cls.assert_called_once_with(api_key="fastcrw-fetch-key", api_url="http://localhost:3000")
        mock_fastcrw_cls.return_value.scrape.assert_called_once_with(
            "https://example.com",
            formats=["markdown"],
        )

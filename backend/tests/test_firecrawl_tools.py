"""Unit tests for the Firecrawl community tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWebSearchTool:
    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_search_uses_web_search_config(self, mock_get_app_config, mock_firecrawl_cls):
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "firecrawl-search-key", "max_results": 7}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = [
            MagicMock(title="Result", url="https://example.com", description="Snippet"),
        ]
        mock_firecrawl_cls.return_value.search = AsyncMock(return_value=mock_result)

        from deerflow.community.firecrawl.tools import web_search_tool

        result = await web_search_tool.ainvoke({"query": "test query"})

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
    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_fetch_uses_web_fetch_config(self, mock_get_app_config, mock_firecrawl_cls):
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
        mock_firecrawl_cls.return_value.scrape = AsyncMock(return_value=mock_scrape_result)

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = await web_fetch_tool.ainvoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_get_app_config.return_value.get_tool_config.assert_any_call("web_fetch")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-fetch-key")
        mock_firecrawl_cls.return_value.scrape.assert_called_once_with(
            "https://example.com",
            formats=["markdown"],
        )


class TestFirecrawlBaseUrl:
    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_fetch_passes_base_url_as_api_url(self, mock_get_app_config, mock_firecrawl_cls):
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
        mock_firecrawl_cls.return_value.scrape = AsyncMock(return_value=mock_scrape_result)

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = await web_fetch_tool.ainvoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_firecrawl_cls.assert_called_once_with(api_key=None, api_url="http://192.168.0.47:3002")

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_search_passes_base_url_and_api_key(self, mock_get_app_config, mock_firecrawl_cls):
        search_config = MagicMock()
        search_config.model_extra = {
            "api_key": "firecrawl-key",
            "base_url": "http://192.168.0.47:3002",
            "max_results": 5,
        }
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = []
        mock_firecrawl_cls.return_value.search = AsyncMock(return_value=mock_result)

        from deerflow.community.firecrawl.tools import web_search_tool

        await web_search_tool.ainvoke({"query": "test query"})

        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-key", api_url="http://192.168.0.47:3002")

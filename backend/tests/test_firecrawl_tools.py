"""Unit tests for the Firecrawl community tools."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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


class TestPerCallClientTeardown:
    """Every tool call builds a fresh client; its pooled async HTTP client must be closed."""

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_search_closes_the_per_call_client(self, mock_get_app_config, mock_firecrawl_cls):
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "firecrawl-search-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = []
        mock_firecrawl_cls.return_value.search = AsyncMock(return_value=mock_result)
        mock_firecrawl_cls.return_value._v2_client.async_http_client.close = AsyncMock()

        from deerflow.community.firecrawl.tools import web_search_tool

        await web_search_tool.ainvoke({"query": "test query"})

        mock_firecrawl_cls.return_value._v2_client.async_http_client.close.assert_awaited_once()

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_fetch_closes_the_per_call_client(self, mock_get_app_config, mock_firecrawl_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {"api_key": "firecrawl-fetch-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = fetch_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Fetched markdown"
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_firecrawl_cls.return_value.scrape = AsyncMock(return_value=mock_scrape_result)
        mock_firecrawl_cls.return_value._v2_client.async_http_client.close = AsyncMock()

        from deerflow.community.firecrawl.tools import web_fetch_tool

        await web_fetch_tool.ainvoke({"url": "https://example.com"})

        mock_firecrawl_cls.return_value._v2_client.async_http_client.close.assert_awaited_once()

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_search_closes_the_per_call_client_when_search_raises(self, mock_get_app_config, mock_firecrawl_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None
        client = mock_firecrawl_cls.return_value
        client.search = AsyncMock(side_effect=RuntimeError("search failed"))
        client._v2_client.async_http_client.close = AsyncMock()

        from deerflow.community.firecrawl.tools import web_search_tool

        result = await web_search_tool.ainvoke({"query": "test query"})

        assert result == "Error: search failed"
        client._v2_client.async_http_client.close.assert_awaited_once()

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_fetch_closes_the_per_call_client_when_scrape_raises(self, mock_get_app_config, mock_firecrawl_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None
        client = mock_firecrawl_cls.return_value
        client.scrape = AsyncMock(side_effect=RuntimeError("scrape failed"))
        client._v2_client.async_http_client.close = AsyncMock()

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = await web_fetch_tool.ainvoke({"url": "https://example.com"})

        assert result == "Error: scrape failed"
        client._v2_client.async_http_client.close.assert_awaited_once()

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_close_failure_does_not_hide_scrape_error(self, mock_get_app_config, mock_firecrawl_cls, caplog):
        mock_get_app_config.return_value.get_tool_config.return_value = None
        client = mock_firecrawl_cls.return_value
        client.scrape = AsyncMock(side_effect=RuntimeError("scrape failed"))
        client._v2_client.async_http_client.close = AsyncMock(side_effect=RuntimeError("close failed"))

        from deerflow.community.firecrawl.tools import web_fetch_tool

        with caplog.at_level(logging.WARNING, logger="deerflow.community.firecrawl.tools"):
            result = await web_fetch_tool.ainvoke({"url": "https://example.com"})

        assert result == "Error: scrape failed"
        client._v2_client.async_http_client.close.assert_awaited_once()
        assert "Failed to close the Firecrawl async HTTP pool" in caplog.text

    @pytest.mark.anyio
    async def test_teardown_reports_a_pool_without_close(self, caplog):
        from deerflow.community.firecrawl.tools import _aclose_firecrawl_client

        client = SimpleNamespace(_v2_client=SimpleNamespace(async_http_client=SimpleNamespace()))

        with caplog.at_level(logging.WARNING, logger="deerflow.community.firecrawl.tools"):
            await _aclose_firecrawl_client(client)

        assert "Firecrawl async HTTP pool has no close method" in caplog.text

    @pytest.mark.anyio
    async def test_teardown_accepts_a_synchronous_close(self, caplog):
        from deerflow.community.firecrawl.tools import _aclose_firecrawl_client

        close = Mock()
        client = SimpleNamespace(_v2_client=SimpleNamespace(async_http_client=SimpleNamespace(close=close)))

        with caplog.at_level(logging.DEBUG, logger="deerflow.community.firecrawl.tools"):
            await _aclose_firecrawl_client(client)

        close.assert_called_once_with()
        assert "Failed to close the Firecrawl async HTTP pool" not in caplog.text

    @pytest.mark.anyio
    async def test_teardown_closes_the_real_sdk_pool(self):
        from firecrawl import AsyncFirecrawlApp as RealApp

        from deerflow.community.firecrawl.tools import _aclose_firecrawl_client

        client = RealApp(api_key="test-key")
        assert client._v2_client.async_http_client._client.is_closed is False

        await _aclose_firecrawl_client(client)

        assert client._v2_client.async_http_client._client.is_closed is True

    @patch("deerflow.community.firecrawl.tools.AsyncFirecrawlApp")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    @pytest.mark.anyio
    async def test_teardown_survives_a_client_without_v2_attributes(self, mock_get_app_config, mock_firecrawl_cls):
        """Older SDKs in the declared range have no _v2_client; teardown must be a no-op."""
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "firecrawl-search-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = []
        mock_firecrawl_cls.return_value.search = AsyncMock(return_value=mock_result)
        del mock_firecrawl_cls.return_value._v2_client

        from deerflow.community.firecrawl.tools import web_search_tool

        result = await web_search_tool.ainvoke({"query": "test query"})

        assert result == "[]"

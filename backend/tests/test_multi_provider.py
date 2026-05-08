"""Tests for multi-provider search system."""

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.multi_provider.adapters import InfoQuestAdapter, SearXNGAdapter, TavilyAdapter
from deerflow.community.multi_provider.tools import MultiProviderSearchClient, get_multi_client, web_fetch_multi, web_search_multi, web_search_stats
from deerflow.community.multi_provider.types import SearchResult


class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = SearchResult(title="Test Title", url="https://example.com", snippet="Test snippet", type="page")

        result_dict = result.to_dict()

        assert result_dict == {"title": "Test Title", "url": "https://example.com", "snippet": "Test snippet", "type": "page"}

    def test_default_type(self):
        """Test default type is 'page'."""
        result = SearchResult(title="Test", url="https://example.com", snippet="Snippet")

        assert result.type == "page"


class TestSearXNGAdapter:
    """Test SearXNG adapter."""

    @patch("deerflow.community.multi_provider.adapters.SearxSearchWrapper")
    def test_initialization(self, mock_wrapper_class):
        """Test SearXNG adapter initialization."""
        mock_wrapper = MagicMock()
        mock_wrapper_class.return_value = mock_wrapper

        adapter = SearXNGAdapter(searx_host="http://localhost:8888", engines=["google"], categories=["general"], language="en")

        mock_wrapper_class.assert_called_once_with(searx_host="http://localhost:8888", engines=["google"], categories=["general"], unsecure=False)
        assert adapter.get_name() == "searxng"
        assert adapter.language == "en"

    @patch("deerflow.community.multi_provider.adapters.SearxSearchWrapper")
    def test_search_normalizes_results(self, mock_wrapper_class):
        """Test search normalizes link → url."""
        mock_wrapper = MagicMock()
        mock_wrapper_class.return_value = mock_wrapper

        # SearXNG returns "link" field
        mock_wrapper.results.return_value = [{"title": "Test", "link": "https://example.com", "snippet": "Snippet"}]

        adapter = SearXNGAdapter(searx_host="http://localhost:8888")
        results = adapter.search("test query", max_results=5)

        assert len(results) == 1
        assert results[0].title == "Test"
        assert results[0].url == "https://example.com"  # normalized from "link"
        assert results[0].snippet == "Snippet"
        assert results[0].type == "page"

    @patch("deerflow.community.multi_provider.adapters.SearxSearchWrapper")
    def test_fetch_not_implemented(self, mock_wrapper_class):
        """Test fetch raises NotImplementedError."""
        mock_wrapper = MagicMock()
        mock_wrapper_class.return_value = mock_wrapper

        adapter = SearXNGAdapter(searx_host="http://localhost:8888")

        with pytest.raises(NotImplementedError, match="SearXNG does not support web fetch"):
            adapter.fetch("https://example.com")


class TestInfoQuestAdapter:
    """Test InfoQuest adapter."""

    @patch("deerflow.community.multi_provider.adapters.InfoQuestClient")
    def test_initialization(self, mock_client_class):
        """Test InfoQuest adapter initialization."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        adapter = InfoQuestAdapter(search_time_range=10)

        mock_client_class.assert_called_once_with(search_time_range=10)
        assert adapter.get_name() == "infoquest"

    @patch("deerflow.community.multi_provider.adapters.InfoQuestClient")
    def test_search(self, mock_client_class):
        """Test search with InfoQuest."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # InfoQuest returns JSON string
        mock_client.web_search.return_value = json.dumps([{"title": "Test", "url": "https://example.com", "snippet": "Snippet", "type": "page"}])

        adapter = InfoQuestAdapter()
        results = adapter.search("test query", max_results=5)

        assert len(results) == 1
        assert results[0].title == "Test"
        assert results[0].url == "https://example.com"

    @patch("deerflow.community.multi_provider.adapters.InfoQuestClient")
    def test_search_limits_results(self, mock_client_class):
        """Test search limits results to max_results."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Return 10 results
        mock_results = [{"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": f"Snippet {i}", "type": "page"} for i in range(10)]
        mock_client.web_search.return_value = json.dumps(mock_results)

        adapter = InfoQuestAdapter()
        results = adapter.search("test", max_results=3)

        assert len(results) == 3

    @patch("deerflow.community.multi_provider.adapters.InfoQuestClient")
    def test_fetch(self, mock_client_class):
        """Test fetch with InfoQuest."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.fetch.return_value = "# Test Content\n\nTest body"

        adapter = InfoQuestAdapter()
        content = adapter.fetch("https://example.com")

        assert content == "# Test Content\n\nTest body"
        mock_client.fetch.assert_called_once_with("https://example.com")


class TestTavilyAdapter:
    """Test Tavily adapter."""

    @patch("deerflow.community.multi_provider.adapters.TavilyClient")
    def test_initialization(self, mock_client_class):
        """Test Tavily adapter initialization."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        adapter = TavilyAdapter(api_key="test-key")

        mock_client_class.assert_called_once_with(api_key="test-key")
        assert adapter.get_name() == "tavily"

    @patch("deerflow.community.multi_provider.adapters.TavilyClient")
    def test_search_normalizes_results(self, mock_client_class):
        """Test search normalizes content → snippet."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Tavily returns "content" field
        mock_client.search.return_value = {"results": [{"title": "Test", "url": "https://example.com", "content": "Content text"}]}

        adapter = TavilyAdapter()
        results = adapter.search("test query", max_results=5)

        assert len(results) == 1
        assert results[0].snippet == "Content text"  # normalized from "content"

    @patch("deerflow.community.multi_provider.adapters.TavilyClient")
    def test_fetch(self, mock_client_class):
        """Test fetch with Tavily."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.extract.return_value = {"results": [{"title": "Test", "raw_content": "Test content here"}]}

        adapter = TavilyAdapter()
        content = adapter.fetch("https://example.com")

        assert "Test" in content
        assert "Test content" in content


class TestMultiProviderSearchClient:
    """Test MultiProviderSearchClient."""

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_default_provider_chain(self, mock_get_config):
        """Test defaults to InfoQuest → Tavily when no providers config."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={})
        mock_get_config.return_value = mock_config

        with patch("deerflow.community.multi_provider.tools.InfoQuestAdapter"), patch("deerflow.community.multi_provider.tools.TavilyAdapter"):
            client = MultiProviderSearchClient()

            # Should initialize 2 providers (infoquest, tavily)
            assert len(client.providers) == 2

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_custom_provider_chain(self, mock_get_config):
        """Test custom provider order from config."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(
            model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "infoquest", "enabled": True}, {"name": "tavily", "enabled": False}], "searxng_host": "http://localhost:8888"}
        )
        mock_get_config.return_value = mock_config

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter"), patch("deerflow.community.multi_provider.tools.InfoQuestAdapter"):
            client = MultiProviderSearchClient()

            # Should initialize 2 providers (searxng, infoquest) - tavily disabled
            assert len(client.providers) == 2

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_search_first_provider_success(self, mock_get_config):
        """Test search returns on first provider success."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        mock_provider = MagicMock()
        mock_provider.get_name.return_value = "searxng"
        mock_provider.search.return_value = [SearchResult("Title", "https://example.com", "Snippet", "page")]

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_provider):
            client = MultiProviderSearchClient()
            result = client.web_search("test query", max_results=5)

            result_data = json.loads(result)
            assert len(result_data) == 1
            assert result_data[0]["title"] == "Title"
            assert client.stats["searxng_success"] == 1
            assert client.stats["searxng_failure"] == 0

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_search_fallback_on_failure(self, mock_get_config):
        """Test search falls back to second provider on first failure."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "infoquest", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        # First provider fails
        mock_searxng = MagicMock()
        mock_searxng.get_name.return_value = "searxng"
        mock_searxng.search.side_effect = Exception("Connection failed")

        # Second provider succeeds
        mock_infoquest = MagicMock()
        mock_infoquest.get_name.return_value = "infoquest"
        mock_infoquest.search.return_value = [SearchResult("Title", "https://example.com", "Snippet", "page")]

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_searxng), patch("deerflow.community.multi_provider.tools.InfoQuestAdapter", return_value=mock_infoquest):
            client = MultiProviderSearchClient()
            result = client.web_search("test query", max_results=5)

            result_data = json.loads(result)
            assert len(result_data) == 1
            assert client.stats["searxng_failure"] == 1
            assert client.stats["infoquest_success"] == 1

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_search_all_providers_fail(self, mock_get_config):
        """Test exception when all providers fail."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "infoquest", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        # Both providers fail
        mock_searxng = MagicMock()
        mock_searxng.get_name.return_value = "searxng"
        mock_searxng.search.side_effect = Exception("SearXNG error")

        mock_infoquest = MagicMock()
        mock_infoquest.get_name.return_value = "infoquest"
        mock_infoquest.search.side_effect = Exception("InfoQuest error")

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_searxng), patch("deerflow.community.multi_provider.tools.InfoQuestAdapter", return_value=mock_infoquest):
            client = MultiProviderSearchClient()

            with pytest.raises(Exception, match="All search providers failed"):
                client.web_search("test query", max_results=5)

            assert client.stats["searxng_failure"] == 1
            assert client.stats["infoquest_failure"] == 1

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_tavily_fallback_counter(self, mock_get_config):
        """Test tavily_fallback counter for backwards compatibility."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "tavily", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        # First provider fails, Tavily succeeds
        mock_searxng = MagicMock()
        mock_searxng.get_name.return_value = "searxng"
        mock_searxng.search.side_effect = Exception("Failed")

        mock_tavily = MagicMock()
        mock_tavily.get_name.return_value = "tavily"
        mock_tavily.search.return_value = [SearchResult("Title", "https://example.com", "Snippet", "page")]

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_searxng), patch("deerflow.community.multi_provider.tools.TavilyAdapter", return_value=mock_tavily):
            client = MultiProviderSearchClient()
            client.web_search("test query", max_results=5)

            # tavily_fallback should be incremented when tavily is not first
            assert client.stats["tavily_fallback"] == 1
            assert client.stats["tavily_success"] == 1

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_fetch_skips_searxng(self, mock_get_config):
        """Test fetch automatically skips SearXNG."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "infoquest", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        mock_searxng = MagicMock()
        mock_searxng.get_name.return_value = "searxng"

        mock_infoquest = MagicMock()
        mock_infoquest.get_name.return_value = "infoquest"
        mock_infoquest.fetch.return_value = "# Content\n\nBody"

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_searxng), patch("deerflow.community.multi_provider.tools.InfoQuestAdapter", return_value=mock_infoquest):
            client = MultiProviderSearchClient()
            content = client.web_fetch("https://example.com")

            # SearXNG should be skipped, InfoQuest called
            mock_searxng.fetch.assert_not_called()
            mock_infoquest.fetch.assert_called_once_with("https://example.com")
            assert content == "# Content\n\nBody"

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_stats_tracking(self, mock_get_config):
        """Test stats are tracked correctly."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        mock_provider = MagicMock()
        mock_provider.get_name.return_value = "searxng"
        mock_provider.search.return_value = [SearchResult("Title", "https://example.com", "Snippet", "page")]

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_provider):
            client = MultiProviderSearchClient()

            # Multiple searches
            client.web_search("query1", max_results=5)
            client.web_search("query2", max_results=5)

            stats = client.get_stats()
            assert stats["searxng_success"] == 2
            assert stats["searxng_failure"] == 0

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_no_providers_available(self, mock_get_config):
        """Test exception when no providers are available."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": []})
        mock_get_config.return_value = mock_config

        client = MultiProviderSearchClient()

        with pytest.raises(Exception, match="No search providers available"):
            client.web_search("test query", max_results=5)


class TestToolFunctions:
    """Test tool functions."""

    @patch("deerflow.community.multi_provider.tools.get_multi_client")
    def test_web_search_multi(self, mock_get_client):
        """Test web_search_multi tool."""
        mock_client = MagicMock()
        mock_client.web_search.return_value = json.dumps([{"title": "Test", "url": "https://example.com", "snippet": "Snippet", "type": "page"}])
        mock_get_client.return_value = mock_client

        result = web_search_multi.invoke({"query": "test query"})

        mock_client.web_search.assert_called_once_with("test query")
        assert "Test" in result

    @patch("deerflow.community.multi_provider.tools.get_multi_client")
    def test_web_fetch_multi(self, mock_get_client):
        """Test web_fetch_multi tool."""
        mock_client = MagicMock()
        mock_client.web_fetch.return_value = "# Content\n\nBody"
        mock_get_client.return_value = mock_client

        result = web_fetch_multi.invoke({"url": "https://example.com"})

        mock_client.web_fetch.assert_called_once_with("https://example.com")
        assert result == "# Content\n\nBody"

    @patch("deerflow.community.multi_provider.tools.get_multi_client")
    def test_web_search_stats(self, mock_get_client):
        """Test web_search_stats tool."""
        mock_client = MagicMock()
        mock_client.get_stats.return_value = {"searxng_success": 5, "infoquest_failure": 2}
        mock_get_client.return_value = mock_client

        result = web_search_stats.invoke({})

        stats = json.loads(result)
        assert stats["searxng_success"] == 5
        assert stats["infoquest_failure"] == 2


class TestProviderOrdering:
    """Test configurable provider ordering."""

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_searxng_first_priority(self, mock_get_config):
        """Test SearXNG as primary provider."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "infoquest", "enabled": True}], "searxng_host": "http://localhost:8888"})
        mock_get_config.return_value = mock_config

        mock_searxng = MagicMock()
        mock_searxng.get_name.return_value = "searxng"
        mock_searxng.search.return_value = [SearchResult("Title", "https://example.com", "Snippet", "page")]

        mock_infoquest = MagicMock()
        mock_infoquest.get_name.return_value = "infoquest"

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_searxng), patch("deerflow.community.multi_provider.tools.InfoQuestAdapter", return_value=mock_infoquest):
            client = MultiProviderSearchClient()
            client.web_search("test query", max_results=5)

            # SearXNG should be called first and succeed
            mock_searxng.search.assert_called_once()
            mock_infoquest.search.assert_not_called()  # Should not fallback
            assert client.stats["searxng_success"] == 1

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_full_chain_traversal(self, mock_get_config):
        """Test all three providers are tried in order."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(
            model_extra={"providers": [{"name": "searxng", "enabled": True}, {"name": "infoquest", "enabled": True}, {"name": "tavily", "enabled": True}], "searxng_host": "http://localhost:8888"}
        )
        mock_get_config.return_value = mock_config

        # First two fail, third succeeds
        mock_searxng = MagicMock()
        mock_searxng.get_name.return_value = "searxng"
        mock_searxng.search.side_effect = Exception("SearXNG down")

        mock_infoquest = MagicMock()
        mock_infoquest.get_name.return_value = "infoquest"
        mock_infoquest.search.side_effect = Exception("InfoQuest down")

        mock_tavily = MagicMock()
        mock_tavily.get_name.return_value = "tavily"
        mock_tavily.search.return_value = [SearchResult("Title", "https://example.com", "Snippet", "page")]

        with (
            patch("deerflow.community.multi_provider.tools.SearXNGAdapter", return_value=mock_searxng),
            patch("deerflow.community.multi_provider.tools.InfoQuestAdapter", return_value=mock_infoquest),
            patch("deerflow.community.multi_provider.tools.TavilyAdapter", return_value=mock_tavily),
        ):
            client = MultiProviderSearchClient()
            client.web_search("test query", max_results=5)

            # All three should be tried in order
            assert client.stats["searxng_failure"] == 1
            assert client.stats["infoquest_failure"] == 1
            assert client.stats["tavily_success"] == 1
            assert client.stats["tavily_fallback"] == 1  # Tavily succeeded but wasn't first


class TestConfigurationScenarios:
    """Test various configuration scenarios."""

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_missing_searxng_host(self, mock_get_config):
        """Test graceful handling of missing searxng_host."""
        mock_config = MagicMock()
        # No searxng_host in config
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "searxng", "enabled": True}]})
        mock_get_config.return_value = mock_config

        with patch("deerflow.community.multi_provider.tools.SearXNGAdapter") as mock_adapter:
            mock_adapter.side_effect = Exception("Connection refused")

            client = MultiProviderSearchClient()

            # Should have 0 providers (SearXNG failed to init)
            assert len(client.providers) == 0

    @patch("deerflow.community.multi_provider.tools.get_app_config")
    def test_invalid_provider_name(self, mock_get_config):
        """Test invalid provider names are skipped."""
        mock_config = MagicMock()
        mock_config.get_tool_config.return_value = MagicMock(model_extra={"providers": [{"name": "invalid_provider", "enabled": True}, {"name": "infoquest", "enabled": True}]})
        mock_get_config.return_value = mock_config

        with patch("deerflow.community.multi_provider.tools.InfoQuestAdapter"):
            client = MultiProviderSearchClient()

            # Should only initialize InfoQuest (invalid_provider skipped)
            assert len(client.providers) == 1


class TestSingleton:
    """Test singleton pattern for get_multi_client."""

    def test_get_multi_client_returns_same_instance(self):
        """Test get_multi_client returns singleton."""
        with patch("deerflow.community.multi_provider.tools.MultiProviderSearchClient"):
            from deerflow.community.multi_provider import tools

            # Reset singleton
            tools._multi_client = None

            client1 = get_multi_client()
            client2 = get_multi_client()

            assert client1 is client2

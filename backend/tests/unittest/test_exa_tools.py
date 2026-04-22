"""Unit tests for the Exa community tools."""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_app_config():
    """Mock the app config to return tool configurations."""
    with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
        tool_config = MagicMock()
        tool_config.model_extra = {
            "max_results": 5,
            "search_type": "auto",
            "contents_max_characters": 1000,
            "api_key": "test-api-key",
        }
        mock_config.return_value.get_tool_config.return_value = tool_config
        yield mock_config


@pytest.fixture
def mock_exa_client():
    """Mock the Exa client."""
    with patch("deerflow.community.exa.tools.Exa") as mock_exa_cls:
        mock_client = MagicMock()
        mock_exa_cls.return_value = mock_client
        yield mock_client


class TestWebSearchTool:
    def test_basic_search(self, mock_app_config, mock_exa_client):
        """Test basic web search returns normalized results."""
        mock_result_1 = MagicMock()
        mock_result_1.title = "Test Title 1"
        mock_result_1.url = "https://example.com/1"
        mock_result_1.highlights = ["This is a highlight about the topic."]

        mock_result_2 = MagicMock()
        mock_result_2.title = "Test Title 2"
        mock_result_2.url = "https://example.com/2"
        mock_result_2.highlights = ["First highlight.", "Second highlight."]

        mock_response = MagicMock()
        mock_response.results = [mock_result_1, mock_result_2]
        mock_exa_client.search.return_value = mock_response

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})
        parsed = json.loads(result)

        assert len(parsed) == 2
        assert parsed[0]["title"] == "Test Title 1"
        assert parsed[0]["url"] == "https://example.com/1"
        assert parsed[0]["snippet"] == "This is a highlight about the topic."
        assert parsed[1]["snippet"] == "First highlight.\nSecond highlight."

        mock_exa_client.search.assert_called_once_with(
            "test query",
            type="auto",
            num_results=5,
            contents={"highlights": {"max_characters": 1000}},
        )

    def test_search_with_custom_config(self, mock_exa_client):
        """Test search respects custom configuration values."""
        with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
            tool_config = MagicMock()
            tool_config.model_extra = {
                "max_results": 10,
                "search_type": "neural",
                "contents_max_characters": 2000,
                "api_key": "test-key",
            }
            mock_config.return_value.get_tool_config.return_value = tool_config

            mock_response = MagicMock()
            mock_response.results = []
            mock_exa_client.search.return_value = mock_response

            from deerflow.community.exa.tools import web_search_tool

            web_search_tool.invoke({"query": "neural search"})

            mock_exa_client.search.assert_called_once_with(
                "neural search",
                type="neural",
                num_results=10,
                contents={"highlights": {"max_characters": 2000}},
            )

    def test_search_with_no_highlights(self, mock_app_config, mock_exa_client):
        """Test search handles results with no highlights."""
        mock_result = MagicMock()
        mock_result.title = "No Highlights"
        mock_result.url = "https://example.com/empty"
        mock_result.highlights = None

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.search.return_value = mock_response

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test"})
        parsed = json.loads(result)

        assert parsed[0]["snippet"] == ""

    def test_search_empty_results(self, mock_app_config, mock_exa_client):
        """Test search with no results returns empty list."""
        mock_response = MagicMock()
        mock_response.results = []
        mock_exa_client.search.return_value = mock_response

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "nothing"})
        parsed = json.loads(result)

        assert parsed == []

    def test_search_error_handling(self, mock_app_config, mock_exa_client):
        """Test search returns error string on exception."""
        mock_exa_client.search.side_effect = Exception("API rate limit exceeded")

        from deerflow.community.exa.tools import web_search_tool

        result = web_search_tool.invoke({"query": "error"})

        assert result == "Error: API rate limit exceeded"


class TestWebFetchTool:
    def test_basic_fetch(self, mock_app_config, mock_exa_client):
        """Test basic web fetch returns formatted content."""
        mock_result = MagicMock()
        mock_result.title = "Fetched Page"
        mock_result.text = "This is the page content."

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nThis is the page content."
        mock_exa_client.get_contents.assert_called_once_with(
            ["https://example.com"],
            text={"max_characters": 4096},
        )

    def test_fetch_no_title(self, mock_app_config, mock_exa_client):
        """Test fetch with missing title uses 'Untitled'."""
        mock_result = MagicMock()
        mock_result.title = None
        mock_result.text = "Content without title."

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result.startswith("# Untitled\n\n")

    def test_fetch_no_results(self, mock_app_config, mock_exa_client):
        """Test fetch with no results returns error."""
        mock_response = MagicMock()
        mock_response.results = []
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com/404"})

        assert result == "Error: No results found"

    def test_fetch_error_handling(self, mock_app_config, mock_exa_client):
        """Test fetch returns error string on exception."""
        mock_exa_client.get_contents.side_effect = Exception("Connection timeout")

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Connection timeout"

    def test_fetch_reads_web_fetch_config(self, mock_exa_client):
        """Test that web_fetch_tool reads 'web_fetch' config, not 'web_search'."""
        with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "exa-fetch-key"}
            mock_config.return_value.get_tool_config.return_value = tool_config

            mock_result = MagicMock()
            mock_result.title = "Page"
            mock_result.text = "Content."
            mock_response = MagicMock()
            mock_response.results = [mock_result]
            mock_exa_client.get_contents.return_value = mock_response

            from deerflow.community.exa.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com"})

            mock_config.return_value.get_tool_config.assert_any_call("web_fetch")

    def test_fetch_uses_independent_api_key(self, mock_exa_client):
        """Test mixed-provider config: web_fetch uses its own api_key, not web_search's."""
        with patch("deerflow.community.exa.tools.get_app_config") as mock_config:
            with patch("deerflow.community.exa.tools.Exa") as mock_exa_cls:
                mock_exa_cls.return_value = mock_exa_client
                fetch_config = MagicMock()
                fetch_config.model_extra = {"api_key": "exa-fetch-key"}

                def get_tool_config(name):
                    if name == "web_fetch":
                        return fetch_config
                    return None

                mock_config.return_value.get_tool_config.side_effect = get_tool_config

                mock_result = MagicMock()
                mock_result.title = "Page"
                mock_result.text = "Content."
                mock_response = MagicMock()
                mock_response.results = [mock_result]
                mock_exa_client.get_contents.return_value = mock_response

                from deerflow.community.exa.tools import web_fetch_tool

                web_fetch_tool.invoke({"url": "https://example.com"})

                mock_exa_cls.assert_called_once_with(api_key="exa-fetch-key")

    def test_fetch_truncates_long_content(self, mock_app_config, mock_exa_client):
        """Test fetch truncates content to 4096 characters."""
        mock_result = MagicMock()
        mock_result.title = "Long Page"
        mock_result.text = "x" * 5000

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_exa_client.get_contents.return_value = mock_response

        from deerflow.community.exa.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        # "# Long Page\n\n" is 14 chars, content truncated to 4096
        content_after_header = result.split("\n\n", 1)[1]
        assert len(content_after_header) == 4096

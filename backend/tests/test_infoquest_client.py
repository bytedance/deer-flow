"""Tests for InfoQuest client and tools."""

import json
from unittest.mock import MagicMock, patch

from src.community.infoquest import tools
from src.community.infoquest.infoquest_client import InfoQuestClient


class TestInfoQuestClient:
    def test_infoquest_client_initialization(self):
        """Test InfoQuestClient initialization with different parameters."""
        # Test with default parameters
        client = InfoQuestClient()
        assert client.fetch_time == -1
        assert client.fetch_timeout == -1
        assert client.fetch_navigation_timeout == -1
        assert client.search_time_range == -1

        # Test with custom parameters
        client = InfoQuestClient(fetch_time=10, fetch_timeout=30, fetch_navigation_timeout=60, search_time_range=24)
        assert client.fetch_time == 10
        assert client.fetch_timeout == 30
        assert client.fetch_navigation_timeout == 60
        assert client.search_time_range == 24

    @patch("src.community.infoquest.infoquest_client.requests.post")
    def test_fetch_success(self, mock_post):
        """Test successful fetch operation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({"reader_result": "<html><body>Test content</body></html>"})
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.fetch("https://example.com")

        assert result == "<html><body>Test content</body></html>"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://reader.infoquest.bytepluses.com"
        assert kwargs["json"]["url"] == "https://example.com"
        assert kwargs["json"]["format"] == "HTML"

    @patch("src.community.infoquest.infoquest_client.requests.post")
    def test_fetch_non_200_status(self, mock_post):
        """Test fetch operation with non-200 status code."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.fetch("https://example.com")

        assert result == "Error: fetch API returned status 404: Not Found"

    @patch("src.community.infoquest.infoquest_client.requests.post")
    def test_fetch_empty_response(self, mock_post):
        """Test fetch operation with empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.fetch("https://example.com")

        assert result == "Error: no result found"

    @patch("src.community.infoquest.infoquest_client.requests.post")
    def test_web_search_raw_results_success(self, mock_post):
        """Test successful web_search_raw_results operation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"organic": [{"title": "Test Result", "desc": "Test description", "url": "https://example.com"}]}}}], "images_results": []}}
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.web_search_raw_results("test query", "")

        assert "search_result" in result
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://search.infoquest.bytepluses.com"
        assert kwargs["json"]["query"] == "test query"

    @patch("src.community.infoquest.infoquest_client.requests.post")
    def test_web_search_success(self, mock_post):
        """Test successful web_search operation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_result": {"results": [{"content": {"results": {"organic": [{"title": "Test Result", "desc": "Test description", "url": "https://example.com"}]}}}], "images_results": []}}
        mock_post.return_value = mock_response

        client = InfoQuestClient()
        result = client.web_search("test query")

        # Check if result is a valid JSON string with expected content
        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["title"] == "Test Result"
        assert result_data[0]["url"] == "https://example.com"

    def test_clean_results(self):
        """Test clean_results method with sample raw results."""
        raw_results = [
            {
                "content": {
                    "results": {
                        "organic": [{"title": "Test Page", "desc": "Page description", "url": "https://example.com/page1"}],
                        "top_stories": {"items": [{"title": "Test News", "source": "Test Source", "time_frame": "2 hours ago", "url": "https://example.com/news1"}]},
                    }
                }
            }
        ]

        cleaned = InfoQuestClient.clean_results(raw_results)

        assert len(cleaned) == 2
        assert cleaned[0]["type"] == "page"
        assert cleaned[0]["title"] == "Test Page"
        assert cleaned[1]["type"] == "news"
        assert cleaned[1]["title"] == "Test News"

    def test_clean_results_with_image_search(self):
        """Test clean_results_with_image_search method with sample raw results."""
        raw_results = [{"content": {"results": {"images_results": [{"image_url": "https://example.com/image1.jpg", "thumbnail_url": "https://example.com/thumb1.jpg", "url": "https://example.com/page1"}]}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 1
        assert cleaned[0]["image_url"] == "https://example.com/image1.jpg"
        assert cleaned[0]["thumbnail_url"] == "https://example.com/thumb1.jpg"
        assert cleaned[0]["url"] == "https://example.com/page1"

    @patch("src.community.infoquest.tools._get_infoquest_client")
    def test_web_search_tool(self, mock_get_client):
        """Test web_search_tool function."""
        mock_client = MagicMock()
        mock_client.web_search.return_value = json.dumps([])
        mock_get_client.return_value = mock_client

        result = tools.web_search_tool.run("test query")

        assert result == json.dumps([])
        mock_get_client.assert_called_once()
        mock_client.web_search.assert_called_once_with("test query")

    @patch("src.community.infoquest.tools._get_infoquest_client")
    def test_web_fetch_tool(self, mock_get_client):
        """Test web_fetch_tool function."""
        mock_client = MagicMock()
        mock_client.fetch.return_value = "<html><body>Test content</body></html>"
        mock_get_client.return_value = mock_client

        result = tools.web_fetch_tool.run("https://example.com")

        assert result == "# Untitled\n\nTest content"
        mock_get_client.assert_called_once()
        mock_client.fetch.assert_called_once_with("https://example.com")

    @patch("src.community.infoquest.tools.get_app_config")
    def test_get_infoquest_client(self, mock_get_app_config):
        """Test _get_infoquest_client function with config."""
        mock_config = MagicMock()
        mock_config.get_tool_config.side_effect = [MagicMock(model_extra={"search_time_range": 24}), MagicMock(model_extra={"fetch_time": 10, "timeout": 30, "navigation_timeout": 60})]
        mock_get_app_config.return_value = mock_config

        client = tools._get_infoquest_client()

        assert client.search_time_range == 24
        assert client.fetch_time == 10
        assert client.fetch_timeout == 30
        assert client.fetch_navigation_timeout == 60

    @patch("src.community.infoquest.infoquest_client.requests.post")
    def test_web_search_api_error(self, mock_post):
        """Test web_search operation with API error."""
        mock_post.side_effect = Exception("Connection error")

        client = InfoQuestClient()
        result = client.web_search("test query")

        assert "Error" in result

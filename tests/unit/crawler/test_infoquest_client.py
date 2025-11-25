# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import Mock, patch
import json

import pytest

from src.crawler.infoquest_client import InfoQuestClient


class TestInfoQuestClient:
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_success(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Test Content</body></html>"
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<html><body>Test Content</body></html>"
        mock_post.assert_called_once()
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_json_response_with_reader_result(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        json_data = {
            "reader_result": "<p>Extracted content from JSON</p>",
            "err_code": 0,
            "err_msg": "success"
        }
        mock_response.text = json.dumps(json_data)
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<p>Extracted content from JSON</p>"
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_json_response_with_content_fallback(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        json_data = {
            "content": "<p>Content fallback from JSON</p>",
            "err_code": 0,
            "err_msg": "success"
        }
        mock_response.text = json.dumps(json_data)
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<p>Content fallback from JSON</p>"
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_json_response_without_expected_fields(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        json_data = {
            "unexpected_field": "some value",
            "err_code": 0,
            "err_msg": "success"
        }
        mock_response.text = json.dumps(json_data)
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == json.dumps(json_data)
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_http_error(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "status 500" in result
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_empty_response(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "empty response" in result
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_whitespace_only_response(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "   \n  \t  "
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "empty response" in result
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_not_found(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "status 404" in result
    
    @patch.dict("os.environ", {}, clear=True)
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_without_api_key_logs_warning(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test</html>"
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<html>Test</html>"
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_with_timeout_parameters(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test</html>"
        mock_post.return_value = mock_response

        client = InfoQuestClient(fetch_time=10, timeout=20, navi_timeout=30)

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<html>Test</html>"
        # Verify the post call was made with timeout parameters
        call_args = mock_post.call_args[1]
        assert call_args['json']['fetch_time'] == 10
        assert call_args['json']['timeout'] == 20
        assert call_args['json']['navi_timeout'] == 30
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_with_markdown_format(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "# Markdown Content"
        mock_post.return_value = mock_response

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com", return_format="markdown")

        # Assert
        assert result == "# Markdown Content"
        # Verify the format was set correctly
        call_args = mock_post.call_args[1]
        assert call_args['json']['format'] == "markdown"
    
    @patch("src.crawler.infoquest_client.requests.post")
    def test_crawl_exception_handling(self, mock_post):
        # Arrange
        mock_post.side_effect = Exception("Network error")

        client = InfoQuestClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "Network error" in result
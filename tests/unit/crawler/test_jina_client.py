# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import Mock, patch

import pytest

from src.crawler.jina_client import JinaClient


class TestJinaClient:
    @patch("src.crawler.jina_client.requests.post")
    def test_crawl_success(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Test</body></html>"
        mock_post.return_value = mock_response

        client = JinaClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<html><body>Test</body></html>"
        mock_post.assert_called_once()

    @patch("src.crawler.jina_client.requests.post")
    def test_crawl_http_error(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        client = JinaClient()

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            client.crawl("https://example.com")

        assert "status 500" in str(exc_info.value)

    @patch("src.crawler.jina_client.requests.post")
    def test_crawl_empty_response(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_post.return_value = mock_response

        client = JinaClient()

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            client.crawl("https://example.com")

        assert "empty response" in str(exc_info.value)

    @patch("src.crawler.jina_client.requests.post")
    def test_crawl_whitespace_only_response(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "   \n  \t  "
        mock_post.return_value = mock_response

        client = JinaClient()

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            client.crawl("https://example.com")

        assert "empty response" in str(exc_info.value)

    @patch("src.crawler.jina_client.requests.post")
    def test_crawl_not_found(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_post.return_value = mock_response

        client = JinaClient()

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            client.crawl("https://example.com")

        assert "status 404" in str(exc_info.value)

    @patch.dict("os.environ", {}, clear=True)
    @patch("src.crawler.jina_client.requests.post")
    def test_crawl_without_api_key_logs_warning(self, mock_post):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test</html>"
        mock_post.return_value = mock_response

        client = JinaClient()

        # Act
        result = client.crawl("https://example.com")

        # Assert
        assert result == "<html>Test</html>"

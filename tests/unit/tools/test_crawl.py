from unittest.mock import Mock, patch
from src.tools.crawl import crawl_tool


class TestCrawlTool:

    @patch("src.tools.crawl.Crawler")
    def test_crawl_tool_success(self, mock_crawler_class):
        # Arrange
        mock_crawler = Mock()
        mock_article = Mock()
        mock_article.to_markdown.return_value = (
            "# Test Article\nThis is test content." * 100
        )
        mock_crawler.crawl.return_value = mock_article
        mock_crawler_class.return_value = mock_crawler

        url = "https://example.com"

        # Act
        result = crawl_tool(url)

        # Assert
        assert isinstance(result, dict)
        assert result["url"] == url
        assert "crawled_content" in result
        assert len(result["crawled_content"]) <= 1000
        mock_crawler_class.assert_called_once()
        mock_crawler.crawl.assert_called_once_with(url)
        mock_article.to_markdown.assert_called_once()

    @patch("src.tools.crawl.Crawler")
    def test_crawl_tool_short_content(self, mock_crawler_class):
        # Arrange
        mock_crawler = Mock()
        mock_article = Mock()
        short_content = "Short content"
        mock_article.to_markdown.return_value = short_content
        mock_crawler.crawl.return_value = mock_article
        mock_crawler_class.return_value = mock_crawler

        url = "https://example.com"

        # Act
        result = crawl_tool(url)

        # Assert
        assert result["crawled_content"] == short_content

    @patch("src.tools.crawl.Crawler")
    @patch("src.tools.crawl.logger")
    def test_crawl_tool_crawler_exception(self, mock_logger, mock_crawler_class):
        # Arrange
        mock_crawler = Mock()
        mock_crawler.crawl.side_effect = Exception("Network error")
        mock_crawler_class.return_value = mock_crawler

        url = "https://example.com"

        # Act
        result = crawl_tool(url)

        # Assert
        assert isinstance(result, str)
        assert "Failed to crawl" in result
        assert "Network error" in result
        mock_logger.error.assert_called_once()

    @patch("src.tools.crawl.Crawler")
    @patch("src.tools.crawl.logger")
    def test_crawl_tool_crawler_instantiation_exception(
        self, mock_logger, mock_crawler_class
    ):
        # Arrange
        mock_crawler_class.side_effect = Exception("Crawler init error")

        url = "https://example.com"

        # Act
        result = crawl_tool(url)

        # Assert
        assert isinstance(result, str)
        assert "Failed to crawl" in result
        assert "Crawler init error" in result
        mock_logger.error.assert_called_once()

    @patch("src.tools.crawl.Crawler")
    @patch("src.tools.crawl.logger")
    def test_crawl_tool_markdown_conversion_exception(
        self, mock_logger, mock_crawler_class
    ):
        # Arrange
        mock_crawler = Mock()
        mock_article = Mock()
        mock_article.to_markdown.side_effect = Exception("Markdown conversion error")
        mock_crawler.crawl.return_value = mock_article
        mock_crawler_class.return_value = mock_crawler

        url = "https://example.com"

        # Act
        result = crawl_tool(url)

        # Assert
        assert isinstance(result, str)
        assert "Failed to crawl" in result
        assert "Markdown conversion error" in result
        mock_logger.error.assert_called_once()

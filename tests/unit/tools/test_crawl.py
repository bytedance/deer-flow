import json
from unittest.mock import Mock, patch

from src.tools.crawl import crawl_tool, is_pdf_url


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
        assert isinstance(result, str)
        result_dict = json.loads(result)
        assert result_dict["url"] == url
        assert "crawled_content" in result_dict
        assert len(result_dict["crawled_content"]) <= 1000
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
        result_dict = json.loads(result)
        assert result_dict["crawled_content"] == short_content

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

    @patch("src.tools.crawl.Crawler")
    def test_crawl_tool_with_none_content(self, mock_crawler_class):
        # Arrange
        mock_crawler = Mock()
        mock_article = Mock()
        mock_article.to_markdown.return_value = "# Article\n\n*No content available*\n"
        mock_crawler.crawl.return_value = mock_article
        mock_crawler_class.return_value = mock_crawler

        url = "https://example.com"

        # Act
        result = crawl_tool(url)

        # Assert
        assert isinstance(result, str)
        result_dict = json.loads(result)
        assert result_dict["url"] == url
        assert "crawled_content" in result_dict
        assert "No content available" in result_dict["crawled_content"]


class TestPDFHandling:
    """Test PDF URL detection and handling for issue #701."""
    
    def test_is_pdf_url_with_pdf_urls(self):
        """Test that PDF URLs are correctly identified."""
        test_cases = [
            ("https://example.com/document.pdf", True),
            ("https://example.com/file.PDF", True),  # Case insensitive
            ("https://example.com/path/to/report.pdf", True),
            ("https://pdf.dfcfw.com/pdf/H3_AP202503071644153386_1.pdf", True),  # URL from issue
            ("http://site.com/path/document.pdf?param=value", True),  # With query params
        ]
        
        for url, expected in test_cases:
            assert is_pdf_url(url) == expected, f"Failed for URL: {url}"
    
    def test_is_pdf_url_with_non_pdf_urls(self):
        """Test that non-PDF URLs are correctly identified."""
        test_cases = [
            ("https://example.com/page.html", False),
            ("https://example.com/article.php", False),
            ("https://example.com/", False),
            ("https://example.com/document.pdfx", False),  # Not exactly .pdf
            ("https://example.com/document.doc", False),
            ("https://example.com/document.txt", False),
            ("https://example.com?file=document.pdf", False),  # Query param, not path
            ("", False),  # Empty string
            (None, False),  # None value
        ]
        
        for url, expected in test_cases:
            assert is_pdf_url(url) == expected, f"Failed for URL: {url}"
    
    def test_crawl_tool_with_pdf_url(self):
        """Test that PDF URLs return the expected error structure."""
        pdf_url = "https://example.com/document.pdf"
        
        # Act
        result = crawl_tool(pdf_url)
        
        # Assert
        assert isinstance(result, str)
        result_dict = json.loads(result)
        
        # Check structure of PDF error response
        assert result_dict["url"] == pdf_url
        assert "error" in result_dict
        assert result_dict["crawled_content"] is None
        assert result_dict["is_pdf"] is True
        assert "PDF files cannot be crawled directly" in result_dict["error"]
    
    def test_crawl_tool_with_issue_pdf_url(self):
        """Test with the exact PDF URL from issue #701."""
        issue_pdf_url = "https://pdf.dfcfw.com/pdf/H3_AP202503071644153386_1.pdf"
        
        # Act
        result = crawl_tool(issue_pdf_url)
        
        # Assert
        result_dict = json.loads(result)
        assert result_dict["url"] == issue_pdf_url
        assert result_dict["is_pdf"] is True
        assert "cannot be crawled directly" in result_dict["error"]
    
    @patch("src.tools.crawl.Crawler")
    @patch("src.tools.crawl.logger")
    def test_crawl_tool_skips_crawler_for_pdfs(self, mock_logger, mock_crawler_class):
        """Test that the crawler is not instantiated for PDF URLs."""
        pdf_url = "https://example.com/document.pdf"
        
        # Act
        result = crawl_tool(pdf_url)
        
        # Assert
        # Crawler should not be instantiated for PDF URLs
        mock_crawler_class.assert_not_called()
        mock_logger.info.assert_called_once_with(f"PDF URL detected, skipping crawling: {pdf_url}")
        
        # Should return proper PDF error structure
        result_dict = json.loads(result)
        assert result_dict["is_pdf"] is True

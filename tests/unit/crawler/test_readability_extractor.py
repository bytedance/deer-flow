# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import patch
from src.crawler.readability_extractor import ReadabilityExtractor


class TestReadabilityExtractor:
    @patch("src.crawler.readability_extractor.simple_json_from_html_string")
    def test_extract_article_with_valid_content(self, mock_simple_json):
        # Arrange
        mock_simple_json.return_value = {
            "title": "Test Article",
            "content": "<p>Article content</p>",
        }
        extractor = ReadabilityExtractor()

        # Act
        article = extractor.extract_article("<html>test</html>")

        # Assert
        assert article.title == "Test Article"
        assert article.html_content == "<p>Article content</p>"

    @patch("src.crawler.readability_extractor.simple_json_from_html_string")
    def test_extract_article_with_none_content(self, mock_simple_json):
        # Arrange
        mock_simple_json.return_value = {
            "title": "Test Article",
            "content": None,
        }
        extractor = ReadabilityExtractor()

        # Act
        article = extractor.extract_article("<html>test</html>")

        # Assert
        assert article.title == "Test Article"
        assert article.html_content == "<p>No content could be extracted from this page</p>"

    @patch("src.crawler.readability_extractor.simple_json_from_html_string")
    def test_extract_article_with_empty_content(self, mock_simple_json):
        # Arrange
        mock_simple_json.return_value = {
            "title": "Test Article",
            "content": "",
        }
        extractor = ReadabilityExtractor()

        # Act
        article = extractor.extract_article("<html>test</html>")

        # Assert
        assert article.title == "Test Article"
        assert article.html_content == "<p>No content could be extracted from this page</p>"

    @patch("src.crawler.readability_extractor.simple_json_from_html_string")
    def test_extract_article_with_whitespace_only_content(self, mock_simple_json):
        # Arrange
        mock_simple_json.return_value = {
            "title": "Test Article",
            "content": "   \n  \t  ",
        }
        extractor = ReadabilityExtractor()

        # Act
        article = extractor.extract_article("<html>test</html>")

        # Assert
        assert article.title == "Test Article"
        assert article.html_content == "<p>No content could be extracted from this page</p>"

    @patch("src.crawler.readability_extractor.simple_json_from_html_string")
    def test_extract_article_with_none_title(self, mock_simple_json):
        # Arrange
        mock_simple_json.return_value = {
            "title": None,
            "content": "<p>Article content</p>",
        }
        extractor = ReadabilityExtractor()

        # Act
        article = extractor.extract_article("<html>test</html>")

        # Assert
        assert article.title == "Untitled"
        assert article.html_content == "<p>Article content</p>"

    @patch("src.crawler.readability_extractor.simple_json_from_html_string")
    def test_extract_article_with_empty_title(self, mock_simple_json):
        # Arrange
        mock_simple_json.return_value = {
            "title": "",
            "content": "<p>Article content</p>",
        }
        extractor = ReadabilityExtractor()

        # Act
        article = extractor.extract_article("<html>test</html>")

        # Assert
        assert article.title == "Untitled"
        assert article.html_content == "<p>Article content</p>"

# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import src.crawler as crawler_module


def test_crawler_sets_article_url(monkeypatch):
    """Test that the crawler sets the article.url field correctly."""

    class DummyArticle:
        def __init__(self):
            self.url = None

        def to_markdown(self):
            return "# Dummy"

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            return "<html>dummy</html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            return DummyArticle()

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )

    crawler = crawler_module.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    assert article.url == url
    assert article.to_markdown() == "# Dummy"


def test_crawler_calls_dependencies(monkeypatch):
    """Test that Crawler calls JinaClient.crawl and ReadabilityExtractor.extract_article."""
    calls = {}

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            calls["jina"] = (url, return_format)
            return "<html>dummy</html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            calls["extractor"] = html

            class DummyArticle:
                url = None

                def to_markdown(self):
                    return "# Dummy"

            return DummyArticle()

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )

    crawler = crawler_module.Crawler()
    url = "http://example.com"
    crawler.crawl(url)
    assert "jina" in calls
    assert calls["jina"][0] == url
    assert calls["jina"][1] == "html"
    assert "extractor" in calls
    assert calls["extractor"] == "<html>dummy</html>"


def test_crawler_handles_empty_content(monkeypatch):
    """Test that the crawler handles empty content gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            return ""  # Empty content

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for empty content
            assert False, "ReadabilityExtractor should not be called for empty content"

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)

    crawler = crawler_module.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Empty Content"
    assert "No content could be extracted" in article.html_content


def test_crawler_handles_non_html_content(monkeypatch):
    """Test that the crawler handles non-HTML content gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            return "This is plain text content, not HTML"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for non-HTML content
            assert False, "ReadabilityExtractor should not be called for non-HTML content"

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)

    crawler = crawler_module.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Non-HTML Content"
    assert "cannot be parsed as HTML" in article.html_content
    assert "plain text content" in article.html_content  # Should include a snippet of the original content


def test_crawler_handles_extraction_failure(monkeypatch):
    """Test that the crawler handles readability extraction failure gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            return "<html><body>Valid HTML but extraction will fail</body></html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            raise Exception("Extraction failed")

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)

    crawler = crawler_module.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Content Extraction Failed"
    assert "Content extraction failed" in article.html_content
    assert "Valid HTML but extraction will fail" in article.html_content  # Should include a snippet of the HTML


def test_crawler_with_json_like_content(monkeypatch):
    """Test that the crawler handles JSON-like content gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            return '{"title": "Some JSON", "content": "This is JSON content"}'

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for JSON content
            assert False, "ReadabilityExtractor should not be called for JSON content"

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)

    crawler = crawler_module.Crawler()
    url = "http://example.com/api/data"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Non-HTML Content"
    assert "cannot be parsed as HTML" in article.html_content
    assert '{"title": "Some JSON"' in article.html_content  # Should include a snippet of the JSON


def test_crawler_with_various_html_formats(monkeypatch):
    """Test that the crawler correctly identifies various HTML formats."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    # Test case 1: HTML with DOCTYPE
    class DummyJinaClient1:
        def crawl(self, url, return_format=None):
            return "<!DOCTYPE html><html><body><p>Test content</p></body></html>"

    # Test case 2: HTML with leading whitespace
    class DummyJinaClient2:
        def crawl(self, url, return_format=None):
            return "\n\n  <html><body><p>Test content</p></body></html>"

    # Test case 3: HTML with comments
    class DummyJinaClient3:
        def crawl(self, url, return_format=None):
            return "<!-- HTML comment --><html><body><p>Test content</p></body></html>"

    # Test case 4: HTML with self-closing tags
    class DummyJinaClient4:
        def crawl(self, url, return_format=None):
            return '<img src="test.jpg" alt="test" /><p>Test content</p>'

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            return DummyArticle("Extracted Article", "<p>Extracted content</p>")

    # Test each HTML format
    test_cases = [
        (DummyJinaClient1, "HTML with DOCTYPE"),
        (DummyJinaClient2, "HTML with leading whitespace"),
        (DummyJinaClient3, "HTML with comments"),
        (DummyJinaClient4, "HTML with self-closing tags"),
    ]
    
    for JinaClientClass, description in test_cases:
        monkeypatch.setattr("src.crawler.crawler.JinaClient", JinaClientClass)
        monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)
        
        crawler = crawler_module.Crawler()
        url = "http://example.com"
        article = crawler.crawl(url)
        
        assert article.url == url
        assert article.title == "Extracted Article"
        assert "Extracted content" in article.html_content

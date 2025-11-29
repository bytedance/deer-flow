# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import src.crawler as crawler_module
from src.crawler.crawler import safe_truncate
from src.crawler.infoquest_client import InfoQuestClient


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
        
    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            pass
            
        def crawl(self, url, return_format=None):
            return "<html>dummy</html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            return DummyArticle()

    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}
    
    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
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
    
    # Fix: Update DummyInfoQuestClient to accept initialization parameters
    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            # We don't need to use these parameters, just accept them
            pass
            
        def crawl(self, url, return_format=None):
            calls["infoquest"] = (url, return_format)
            return "<html>dummy</html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            calls["extractor"] = html

            class DummyArticle:
                url = None

                def to_markdown(self):
                    return "# Dummy"

            return DummyArticle()
    
    # Add mock for load_yaml_config to ensure it returns configuration with Jina engine
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}
    
    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)  # Include this if InfoQuest might be used
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
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
    
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Empty Content"
    assert "No content could be extracted from this page" in article.html_content


def test_crawler_handles_error_response_from_client(monkeypatch):
    """Test that the crawler handles error responses from the client gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            return "Error: API returned status 500"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for error responses
            assert False, "ReadabilityExtractor should not be called for error responses"
    
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title in ["Non-HTML Content", "Content Extraction Failed"]
    assert "Error: API returned status 500" in article.html_content


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

    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}
        
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)
    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title in ["Non-HTML Content", "Content Extraction Failed"]
    assert "cannot be parsed as HTML" in article.html_content or "Content extraction failed" in article.html_content
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
    
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
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
    
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}

    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com/api/data"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title in ["Non-HTML Content", "Content Extraction Failed"]
    assert "cannot be parsed as HTML" in article.html_content or "Content extraction failed" in article.html_content
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

    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "jina"}}
    
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
        monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)
        
        crawler = crawler_module.crawler.Crawler()
        url = "http://example.com"
        article = crawler.crawl(url)
        
        assert article.url == url
        assert article.title == "Extracted Article"
        assert "Extracted content" in article.html_content


def test_safe_truncate_function():
    """Test the safe_truncate function handles various character sets correctly."""
    
    # Test None input
    assert safe_truncate(None) is None
    
    # Test empty string
    assert safe_truncate("") == ""
    
    # Test string shorter than limit
    assert safe_truncate("Short text") == "Short text"
    
    # Test ASCII truncation
    result = safe_truncate("This is a longer text that needs truncation", 20)
    assert len(result) <= 20
    assert "..." in result
    
    # Test Unicode/emoji characters
    text_with_emoji = "Hello! 🌍 Welcome to the world 🚀"
    result = safe_truncate(text_with_emoji, 20)
    assert len(result) <= 20
    assert "..." in result
    # Verify it's valid UTF-8
    assert result.encode('utf-8').decode('utf-8') == result
    
    # Test very small limit
    assert safe_truncate("Long text", 1) == "."
    assert safe_truncate("Long text", 2) == ".."
    assert safe_truncate("Long text", 3) == "..."
    
    # Test with Chinese characters
    chinese_text = "这是一个中文测试文本"
    result = safe_truncate(chinese_text, 10)
    assert len(result) <= 10
    # Verify it's valid UTF-8
    assert result.encode('utf-8').decode('utf-8') == result

# ========== InfoQuest Client Tests ==========

def test_crawler_selects_infoquest_engine(monkeypatch):
    """Test that the crawler selects InfoQuestClient when configured to use it."""
    calls = {}

    class DummyJinaClient:
        def crawl(self, url, return_format=None):
            calls["jina"] = True
            return "<html>dummy</html>"
    
    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            calls["infoquest_init"] = (fetch_time, timeout, navi_timeout)
            
        def crawl(self, url, return_format=None):
            calls["infoquest"] = (url, return_format)
            return "<html>dummy from infoquest</html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            calls["extractor"] = html

            class DummyArticle:
                url = None

                def to_markdown(self):
                    return "# Dummy"

            return DummyArticle()
    
    # Mock configuration to use InfoQuest engine with custom parameters
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {
            "engine": "infoquest",
            "fetch_time": 30,
            "timeout": 60,
            "navi_timeout": 45
        }}
    
    monkeypatch.setattr("src.crawler.crawler.JinaClient", DummyJinaClient)
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    crawler.crawl(url)
    
    # Verify InfoQuestClient was used, not JinaClient
    assert "infoquest_init" in calls
    assert calls["infoquest_init"] == (30, 60, 45)  # Verify parameters were passed correctly
    assert "infoquest" in calls
    assert calls["infoquest"][0] == url
    assert calls["infoquest"][1] == "html"
    assert "extractor" in calls
    assert calls["extractor"] == "<html>dummy from infoquest</html>"
    assert "jina" not in calls


def test_crawler_with_infoquest_empty_content(monkeypatch):
    """Test that the crawler handles empty content from InfoQuest client gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            pass
            
        def crawl(self, url, return_format=None):
            return ""  # Empty content

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for empty content
            assert False, "ReadabilityExtractor should not be called for empty content"
    
    # Mock configuration to use InfoQuest engine
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "infoquest"}}

    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Empty Content"
    assert "No content could be extracted from this page" in article.html_content


def test_crawler_with_infoquest_non_html_content(monkeypatch):
    """Test that the crawler handles non-HTML content from InfoQuest client gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            pass
            
        def crawl(self, url, return_format=None):
            return "This is plain text content from InfoQuest, not HTML"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for non-HTML content
            assert False, "ReadabilityExtractor should not be called for non-HTML content"

    # Mock configuration to use InfoQuest engine
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "infoquest"}}
        
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title in ["Non-HTML Content", "Content Extraction Failed"]
    assert "cannot be parsed as HTML" in article.html_content or "Content extraction failed" in article.html_content
    assert "plain text content from InfoQuest" in article.html_content


def test_crawler_with_infoquest_error_response(monkeypatch):
    """Test that the crawler handles error responses from InfoQuest client gracefully."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            pass
            
        def crawl(self, url, return_format=None):
            return "Error: InfoQuest API returned status 403: Forbidden"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            # This should not be called for error responses
            assert False, "ReadabilityExtractor should not be called for error responses"

    # Mock configuration to use InfoQuest engine
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "infoquest"}}
        
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title in ["Non-HTML Content", "Content Extraction Failed"]
    assert "Error: InfoQuest API returned status 403: Forbidden" in article.html_content


def test_crawler_with_infoquest_json_response(monkeypatch):
    """Test that the crawler handles JSON responses from InfoQuest client correctly."""
    
    class DummyArticle:
        def __init__(self, title, html_content):
            self.title = title
            self.html_content = html_content
            self.url = None
        
        def to_markdown(self):
            return f"# {self.title}"

    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            pass
            
        def crawl(self, url, return_format=None):
            return "<html><body>Content from InfoQuest JSON</body></html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            return DummyArticle("Extracted from JSON", html)

    # Mock configuration to use InfoQuest engine
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "infoquest"}}
        
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr(
        "src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor
    )
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    url = "http://example.com"
    article = crawler.crawl(url)
    
    assert article.url == url
    assert article.title == "Extracted from JSON"
    assert "Content from InfoQuest JSON" in article.html_content


def test_infoquest_client_initialization_params():
    """Test that InfoQuestClient correctly initializes with the provided parameters."""
    # Test default parameters
    client_default = InfoQuestClient()
    assert client_default.fetch_time == -1
    assert client_default.timeout == -1
    assert client_default.navi_timeout == -1
    
    # Test custom parameters
    client_custom = InfoQuestClient(fetch_time=30, timeout=60, navi_timeout=45)
    assert client_custom.fetch_time == 30
    assert client_custom.timeout == 60
    assert client_custom.navi_timeout == 45


def test_crawler_with_infoquest_default_parameters(monkeypatch):
    """Test that the crawler initializes InfoQuestClient with default parameters when none are provided."""
    calls = {}

    class DummyInfoQuestClient:
        def __init__(self, fetch_time=None, timeout=None, navi_timeout=None):
            calls["infoquest_init"] = (fetch_time, timeout, navi_timeout)
            
        def crawl(self, url, return_format=None):
            return "<html>dummy</html>"

    class DummyReadabilityExtractor:
        def extract_article(self, html):
            class DummyArticle:
                url = None
                def to_markdown(self):
                    return "# Dummy"
            return DummyArticle()
    
    # Mock configuration to use InfoQuest engine without custom parameters
    def mock_load_config(*args, **kwargs):
        return {"CRAWLER_ENGINE": {"engine": "infoquest"}}
    
    monkeypatch.setattr("src.crawler.crawler.InfoQuestClient", DummyInfoQuestClient)
    monkeypatch.setattr("src.crawler.crawler.ReadabilityExtractor", DummyReadabilityExtractor)
    monkeypatch.setattr("src.crawler.crawler.load_yaml_config", mock_load_config)

    crawler = crawler_module.crawler.Crawler()
    crawler.crawl("http://example.com")
    
    # Verify default parameters were passed
    assert "infoquest_init" in calls
    assert calls["infoquest_init"] == (-1, -1, -1)
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

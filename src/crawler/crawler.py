# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import re
import logging

from src.config.tools import CrawlerEngine
from src.config import load_yaml_config
from src.crawler.article import Article
from src.crawler.infoquest_client import InfoQuestClient
from src.crawler.jina_client import JinaClient
from src.crawler.readability_extractor import ReadabilityExtractor

logger = logging.getLogger(__name__)


def safe_truncate(text: str, max_length: int = 500) -> str:
    """
    Safely truncate text to a maximum length without breaking multi-byte characters.

    Args:
        text: The text to truncate
        max_length: Maximum number of characters to keep

    Returns:
        Truncated text that is safe to use without encoding issues
    """
    if text is None:
        return None

    if len(text) <= max_length:
        return text

    # Ensure max_length is at least 3 to accommodate the placeholder
    if max_length < 3:
        return "..."[:max_length]

    # Use Python's built-in textwrap.shorten which handles unicode safely
    try:
        import textwrap
        return textwrap.shorten(text, width=max_length, placeholder="...")
    except (ImportError, TypeError):
        # Fallback for older Python versions or if textwrap.shorten has issues
        # Truncate to max_length - 3 to make room for "..."
        truncated = text[:max_length - 3]
        # Remove any incomplete Unicode surrogate pair
        while truncated and ord(truncated[-1]) >= 0xD800 and ord(truncated[-1]) <= 0xDFFF:
            truncated = truncated[:-1]
        return truncated + "..."


def is_html_content(content: str) -> bool:
    """
    Check if the provided content is HTML.

    Uses a more robust detection method that checks for common HTML patterns
    including DOCTYPE declarations, HTML tags, and other HTML markers.
    """
    if not content or not content.strip():
        return False

    content = content.strip()

    # Check for HTML comments
    if content.startswith('<!--') and '-->' in content:
        return True

    # Check for DOCTYPE declarations (case insensitive)
    if re.match(r'^<!DOCTYPE\s+html', content, re.IGNORECASE):
        return True

    # Check for XML declarations followed by HTML
    if content.startswith('<?xml') and '<html' in content:
        return True

    # Check for common HTML tags at the beginning
    html_start_patterns = [
        r'^<html',
        r'^<head',
        r'^<body',
        r'^<title',
        r'^<meta',
        r'^<link',
        r'^<script',
        r'^<style',
        r'^<div',
        r'^<p>',
        r'^<p\s',
        r'^<span',
        r'^<h[1-6]',
        r'^<!DOCTYPE',
        r'^<\!DOCTYPE',  # Some variations
    ]

    for pattern in html_start_patterns:
        if re.match(pattern, content, re.IGNORECASE):
            return True

    # Check for any HTML-like tags in the content (more permissive)
    if re.search(r'<[^>]+>', content):
        # Additional check: ensure it's not just XML or other markup
        # Look for common HTML attributes or elements
        html_indicators = [
            r'href\s*=',
            r'src\s*=',
            r'class\s*=',
            r'id\s*=',
            r'<img\s',
            r'<a\s',
            r'<div',
            r'<p>',
            r'<p\s',
            r'<!DOCTYPE',
        ]

        for indicator in html_indicators:
            if re.search(indicator, content, re.IGNORECASE):
                return True

        # Also check for self-closing HTML tags
        self_closing_tags = [
            r'<img\s+[^>]*?/>',
            r'<br\s*/?>',
            r'<hr\s*/?>',
            r'<input\s+[^>]*?/>',
            r'<meta\s+[^>]*?/>',
            r'<link\s+[^>]*?/>',
        ]

        for tag in self_closing_tags:
            if re.search(tag, content, re.IGNORECASE):
                return True

    return False
class Crawler:
    def crawl(self, url: str) -> Article:
        # To help LLMs better understand content, we extract clean
        # articles from HTML, convert them to markdown, and split
        # them into text and image blocks for one single and unified
        # LLM message.
        #
        # The system supports multiple crawler engines:
        # - Jina: An accessible solution, though with some limitations in readability extraction
        # - InfoQuest: A BytePlus product offering advanced capabilities with configurable parameters
        #   like fetch_time, timeout, and navi_timeout.
        #
        # Instead of using Jina's own markdown converter, we'll use
        # our own solution to get better readability results.
        
        # Get crawler configuration
        config = load_yaml_config("conf.yaml")
        crawler_config = config.get("CRAWLER_ENGINE", {})

        # Get the selected crawler tool based on configuration
        crawler_client = self._select_crawler_tool(crawler_config)
        html = self._crawl_with_tool(crawler_client, url)

        # Check if we got valid HTML content
        if not html or not html.strip():
            logger.warning(f"Empty content received from URL {url}")
            article = Article(
                title="Empty Content",
                html_content="<p>No content could be extracted from this page</p>"
            )
            article.url = url
            return article

        # Check if content is actually HTML using more robust detection
        if not is_html_content(html):
            logger.warning(f"Non-HTML content received from URL {url}, creating fallback article")
            # Return a simple article with the raw content (safely truncated)
            article = Article(
                title="Non-HTML Content",
                html_content=f"<p>This URL returned content that cannot be parsed as HTML. Raw content: {safe_truncate(html, 500)}</p>"
            )
            article.url = url
            return article

        # Extract article from HTML
        try:
            extractor = ReadabilityExtractor()
            article = extractor.extract_article(html)
        except Exception as e:
            logger.error(f"Failed to extract article from {url}: {repr(e)}")
            # Fall back to a simple article with the raw HTML (safely truncated)
            article = Article(
                title="Content Extraction Failed",
                html_content=f"<p>Content extraction failed. Raw content: {safe_truncate(html, 500)}</p>"
            )
            article.url = url
            return article
        
        article.url = url
        return article

    def _select_crawler_tool(self, crawler_config: dict):
        # Only check engine from configuration file
        engine = crawler_config.get("engine", CrawlerEngine.JINA.value)
        
        if engine == CrawlerEngine.JINA.value:
            logger.info(f"Selecting Jina crawler engine")
            return JinaClient()
        elif engine == CrawlerEngine.INFOQUEST.value:
            logger.info(f"Selecting InfoQuest crawler engine")
            # Read timeout parameters directly from crawler_config root level
            # These parameters are only effective when engine is set to "infoquest"
            fetch_time = crawler_config.get("fetch_time", -1)
            timeout = crawler_config.get("timeout", -1)
            navi_timeout = crawler_config.get("navi_timeout", -1)

            # Log the configuration being used
            if fetch_time > 0 or timeout > 0 or navi_timeout > 0:
                logger.debug(
                    f"Initializing InfoQuestCrawler with parameters: "
                    f"fetch_time={fetch_time}, "
                    f"timeout={timeout}, "
                    f"navi_timeout={navi_timeout}"
                )

            # Initialize InfoQuestClient with the parameters from configuration
            return InfoQuestClient(
                fetch_time=fetch_time,
                timeout=timeout,
                navi_timeout=navi_timeout
            )
        else:
            raise ValueError(f"Unsupported crawler engine: {engine}")
    
    def _crawl_with_tool(self, crawler_client, url: str) -> str:
        logger.info(f"Crawling URL: {url} using {crawler_client.__class__.__name__}")
        try:
            return crawler_client.crawl(url, return_format="html")
        except Exception as e:
            logger.error(f"Failed to fetch URL {url} using {crawler_client.__class__.__name__}: {repr(e)}")
            raise
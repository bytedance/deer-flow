# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from .article import Article
from .jina_client import JinaClient
from .readability_extractor import ReadabilityExtractor

logger = logging.getLogger(__name__)


class Crawler:
    def crawl(self, url: str) -> Article:
        # To help LLMs better understand content, we extract clean
        # articles from HTML, convert them to markdown, and split
        # them into text and image blocks for one single and unified
        # LLM message.
        #
        # Jina is not the best crawler on readability, however it's
        # much easier and free to use.
        #
        # Instead of using Jina's own markdown converter, we'll use
        # our own solution to get better readability results.
        try:
            jina_client = JinaClient()
            html = jina_client.crawl(url, return_format="html")
        except Exception as e:
            logger.error(f"Failed to fetch URL {url} from Jina: {repr(e)}")
            raise
        
        # Check if we got valid HTML content
        if not html or not html.strip():
            logger.warning(f"Empty content received from URL {url}")
            article = Article(
                title="Empty Content",
                html_content="<p>No content could be extracted from this page</p>"
            )
            article.url = url
            return article
        
        # Check if content is actually HTML
        if not html.strip().startswith('<') or not html.strip().endswith('>'):
            logger.warning(f"Non-HTML content received from URL {url}, creating fallback article")
            # Return a simple article with the raw content
            article = Article(
                title="Non-HTML Content",
                html_content=f"<p>This URL returned content that cannot be parsed as HTML. Raw content: {html[:500]}...</p>"
            )
            article.url = url
            return article
        
        try:
            extractor = ReadabilityExtractor()
            article = extractor.extract_article(html)
        except Exception as e:
            logger.error(f"Failed to extract article from {url}: {repr(e)}")
            # Fall back to a simple article with the raw HTML
            article = Article(
                title="Content Extraction Failed",
                html_content=f"<p>Content extraction failed. Raw content: {html[:500]}...</p>"
            )
            article.url = url
            return article
        
        article.url = url
        return article

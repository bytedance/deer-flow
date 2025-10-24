# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from readabilipy import simple_json_from_html_string

from .article import Article

logger = logging.getLogger(__name__)


class ReadabilityExtractor:
    def extract_article(self, html: str) -> Article:
        article = simple_json_from_html_string(html, use_readability=True)
        
        content = article.get("content")
        if not content or not str(content).strip():
            logger.warning("Readability extraction returned empty content")
            content = "<p>No content could be extracted from this page</p>"
        
        title = article.get("title") or "Untitled"
        
        return Article(
            title=title,
            html_content=content,
        )

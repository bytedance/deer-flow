# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import Annotated
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from langchain_core.tools import tool
from .decorators import log_io

from src.crawler import Crawler

logger = logging.getLogger(__name__)


@tool
@log_io
def crawl_tool(
    url: Annotated[str, "The url to crawl."],
) -> dict:
    """
    Use this to crawl a url.
    Returns a dictionary containing the URL, readable content in markdown format,
    and a list of extracted image items.
    Each image item is a dictionary like: {"type": "image_url", "image_url": {"url": "absolute_image_url"}}
    """
    try:
        crawler = Crawler()
        article = crawler.crawl(url)

        markdown_content = article.to_markdown()[:2000] # Increased limit slightly

        # Extract image information using to_message logic
        message_items = article.to_message()
        extracted_images = []
        # We also need to reconstruct the text if to_message() is the sole source of markdown.
        # For now, let's assume to_markdown() is still primary for text, and we just extract images.
        # A more robust way would be for Article to have a method that returns both separately.

        # Simplified extraction for now:
        image_urls_from_article = []
        soup = BeautifulSoup(article.html_content, "html.parser")
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src")
            if not src or src.startswith("data:image"):
                continue
            absolute_url = urljoin(article.url, src) # Use article.url as base
            # Add some basic filtering if desired, e.g. min width/height if available
            image_urls_from_article.append({"type": "image_url_from_crawl", "url": absolute_url, "original_alt": img_tag.get("alt", "")})

        return {
            "url": url,
            "markdown_content": markdown_content,
            "extracted_images": image_urls_from_article
        }
    except BaseException as e:
        error_msg = f"Failed to crawl {url}. Error: {repr(e)}"
        logger.error(error_msg)
        # Return a dictionary in error cases too for consistency, if possible
        return {"url": url, "error": error_msg, "markdown_content": "", "extracted_images": []}

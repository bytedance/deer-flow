# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
from typing import Annotated
from urllib.parse import urlparse

from langchain_core.tools import tool

from src.crawler import Crawler

from .decorators import log_io

logger = logging.getLogger(__name__)


def is_pdf_url(url: str) -> bool:
    """Check if the URL points to a PDF file."""
    parsed_url = urlparse(url)
    # Check if the path ends with .pdf (case insensitive)
    return parsed_url.path.lower().endswith('.pdf')


@tool
@log_io
def crawl_tool(
    url: Annotated[str, "The url to crawl."],
) -> str:
    """Use this to crawl a url and get a readable content in markdown format."""
    # Special handling for PDF URLs
    if is_pdf_url(url):
        logger.info(f"PDF URL detected, skipping crawling: {url}")
        pdf_message = json.dumps({
            "url": url,
            "error": "PDF files cannot be crawled directly. Please download and view the PDF manually.",
            "crawled_content": None,
            "is_pdf": True
        })
        return pdf_message
    
    try:
        crawler = Crawler()
        article = crawler.crawl(url)
        return json.dumps({"url": url, "crawled_content": article.to_markdown()[:1000]})
    except BaseException as e:
        error_msg = f"Failed to crawl. Error: {repr(e)}"
        logger.error(error_msg)
        return error_msg

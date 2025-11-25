# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from src.config.tools import CrawlerEngine
from src.config import load_yaml_config
from src.crawler.article import Article
from src.crawler.infoquest_client import InfoQuestClient
from src.crawler.jina_client import JinaClient
from src.crawler.readability_extractor import ReadabilityExtractor

logger = logging.getLogger(__name__)


class Crawler:
    def crawl(self, url: str) -> Article:
        # To help LLMs better understand content, we extract clean
        # articles from HTML, convert them to markdown, and split
        # them into text and image blocks for one single and unified
        # LLM message.
        #
        # The system supports multiple crawler engines:
        # - Jina: An accessible and free solution, though with some limitations in readability extraction
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
        
        # Extract article from HTML
        try:
            extractor = ReadabilityExtractor()
            article = extractor.extract_article(html)
        except Exception as e:
            logger.error(f"Failed to extract article from {url}: {repr(e)}")
            raise
        
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
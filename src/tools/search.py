# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
from typing import List, Optional

from langchain_community.tools import (
    BraveSearch,
    DuckDuckGoSearchResults,
    SearxSearchRun,
    WikipediaQueryRun,
)
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.utilities import (
    ArxivAPIWrapper,
    BraveSearchWrapper,
    SearxSearchWrapper,
    WikipediaAPIWrapper,
)

from src.config import SELECTED_SEARCH_ENGINE, SearchEngine, load_yaml_config
from src.tools.bocha_search.bocha_search_tool import BochaSearchTool
from src.tools.decorators import create_logged_tool
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchWithImages,
)

logger = logging.getLogger(__name__)

# Create logged versions of the search tools
LoggedTavilySearch = create_logged_tool(TavilySearchWithImages)
LoggedBochaSearch = create_logged_tool(BochaSearchTool)
LoggedDuckDuckGoSearch = create_logged_tool(DuckDuckGoSearchResults)
LoggedBraveSearch = create_logged_tool(BraveSearch)
LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
LoggedSearxSearch = create_logged_tool(SearxSearchRun)
LoggedWikipediaSearch = create_logged_tool(WikipediaQueryRun)


def get_search_config():
    config = load_yaml_config("conf.yaml")
    search_config = config.get("SEARCH_ENGINE", {})
    return search_config


# Get the selected search tool
def get_web_search_tool(max_search_results: int):
    search_config = get_search_config()

    if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
        # Get all Tavily search parameters from configuration with defaults
        include_domains: Optional[List[str]] = search_config.get("include_domains", [])
        exclude_domains: Optional[List[str]] = search_config.get("exclude_domains", [])
        include_answer: bool = search_config.get("include_answer", False)
        search_depth: str = search_config.get("search_depth", "advanced")
        include_raw_content: bool = search_config.get("include_raw_content", True)
        include_images: bool = search_config.get("include_images", True)
        include_image_descriptions: bool = include_images and search_config.get(
            "include_image_descriptions", True
        )

        logger.info(
            f"Tavily search configuration loaded: include_domains={include_domains}, "
            f"exclude_domains={exclude_domains}, include_answer={include_answer}, "
            f"search_depth={search_depth}, include_raw_content={include_raw_content}, "
            f"include_images={include_images}, include_image_descriptions={include_image_descriptions}"
        )

        return LoggedTavilySearch(
            name="web_search",
            max_results=max_search_results,
            include_answer=include_answer,
            search_depth=search_depth,
            include_raw_content=include_raw_content,
            include_images=include_images,
            include_image_descriptions=include_image_descriptions,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.BOCHA.value:
        # Bocha-specific configuration: freshness & summary are read from SEARCH_ENGINE section.
        freshness: str = search_config.get("freshness", "noLimit")
        summary: bool = search_config.get("summary", True)

        logger.info(
            "Bocha search configuration loaded: freshness=%s, summary=%s, max_results=%s",
            freshness,
            summary,
            max_search_results,
        )

        return LoggedBochaSearch(
            name="web_search",
            max_results=max_search_results,
            freshness=freshness,
            summary=summary,
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.DUCKDUCKGO.value:
        return LoggedDuckDuckGoSearch(
            name="web_search",
            num_results=max_search_results,
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.BRAVE_SEARCH.value:
        return LoggedBraveSearch(
            name="web_search",
            search_wrapper=BraveSearchWrapper(
                api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
                search_kwargs={"count": max_search_results},
            ),
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.ARXIV.value:
        return LoggedArxivSearch(
            name="web_search",
            api_wrapper=ArxivAPIWrapper(
                top_k_results=max_search_results,
                load_max_docs=max_search_results,
                load_all_available_meta=True,
            ),
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.SEARX.value:
        return LoggedSearxSearch(
            name="web_search",
            wrapper=SearxSearchWrapper(
                k=max_search_results,
            ),
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.WIKIPEDIA.value:
        wiki_lang = search_config.get("wikipedia_lang", "en")
        wiki_doc_content_chars_max = search_config.get(
            "wikipedia_doc_content_chars_max", 4000
        )
        return LoggedWikipediaSearch(
            name="web_search",
            api_wrapper=WikipediaAPIWrapper(
                lang=wiki_lang,
                top_k_results=max_search_results,
                load_all_available_meta=True,
                doc_content_chars_max=wiki_doc_content_chars_max,
            ),
        )
    else:
        raise ValueError(f"Unsupported search engine: {SELECTED_SEARCH_ENGINE}")

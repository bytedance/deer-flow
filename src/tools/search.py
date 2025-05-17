# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os

from langchain_community.tools import BraveSearch, DuckDuckGoSearchResults
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.tools.searx_search.tool import SearxSearchResults
from langchain_community.utilities import ArxivAPIWrapper, BraveSearchWrapper, SearxSearchWrapper

from src.config import SEARCH_MAX_RESULTS, SearchEngine
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchResultsWithImages,
)

from src.tools.decorators import create_logged_tool

logger = logging.getLogger(__name__)

LoggedTavilySearch = create_logged_tool(TavilySearchResultsWithImages)
if os.getenv("SEARCH_API", "") == SearchEngine.TAVILY.value:
    tavily_search_tool = LoggedTavilySearch(
        name="web_search",
        max_results=SEARCH_MAX_RESULTS,
        include_raw_content=True,
        include_images=True,
        include_image_descriptions=True,
    )
else:
    tavily_search_tool = None

LoggedDuckDuckGoSearch = create_logged_tool(DuckDuckGoSearchResults)
duckduckgo_search_tool = LoggedDuckDuckGoSearch(
    name="web_search", max_results=SEARCH_MAX_RESULTS
)

LoggedBraveSearch = create_logged_tool(BraveSearch)
brave_search_tool = LoggedBraveSearch(
    name="web_search",
    search_wrapper=BraveSearchWrapper(
        api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
        search_kwargs={"count": SEARCH_MAX_RESULTS},
    ),
)

LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
arxiv_search_tool = LoggedArxivSearch(
    name="web_search",
    api_wrapper=ArxivAPIWrapper(
        top_k_results=SEARCH_MAX_RESULTS,
        load_max_docs=SEARCH_MAX_RESULTS,
        load_all_available_meta=True,
    ),
)

LoggedSearxSearch = create_logged_tool(SearxSearchResults)
searx_search_tool = LoggedSearxSearch(
    name="web_search",
    wrapper = SearxSearchWrapper(
        searx_host=os.getenv("SEARXNG_API_URL", "http://localhost:8081"),
    ),
)

if __name__ == "__main__":
    results = LoggedDuckDuckGoSearch(
        name="web_search", max_results=SEARCH_MAX_RESULTS, output_format="list"
    ).invoke("cute panda")
    print(json.dumps(results, indent=2, ensure_ascii=False))

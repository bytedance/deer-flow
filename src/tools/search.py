# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
import re

from langchain_community.tools import BraveSearch, DuckDuckGoSearchResults
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.utilities import ArxivAPIWrapper, BraveSearchWrapper

from src.config import SearchEngine, SELECTED_SEARCH_ENGINE
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchResultsWithImages,
)
from src.tools.volcano_search.volcano_search_results import VolcanoSearchResults
from src.tools.sogou_search.sogou_search_results import SogouSearchResults
from src.tools.decorators import create_logged_tool

logger = logging.getLogger(__name__)

# Create logged versions of the search tools
LoggedTavilySearch = create_logged_tool(TavilySearchResultsWithImages)
LoggedDuckDuckGoSearch = create_logged_tool(DuckDuckGoSearchResults)
LoggedBraveSearch = create_logged_tool(BraveSearch)
LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
LoggedVolcanoSearch = create_logged_tool(VolcanoSearchResults)
LoggedSogouSearch = create_logged_tool(SogouSearchResults)

# Get the selected search tool
def get_web_search_tool(max_search_results: int):
    logger.info(f"SELECTED_SEARCH_ENGINE: {SELECTED_SEARCH_ENGINE}")
    if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
        return LoggedTavilySearch(
            name="web_search",
            max_results=max_search_results,
            include_raw_content=False, # TODO 这个会很长，先不加
            include_images=True,
            include_image_descriptions=True,
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.DUCKDUCKGO.value:
        return LoggedDuckDuckGoSearch(name="web_search", max_results=max_search_results)
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
    elif SELECTED_SEARCH_ENGINE == SearchEngine.VOLCANO.value:
        return LoggedVolcanoSearch(
            name="web_search",
            max_results=max_search_results,
        )
    elif SELECTED_SEARCH_ENGINE == SearchEngine.SOGOU.value:
        return LoggedSogouSearch(
            name="web_search",
            max_results=max_search_results,
        )
    else:
        raise ValueError(f"Unsupported search engine: {SELECTED_SEARCH_ENGINE}")

def filter_garbled_text(text):
    """
    过滤掉字符串中的乱码内容
    :param text: 输入的字符串
    :return: 过滤后的字符串
    """
    # 使用正则表达式匹配乱码内容,保留空格和英文标点符号
    pattern = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\ufe30\uffa0-\uffa9\uff3f\uff00-\uffa0\u2000-\u206f\u3000-\u303f\ufb00-\uffa0,.?!:;\'"()\[\]{}\/<>@#$%^&*_+\-=]+')
    filtered_text = re.sub(pattern, '', text)
    return filtered_text

if __name__ == "__main__":
    results = LoggedDuckDuckGoSearch(
        name="web_search", max_results=3, output_format="list"
    )
    print(results.name)
    print(results.description)
    print(results.args)
    # .invoke("cute panda")
    # print(json.dumps(results, indent=2, ensure_ascii=False))

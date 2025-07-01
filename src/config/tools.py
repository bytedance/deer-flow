# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import enum
from dotenv import load_dotenv

load_dotenv()


class SearchEngine(enum.Enum):
    TAVILY = "tavily"
    DUCKDUCKGO = "duckduckgo"
    BRAVE_SEARCH = "brave_search"
    ARXIV = "arxiv"
    VOLCANO = "volcano"  # 新增火山引擎
    SOGOU = "sogou" # 新增搜狗搜索


# Tool configuration
SELECTED_SEARCH_ENGINE = os.getenv("SEARCH_API", SearchEngine.VOLCANO.value)


class RAGProvider(enum.Enum):
    RAGFLOW = "ragflow"


SELECTED_RAG_PROVIDER = os.getenv("RAG_PROVIDER")

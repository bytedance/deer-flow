# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import enum
import os

from dotenv import load_dotenv

load_dotenv()


class SearchEngine(enum.Enum):
    TAVILY = "tavily"
    INFOQUEST = "infoquest"
    DUCKDUCKGO = "duckduckgo"
    BRAVE_SEARCH = "brave_search"
    ARXIV = "arxiv"
    SEARX = "searx"
    WIKIPEDIA = "wikipedia"
    BOCHA = "bocha"


class CrawlerEngine(enum.Enum):
    JINA = "jina"
    INFOQUEST = "infoquest"


# Tool configuration
# Default to Bocha for intranet deployments; can be overridden by SEARCH_API env.
SELECTED_SEARCH_ENGINE = os.getenv("SEARCH_API", SearchEngine.BOCHA.value)

class RAGProvider(enum.Enum):
    DIFY = "dify"
    RAGFLOW = "ragflow"
    VIKINGDB_KNOWLEDGE_BASE = "vikingdb_knowledge_base"
    MOI = "moi"
    MILVUS = "milvus"
    QDRANT = "qdrant"


SELECTED_RAG_PROVIDER = os.getenv("RAG_PROVIDER")

# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
from typing import Dict, List, Optional, Tuple, Union

from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain.tools import BaseTool
from pydantic import Field

from src.tools.bocha_search.bocha_search_api_wrapper import BochaSearchAPIWrapper

logger = logging.getLogger(__name__)


class BochaSearchTool(BaseTool):
    """LangChain tool for Bocha Web Search.

    This tool calls the BochaSearchAPIWrapper, normalizes results and returns
    a JSON string that matches the internal search result schema used by
    DeerFlow (same as Tavily integration).
    """

    name: str = "web_search"
    description: str = (
        "使用 Bocha Web Search API 进行互联网搜索，返回整理后的 JSON 结果，"
        "每条结果包含标题、URL、摘要以及可选的站点信息。"
    )

    # Configurable parameters (wired from SEARCH_ENGINE config & workflow)
    max_results: int = 5
    freshness: str = "noLimit"
    summary: bool = True

    api_wrapper: BochaSearchAPIWrapper = Field(  # type: ignore[assignment]
        default_factory=BochaSearchAPIWrapper
    )

    def _run(
        self,
        query: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **tool_kwargs,
    ) -> Tuple[Union[List[Dict[str, str]], str], Dict]:
        """Synchronously call Bocha search and return (json_string, raw_results).

        Notes
        -----
        LangChain/LangGraph may pass tool arguments in different formats,
        e.g. as positional input, as ``query=...``, or nested inside a
        ``kwargs`` dict. This implementation normalizes these forms and
        always extracts the final query string.
        """

        # Normalize query from various invocation patterns
        if query is None:
            # Common case: query is inside tool_kwargs["query"]
            query = tool_kwargs.get("query")

        # Some newer tool-call formats wrap arguments in a "kwargs" dict
        if query is None and "kwargs" in tool_kwargs and isinstance(tool_kwargs["kwargs"], dict):
            query = tool_kwargs["kwargs"].get("query")

        if query is None:
            error_result = json.dumps(
                {"error": "BochaSearchTool requires a 'query' argument"},
                ensure_ascii=False,
            )
            logger.error("BochaSearchTool._run called without query: tool_kwargs=%s", tool_kwargs)
            return error_result, {}

        logger.info(
            "BochaSearchTool running (sync): query=%s, max_results=%s, freshness=%s, summary=%s",
            query,
            self.max_results,
            self.freshness,
            self.summary,
        )

        try:
            raw = self.api_wrapper.raw_results(
                query=query,
                max_results=self.max_results,
                freshness=self.freshness,
                summary=self.summary,
            )
            cleaned = self.api_wrapper.clean_results(raw)
        except Exception as e:  # pragma: no cover - defensive logging
            logger.error("Bocha search returned error: %s", e)
            error_result = json.dumps({"error": repr(e)}, ensure_ascii=False)
            return error_result, {}

        logger.debug(
            "Bocha search cleaned results: %s",
            json.dumps(cleaned, ensure_ascii=False)[:1000],
        )
        result_json = json.dumps(cleaned, ensure_ascii=False)
        return result_json, raw

    async def _arun(
        self,
        query: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **tool_kwargs,
    ) -> Tuple[Union[List[Dict[str, str]], str], Dict]:
        """Asynchronously call Bocha search.

        Mirrors Tavily's async tool behavior by delegating to the
        API wrapper's raw_results_async method and returning the
        same (json_string, raw_results) contract.
        """

        # Normalize query from various invocation patterns
        if query is None:
            query = tool_kwargs.get("query")
        if query is None and "kwargs" in tool_kwargs and isinstance(tool_kwargs["kwargs"], dict):
            query = tool_kwargs["kwargs"].get("query")

        if query is None:
            error_result = json.dumps(
                {"error": "BochaSearchTool requires a 'query' argument"},
                ensure_ascii=False,
            )
            logger.error("BochaSearchTool._arun called without query: tool_kwargs=%s", tool_kwargs)
            return error_result, {}

        logger.info(
            "BochaSearchTool running (async): query=%s, max_results=%s, freshness=%s, summary=%s",
            query,
            self.max_results,
            self.freshness,
            self.summary,
        )

        try:
            raw = await self.api_wrapper.raw_results_async(
                query=query,
                max_results=self.max_results,
                freshness=self.freshness,
                summary=self.summary,
            )
            cleaned = self.api_wrapper.clean_results(raw)
        except Exception as e:  # pragma: no cover - defensive logging
            logger.error("Bocha search returned error (async): %s", e)
            error_result = json.dumps({"error": repr(e)}, ensure_ascii=False)
            return error_result, {}

        logger.debug(
            "Bocha search cleaned results (async): %s",
            json.dumps(cleaned, ensure_ascii=False)[:1000],
        )
        result_json = json.dumps(cleaned, ensure_ascii=False)
        return result_json, raw

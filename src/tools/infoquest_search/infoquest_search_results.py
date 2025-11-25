# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Tool for the InfoQuest search API."""

import json
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, Union
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.tools.infoquest_search.infoquest_search_api import InfoQuestAPIWrapper

logger = logging.getLogger(__name__)

class InfoQuestInput(BaseModel):
    """Input for the InfoQuest tool."""

    query: str = Field(description="search query to look up")

class InfoQuestSearchResults(BaseTool):
    """Tool that queries the InfoQuest Search API and returns processed results with images.

Setup:
    Install required packages and set environment variable ``INFOQUEST_API_KEY``.

    .. code-block:: bash

        pip install -U langchain-community aiohttp
        export INFOQUEST_API_KEY="your-api-key"

Instantiate:
    .. code-block:: python

        from your_module import InfoQuestSearch 

        tool = InfoQuestSearchResults(
            output_format="json",
            time_range=10,
            site="nytimes.com"
        )

Invoke directly with args:
    .. code-block:: python

        tool.invoke({
            'query': 'who won the last french open'
        })

    .. code-block:: json

        [
            {
                "type": "page",
                "title": "Djokovic Claims French Open Title...",
                "url": "https://www.nytimes.com/...",
                "desc": "Novak Djokovic won the 2024 French Open by defeating Casper Ruud..."
            },
            {
                "type": "news",
                "time_frame": "2 days ago",
                "title": "French Open Finals Recap",
                "url": "https://www.nytimes.com/...",
                "source": "New York Times"
            },
            {
                "type": "image_url",
                "image_url": {"url": "https://www.nytimes.com/.../djokovic.jpg"},
                "image_description": "Novak Djokovic celebrating his French Open victory"
            }
        ]

Invoke with tool call:
    .. code-block:: python

        tool.invoke({
            "args": {
                'query': 'who won the last french open',
            },
            "type": "tool_call",
            "id": "foo",
            "name": "infoquest"
        })

    .. code-block:: python

        ToolMessage(
            content='[
                {"type": "page", "title": "Djokovic Claims...", "url": "https://www.nytimes.com/...", "desc": "Novak Djokovic won..."},
                {"type": "news", "time_frame": "2 days ago", "title": "French Open Finals...", "url": "https://www.nytimes.com/...", "source": "New York Times"},
                {"type": "image_url", "image_url": {"url": "https://www.nytimes.com/.../djokovic.jpg"}, "image_description": "Novak Djokovic celebrating..."}
            ]',
            tool_call_id='1',
            name='infoquest_search_results_json',
        )


    """  # noqa: E501

    name: str = "infoquest_search_results_json"
    description: str = (
        "A search engine optimized for comprehensive, accurate, and trusted results. "
        "Useful for when you need to answer questions about current events. "
        "Input should be a search query."
    )
    args_schema: Type[BaseModel] = InfoQuestInput
    """The tool response format."""

    time_range: int = -1,
    """Time range for filtering search results, in days.

    If set to a positive integer (e.g., 30), only results from the last N days will be included.
    Default is -1, which means no time range filter is applied.
    """

    site: str = "",
    """Specific domain to restrict search results to (e.g., "nytimes.com").

    If provided, only results from the specified domain will be returned.
    Default is an empty string, which means no domain restriction is applied.
    """

    api_wrapper: InfoQuestAPIWrapper = Field(default_factory=InfoQuestAPIWrapper)  # type: ignore[arg-type]
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    def __init__(self, **kwargs: Any) -> None:
        # Create api_wrapper with infoquest_api_key if provided
        if "infoquest_api_key" in kwargs:
            kwargs["api_wrapper"] = InfoQuestAPIWrapper(
                infoquest_api_key=kwargs["infoquest_api_key"]
            )
            logger.debug("API wrapper initialized with provided key")

        super().__init__(**kwargs)

        logger.info(
            "\n============================================\n"
            "🚀 BytePlus InfoQuest Search Initialization 🚀\n"
            "============================================"
        )
        
        # Prepare initialization details
        time_range_status = f"{self.time_range} days" if hasattr(self, 'time_range') and self.time_range > 0 else "Disabled"
        site_filter = f"'{self.site}'" if hasattr(self, 'site') and self.site else "Disabled"
        
        initialization_details = (
            f"🔧 Tool Information:\n"
            f"├── Tool Name: {self.name}\n"
            f"├── Time Range Filter: {time_range_status}\n"
            f"└── Site Filter: {site_filter}\n"
            f"📊 Configuration Summary:\n"
            f"├── Response Format: {self.response_format}\n"
        )
        
        logger.info(initialization_details)
        logger.info("\n" + "*" * 70 + "\n")

    def _run(
            self,
            query: str,
            run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Tuple[Union[List[Dict[str, str]], str], Dict]:
        """Use the tool."""
        try:
            logger.debug(f"Executing search with parameters: time_range={self.time_range}, site={self.site}")
            raw_results = self.api_wrapper.raw_results(
                query,
                self.time_range,
                self.site
            )
            logger.debug("Processing raw search results")
            cleaned_results = self.api_wrapper.clean_results_with_images(raw_results["results"])

            result_json = json.dumps(cleaned_results, ensure_ascii=False)

            logger.info(
                f"Search tool execution completed | "
                f"mode=synchronous | "
                f"results_count={len(cleaned_results)}"
            )
            return result_json, raw_results
        except Exception as e:
            logger.error(
                f"Search tool execution failed | "
                f"mode=synchronous | "
                f"error={str(e)}"
            )
            error_result = json.dumps({"error": repr(e)}, ensure_ascii=False)
            return error_result, {}

    async def _arun(
            self,
            query: str,
            run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> Tuple[Union[List[Dict[str, str]], str], Dict]:
        """Use the tool asynchronously."""
        if logger.isEnabledFor(logging.DEBUG):
            query_truncated = query[:50] + "..." if len(query) > 50 else query
            logger.debug(
                f"Search tool execution started | "
                f"mode=asynchronous | "
                f"query={query_truncated}"
            )
        try:
            logger.debug(f"Executing async search with parameters: time_range={self.time_range}, site={self.site}")

            raw_results = await self.api_wrapper.raw_results_async(
                query,
                self.time_range,
                self.site
            )

            logger.debug("Processing raw async search results")
            cleaned_results = self.api_wrapper.clean_results_with_images(raw_results["results"])

            result_json = json.dumps(cleaned_results, ensure_ascii=False)

            logger.debug(
                f"Search tool execution completed | "
                f"mode=asynchronous | "
                f"results_count={len(cleaned_results)}"
            )

            return result_json, raw_results
        except Exception as e:
            logger.error(
                f"Search tool execution failed | "
                f"mode=asynchronous | "
                f"error={str(e)}"
            )
            error_result = json.dumps({"error": repr(e)}, ensure_ascii=False)
            return error_result, {}
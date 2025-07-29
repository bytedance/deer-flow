import logging
import os
from typing import Any, Literal, Type

from alibabacloud_iqs20241111 import models
from alibabacloud_iqs20241111.client import Client
from alibabacloud_tea_openapi import models as open_api_models
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from Tea.exceptions import TeaException

logger = logging.getLogger(__name__)


class GenericSearchInput(BaseModel):
    """Input for GenericSearch tool."""

    query: str = Field(description="Search keyword, length 1-100 characters")
    time_range: (
        Literal["NoLimit", "OneDay", "OneWeek", "OneMonth", "OneYear"] | None
    ) = Field(
        default="NoLimit",
        description="Time range. Supported values: NoLimit(no limit), OneDay(last day), OneWeek(last week), OneMonth(last month), OneYear(last year)",
    )
    industry: (
        Literal[
            "finance",
            "law",
            "medical",
            "internet",
            "tax",
            "news_province",
            "news_center",
        ]
        | None
    ) = Field(
        default=None,
        description="Industry search, multiple industries separated by commas. Supported values: finance, law, medical, internet, tax, news_province, news_center",
    )
    page: int | None = Field(default=1, description="Page number, default is 1")
    return_main_text: bool | None = Field(
        default=True, description="Whether to return the main text of the webpage"
    )
    return_markdown_text: bool | None = Field(
        default=True,
        description="Whether to return the webpage content in markdown format",
    )
    enable_rerank: bool | None = Field(
        default=True, description="Whether to enable reranking"
    )


class GenericSearchTool(BaseTool):
    """Alibaba Cloud Generic Search Tool, based on the IQS service's GenericSearch interface."""

    name: str = "generic_search"
    description: str = """
    Alibaba Cloud Generic Search Tool, providing high-quality web search results.

    Features:
    - Supports time range filtering
    - Supports vertical industry search
    - Returns structured search results including title, summary, main text, etc.
    - Supports reranking to improve relevance

    Suitable scenarios:
    - Obtain the latest information and news
    - Professional industry information search
    - Research tasks requiring high-quality search results
    """
    max_results: int = 10
    client: Client | None = None
    args_schema: Type[BaseModel] = GenericSearchInput

    def __init__(self, max_results: int = 10, **kwargs):
        super().__init__(**kwargs)
        self.max_results = max_results
        self.client = self._create_client()

    def _create_client(self) -> Client:
        """Create Alibaba Cloud IQS client"""
        config = open_api_models.Config(
            access_key_id=os.environ.get("GENERIC_SEARCH_ACCESS_KEY"),
            access_key_secret=os.environ.get("GENERIC_SEARCH_ACCESS_SECRET"),
        )
        config.endpoint = os.environ.get("GENERIC_SEARCH_ENDPOINT")

        if not config.access_key_id or not config.access_key_secret:
            logger.warning(
                "Alibaba Cloud access credentials are not configured. Please set GENERIC_SEARCH_ACCESS_KEY and GENERIC_SEARCH_ACCESS_*"
            )

        return Client(config)

    def _validate_query(self, query: str) -> str | None:
        """Validate query parameters"""
        if not query:
            return "Error: Search keyword cannot be empty"
        if len(query) > 100:
            return "Error: Search keyword length cannot exceed 100 characters"
        return None

    def _handle_search_results(
        self, result: models.GenericSearchResult, operation: str = "search"
    ) -> list[dict[str, Any]]:
        """Parse search results into standard format."""
        page_items = result.page_items or []
        logger.info(
            f"{operation}: {result.request_id}, number of results: {len(page_items)}"
        )

        # Parse and limit the number of results
        parsed_results = [
            self._parse_item(item) for item in page_items[: self.max_results]
        ]

        # Log search meta information
        if search_info := result.search_information:
            logger.info(
                f"{operation} completed - total results: {search_info.total or 0}, "
                f"time taken: {search_info.search_time or 0}ms"
            )

        return parsed_results

    def _parse_item(self, item) -> dict[str, Any]:
        """Parse a single search result item"""
        parsed_item = {
            "title": item.title or "",
            "url": item.link or "",
            "snippet": item.snippet or "",
            "content": item.main_text or item.snippet or "",
            "publish_time": item.publish_time,
            "score": item.score,
            "card_type": item.card_type or "",
            "hostname": (
                item.page_map.get("hostname") if isinstance(item.page_map, dict) else ""
            ),
            "site_label": (
                item.page_map.get("siteLabel")
                if isinstance(item.page_map, dict)
                else ""
            ),
        }

        # Add optional content
        if item.markdown_text:
            parsed_item["markdown_content"] = item.markdown_text

        if item.images:
            parsed_item["images"] = [
                {
                    "url": img.image_link or "",
                    "width": img.width,
                    "height": img.height,
                }
                for img in item.images
            ]

        return parsed_item

    def _handle_tea_exception(self, e: TeaException, operation: str = "search") -> str:
        """Handle TeaException"""
        code = e.code
        request_id = e.data.get("requestId") if isinstance(e.data, dict) else None
        message = e.data.get("message") if isinstance(e.data, dict) else str(e)
        error_msg = f"{operation} API exception, requestId: {request_id}, code: {code}, message: {message}"
        logger.error(error_msg)
        return error_msg

    def _handle_general_exception(self, e: Exception, operation: str = "search") -> str:
        """Handle general exception"""
        error_msg = f"{operation} failed: {str(e)}"
        logger.error(error_msg)
        return error_msg

    def _run(
        self,
        query: str,
        time_range: str = "NoLimit",
        industry: str | None = None,
        page: int = 1,
        return_main_text: bool = True,
        return_markdown_text: bool = True,
        enable_rerank: bool = True,
    ) -> str | list[dict[str, Any]]:
        """Execute synchronous search."""
        if validation_error := self._validate_query(query):
            return validation_error
        try:
            request = models.GenericSearchRequest(
                query=query,
                time_range=time_range,
                industry=industry,
                page=page,
                return_main_text=return_main_text,
                return_markdown_text=return_markdown_text,
                enable_rerank=enable_rerank,
            )
            response = self.client.generic_search(request)
            return self._handle_search_results(response.body, "synchronous search")
        except TeaException as e:
            return self._handle_tea_exception(e, "synchronous search")
        except Exception as e:
            return self._handle_general_exception(e, "synchronous search")

    async def _arun(
        self,
        query: str,
        time_range: str = "NoLimit",
        industry: str | None = None,
        page: int = 1,
        return_main_text: bool = True,
        return_markdown_text: bool = True,
        enable_rerank: bool = True,
    ) -> str | list[dict[str, Any]]:
        """Execute asynchronous search."""
        if validation_error := self._validate_query(query):
            return validation_error

        try:
            request = models.GenericSearchRequest(
                query=query,
                time_range=time_range,
                industry=industry,
                page=page,
                return_main_text=return_main_text,
                return_markdown_text=return_markdown_text,
                enable_rerank=enable_rerank,
            )
            response = await self.client.generic_search_async(request)
            return self._handle_search_results(response.body, "asynchronous search")
        except TeaException as e:
            return self._handle_tea_exception(e, "asynchronous search")
        except Exception as e:
            return self._handle_general_exception(e, "asynchronous generic search")

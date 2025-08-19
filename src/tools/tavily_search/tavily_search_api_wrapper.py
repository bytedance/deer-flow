# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
from typing import Dict, List, Optional

import aiohttp
import requests
from langchain_tavily._utilities import TAVILY_API_URL
from langchain_tavily.tavily_search import (
    TavilySearchAPIWrapper as OriginalTavilySearchAPIWrapper,
)


class EnhancedTavilySearchAPIWrapper(OriginalTavilySearchAPIWrapper):
    def raw_results(
        self,
        query: str,
        max_results: Optional[int] = 5,
        search_depth: Optional[str] = "advanced",
        include_domains: Optional[List[str]] = [],
        exclude_domains: Optional[List[str]] = [],
        include_answer: Optional[bool] = False,
        include_raw_content: Optional[bool] = False,
        include_images: Optional[bool] = False,
        include_image_descriptions: Optional[bool] = False,
    ) -> Dict:
        params = {
            "api_key": self.tavily_api_key.get_secret_value(),
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
            "include_image_descriptions": include_image_descriptions,
        }
        response = requests.post(
            # type: ignore
            f"{TAVILY_API_URL}/search",
            json=params,
        )
        response.raise_for_status()
        return response.json()

    async def raw_results_async(
        self,
        query: str,
        max_results: Optional[int] = 5,
        search_depth: Optional[str] = "advanced",
        include_domains: Optional[List[str]] = [],
        exclude_domains: Optional[List[str]] = [],
        include_answer: Optional[bool] = False,
        include_raw_content: Optional[bool] = False,
        include_images: Optional[bool] = False,
        include_image_descriptions: Optional[bool] = False,
    ) -> Dict:
        """Get results from the Tavily Search API asynchronously."""

        # Function to perform the API call
        async def fetch() -> str:
            params = {
                "api_key": self.tavily_api_key.get_secret_value(),
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
                "include_answer": include_answer,
                "include_raw_content": include_raw_content,
                "include_images": include_images,
                "include_image_descriptions": include_image_descriptions,
            }
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(f"{TAVILY_API_URL}/search", json=params) as res:
                    if res.status == 200:
                        data = await res.text()
                        return data
                    else:
                        raise Exception(f"Error {res.status}: {res.reason}")

        results_json_str = await fetch()
        return json.loads(results_json_str)

    def clean_results_with_images(
        self, raw_results: Dict[str, List[Dict]]
    ) -> List[Dict]:
        results = raw_results["results"]
        """Clean results from Tavily Search API."""
        clean_results = []
        for result in results:
            clean_result = {
                "type": "page",
                "title": result["title"],
                "url": result["url"],
                "content": result["content"],
                "score": result["score"],
            }
            if raw_content := result.get("raw_content"):
                clean_result["raw_content"] = raw_content
            clean_results.append(clean_result)
        images = raw_results["images"]
        for image in images:
            clean_result = {
                "type": "image",
                "image_url": image["url"],
                "image_description": image["description"],
            }
            clean_results.append(clean_result)
        return clean_results

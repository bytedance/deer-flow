# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Util that calls InfoQuest Search API.

In order to set this up, follow instructions at:
https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest
"""

import json
from typing import Any, Dict, List

import aiohttp
import requests
from langchain_core.utils import get_from_dict_or_env
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator
from src.config import load_yaml_config
import logging

logger = logging.getLogger(__name__)

INFOQUEST_API_URL = "https://search.infoquest.bytepluses.com"

def get_search_config():
    config = load_yaml_config("conf.yaml")
    search_config = config.get("SEARCH_ENGINE", {})
    return search_config

class InfoQuestAPIWrapper(BaseModel):
    """Wrapper for InfoQuest Search API."""

    infoquest_api_key: SecretStr
    model_config = ConfigDict(
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_environment(cls, values: Dict) -> Any:
        """Validate that api key and endpoint exists in environment."""
        logger.info("Initializing BytePlus InfoQuest Product - Search API client")

        infoquest_api_key = get_from_dict_or_env(
            values, "infoquest_api_key", "INFOQUEST_API_KEY"
        )
        values["infoquest_api_key"] = infoquest_api_key

        logger.info("BytePlus InfoQuest Product - Environment validation successful")
        return values

    def raw_results(
        self,
        query: str,
        time_range: int,
        site: str,
        output_format: str="JSON",
    ) -> Dict:
        """Get results from the InfoQuest Search API synchronously."""
        if logger.isEnabledFor(logging.DEBUG):
            query_truncated = query[:50] + "..." if len(query) > 50 else query
            logger.debug(
                f"InfoQuest - Search API request initiated | "
                f"operation=search | "
                f"query_truncated={query_truncated} | "
                f"has_time_filter={time_range > 0} | "
                f"has_site_filter={bool(site)} | "
                f"request_type=sync"
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.infoquest_api_key.get_secret_value()}",
        }

        params = {
            "format": output_format,
            "query": query
        }
        if time_range >0:
            params["time_range"] = time_range
            logger.debug(f"InfoQuest - Applying time range filter: time_range_days={time_range}")

        if site != "":
            params["site"] = site
            logger.debug(f"InfoQuest - Applying site filter: site={site}")

        response = requests.post(
            f"{INFOQUEST_API_URL}",
            headers=headers,
            json=params
        )
        response.raise_for_status()

        # Print partial response for debugging
        response_json = response.json()
        if logger.isEnabledFor(logging.DEBUG):
            response_sample = json.dumps(response_json)[:200] + ("..." if len(json.dumps(response_json)) > 200 else "")
            logger.debug(
                f"Search API request completed successfully | "
                f"service=InfoQuest | "
                f"status=success | "
                f"response_sample={response_sample}"
            )

        return response_json["search_result"]

    async def raw_results_async(
        self,
        query: str,
        time_range: int,
        site: str,
        output_format: str = "JSON",
    ) -> Dict:
        """Get results from the InfoQuest Search API asynchronously."""

        if logger.isEnabledFor(logging.DEBUG):
            query_truncated = query[:50] + "..." if len(query) > 50 else query
            logger.debug(
                f"BytePlus InfoQuest - Search API async request initiated | "
                f"operation=search | "
                f"query_truncated={query_truncated} | "
                f"has_time_filter={time_range > 0} | "
                f"has_site_filter={bool(site)} | "
                f"request_type=async"
            )
        # Function to perform the API call
        async def fetch() -> str:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.infoquest_api_key.get_secret_value()}",
            }
            params = {
                "format": output_format,
                "query": query,
            }
            if time_range > 0:
                params["time_range"] = time_range
                logger.debug(f"Applying time range filter in async request: {time_range} days")
            if site != "":
                params["site"] = site
                logger.debug(f"Applying site filter in async request: {site}")

            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(f"{INFOQUEST_API_URL}", headers = headers, json=params) as res:
                    if res.status == 200:
                        data = await res.text()
                        return data
                    else:
                        raise Exception(f"Error {res.status}: {res.reason}")
        results_json_str = await fetch()

        # Print partial response for debugging
        if logger.isEnabledFor(logging.DEBUG):
            response_sample = results_json_str[:200] + ("..." if len(results_json_str) > 200 else "")
            logger.debug(
                f"Async search API request completed successfully | "
                f"service=InfoQuest | "
                f"status=success | "
                f"response_sample={response_sample}"
            )
        return json.loads(results_json_str)["search_result"]

    def clean_results_with_images(
        self, raw_results: List[Dict[str, Dict[str, Dict[str,Any]]]]
    ) -> List[Dict]:
        """Clean results from InfoQuest Search API."""
        logger.debug("Processing search results")

        seen_urls = set()
        clean_results = []
        counts = {"pages": 0, "news": 0, "images": 0}

        for content_list in raw_results:
            content = content_list["content"]
            results = content["results"]
            """Clean results from InfoQuest Search API."""

            if results.get("organic"):
                organic_results = results["organic"]
                for result in organic_results:
                    clean_result = {
                        "type": "page",
                        "title": result["title"],
                        "url": result["url"],
                        "desc": result["desc"],
                    }
                    url = clean_result["url"]
                    if isinstance(url, str) and url and url not in seen_urls:
                        seen_urls.add(url)
                        clean_results.append(clean_result)
                        counts["pages"] += 1

            if results.get("top_stories"):
                news = results["top_stories"]
                for obj in news["items"]:
                    clean_result = {
                        "type": "news",
                        "time_frame": obj["time_frame"],
                        "title": obj["title"],
                        "url": obj["url"],
                        "source": obj["source"],
                    }
                    url = clean_result["url"]
                    if isinstance(url, str) and url and url not in seen_urls:
                        seen_urls.add(url)
                        clean_results.append(clean_result)
                        counts["news"] += 1

            if results.get("images"):
                images = results["images"]
                for image in images["items"]:
                    clean_result = {
                        "type": "image_url",
                        "image_url": image["url"],
                        "image_description": image["alt"],
                    }
                    url = clean_result["image_url"]
                    if isinstance(url, str) and url and url not in seen_urls:
                        seen_urls.add(url)
                        clean_results.append(clean_result)
                        counts["images"] += 1

        logger.debug(
            f"Results processing completed | "
            f"total_results={len(clean_results)} | "
            f"pages={counts['pages']} | "
            f"news_items={counts['news']} | "
            f"images={counts['images']} | "
            f"unique_urls={len(seen_urls)}"
        )

        return clean_results
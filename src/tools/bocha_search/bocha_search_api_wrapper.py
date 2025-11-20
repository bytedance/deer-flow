# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from typing import Dict, List, Optional

import aiohttp
import requests

from src.config import load_yaml_config
from src.tools.search_postprocessor import SearchResultPostProcessor

logger = logging.getLogger(__name__)


def get_search_config() -> Dict:
    """Load SEARCH_ENGINE section from conf.yaml.

    This mirrors the helper used in other search integrations.
    """

    config = load_yaml_config("conf.yaml")
    search_config = config.get("SEARCH_ENGINE", {})
    return search_config


class BochaSearchAPIWrapper:
    """Lightweight wrapper around the Bocha Web Search API.

    The API shape is based on the example provided in project docs/user code.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("BOCHA_API_KEY", "")
        if not self.api_key:
            logger.warning("BOCHA_API_KEY is not set; Bocha search calls will likely fail.")

        # In case a custom internal gateway is used in intranet deployments
        self.base_url = os.getenv("BOCHA_API_BASE_URL", "https://api.bochaai.com")

    # -------------------- raw API --------------------
    def raw_results(
        self,
        query: str,
        max_results: int = 5,
        freshness: str = "noLimit",
        summary: bool = True,
    ) -> Dict:
        """Call Bocha Web Search API and return raw JSON.

        Expected request body (based on user example):
        {
          "query": str,
          "freshness": "oneDay" | "oneWeek" | "oneMonth" | "oneYear" | "noLimit",
          "summary": bool,
          "count": int
        }

        Expected successful response (simplified):
        {
          "code": 200,
          "data": {
            "webPages": {
              "value": [ { ... } ]
            }
          }
        }
        """

        url = f"{self.base_url.rstrip('/')}/v1/web-search"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "freshness": freshness,
            "summary": summary,
            "count": max_results,
        }

        logger.debug("Calling Bocha search: url=%s, freshness=%s, summary=%s, count=%s", url, freshness, summary, max_results)

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            logger.error("Failed to parse Bocha search response as JSON: %s", resp.text[:500])
            raise

        return data

    async def raw_results_async(
        self,
        query: str,
        max_results: int = 5,
        freshness: str = "noLimit",
        summary: bool = True,
    ) -> Dict:
        """Async variant of raw_results using aiohttp.

        Mirrors the Tavily async implementation so LangGraph can execute
        this tool without blocking the event loop.
        """

        url = f"{self.base_url.rstrip('/')}/v1/web-search"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "freshness": freshness,
            "summary": summary,
            "count": max_results,
        }

        async def fetch() -> str:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                ) as res:
                    if res.status == 200:
                        return await res.text()
                    raise Exception(f"Error {res.status}: {res.reason}")

        text = await fetch()
        try:
            data = json.loads(text)
        except ValueError:
            logger.error("Failed to parse Bocha search async response as JSON: %s", text[:500])
            raise

        return data

    # -------------------- cleaning & normalization --------------------
    def _extract_pages(self, raw: Dict) -> List[Dict]:
        """Extract web page items from Bocha raw response.

        We are tolerant to missing keys to avoid hard failures on schema changes.
        """

        if not isinstance(raw, dict):
            logger.warning("Bocha raw_results is not a dict: %r", type(raw))
            return []

        if raw.get("code") != 200:
            # Some Bocha responses may include error details; log and return empty list
            logger.error("Bocha search error response: code=%s, raw=%s", raw.get("code"), json.dumps(raw, ensure_ascii=False)[:500])
            return []

        data = raw.get("data") or {}
        web_pages = data.get("webPages") or {}
        values = web_pages.get("value") or []

        if not isinstance(values, list):
            logger.warning("Bocha webPages.value is not a list: %r", type(values))
            return []

        return values

    def clean_results(self, raw: Dict) -> List[Dict]:
        """Convert Bocha results into DeerFlow's normalized search result format.

        Output items follow the same shape used by Tavily integration and
        consumed by SearchResultPostProcessor:

        {
          "type": "page",
          "title": str,
          "url": str,
          "content": str,
          "score": float,
          ...extra fields (site_name, site_icon, date_last_crawled)
        }
        """

        pages = self._extract_pages(raw)
        normalized: List[Dict] = []

        for p in pages:
            if not isinstance(p, dict):
                continue

            title = p.get("name", "")
            url = p.get("url", "")
            summary = p.get("summary", "") or ""

            # Bocha may or may not expose an explicit relevance score; if missing,
            # fall back to 1.0 so that post-processor can still sort.
            score = p.get("score")
            try:
                score_val = float(score) if score is not None else 1.0
            except (TypeError, ValueError):
                score_val = 1.0

            item: Dict = {
                "type": "page",
                "title": title,
                "url": url,
                "content": summary,
                "score": score_val,
            }

            # Attach extra metadata if present
            if "siteName" in p:
                item["site_name"] = p.get("siteName")
            if "siteIcon" in p:
                item["site_icon"] = p.get("siteIcon")
            if "dateLastCrawled" in p:
                item["date_last_crawled"] = p.get("dateLastCrawled")

            normalized.append(item)

        # Run shared post-processing (dedup, truncation, filtering)
        search_config = get_search_config()
        processor = SearchResultPostProcessor(
            min_score_threshold=search_config.get("min_score_threshold"),
            max_content_length_per_page=search_config.get("max_content_length_per_page"),
        )

        processed = processor.process_results(normalized)
        logger.info(
            "Bocha search result post-processing: %d -> %d", len(normalized), len(processed)
        )
        return processed

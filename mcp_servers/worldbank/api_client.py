"""Async HTTP client for the World Bank Open Data API v2."""

import logging
import os
import sys
import time
from typing import Any

import httpx

# All logging to stderr (stdout reserved for JSON-RPC)
logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, os.environ.get("WORLDBANK_MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("worldbank-mcp")

BASE_URL = "https://api.worldbank.org/v2"
INDICATOR_CACHE_TTL = 3600  # 1 hour


class WorldBankAPIError(Exception):
    """Raised when the World Bank API returns an error."""


class WorldBankClient:
    """Async client for the World Bank Open Data API v2."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._indicator_cache: list[dict[str, Any]] | None = None
        self._indicator_cache_time: float = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Make a GET request to the World Bank API.

        The API returns a JSON array: [pagination_meta, data_array].
        Returns (pagination_meta, data_array).
        """
        request_params = {"format": "json", **(params or {})}
        logger.debug(f"GET {path} params={request_params}")
        resp = await self._http.get(path, params=request_params)
        resp.raise_for_status()
        body = resp.json()

        if isinstance(body, list) and len(body) == 2:
            meta, data = body
            # Check for API-level error messages
            if isinstance(meta, list) and len(meta) > 0 and isinstance(meta[0], dict) and "message" in meta[0]:
                error_messages = [m.get("value", str(m)) for m in meta[0].get("message", meta)]
                raise WorldBankAPIError("; ".join(error_messages))
            return meta, data if data is not None else []

        # Some endpoints return error objects directly
        if isinstance(body, list) and len(body) == 1 and isinstance(body[0], dict) and "message" in body[0]:
            messages = body[0]["message"]
            error_text = "; ".join(m.get("value", str(m)) for m in messages) if isinstance(messages, list) else str(messages)
            raise WorldBankAPIError(error_text)

        raise WorldBankAPIError(f"Unexpected API response format: {type(body)}")

    async def list_countries(
        self,
        region: str | None = None,
        income_level: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, Any]:
        """List countries with optional filters."""
        params: dict[str, Any] = {"per_page": min(per_page, 300), "page": page}
        if region:
            params["region"] = region
        if income_level:
            params["incomeLevel"] = income_level

        meta, data = await self._get("/country", params)
        countries = [
            {
                "id": c["id"],
                "name": c["name"],
                "region": c.get("region", {}).get("value", ""),
                "income_level": c.get("incomeLevel", {}).get("value", ""),
                "capital": c.get("capitalCity", ""),
                "iso2": c.get("iso2Code", ""),
            }
            for c in data
        ]
        return {"pagination": meta, "countries": countries}

    async def _fetch_all_indicators(self) -> list[dict[str, Any]]:
        """Fetch all indicators (cached with TTL)."""
        now = time.time()
        if self._indicator_cache is not None and (now - self._indicator_cache_time) < INDICATOR_CACHE_TTL:
            logger.debug("Using cached indicator list")
            return self._indicator_cache

        logger.info("Fetching full indicator list from World Bank API...")
        all_indicators: list[dict[str, Any]] = []
        page = 1
        per_page = 1000
        while True:
            meta, data = await self._get("/indicator", {"per_page": per_page, "page": page})
            all_indicators.extend(data)
            total_pages = meta.get("pages", 1)
            if page >= total_pages:
                break
            page += 1

        self._indicator_cache = all_indicators
        self._indicator_cache_time = now
        logger.info(f"Cached {len(all_indicators)} indicators")
        return all_indicators

    async def search_indicators(
        self,
        query: str,
        topic: int | None = None,
        per_page: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search indicators by keyword with client-side matching."""
        all_indicators = await self._fetch_all_indicators()

        keywords = query.lower().split()
        matches = []
        for ind in all_indicators:
            name = (ind.get("name") or "").lower()
            source_note = (ind.get("sourceNote") or "").lower()
            indicator_id = (ind.get("id") or "").lower()
            text = f"{name} {source_note} {indicator_id}"

            if all(kw in text for kw in keywords):
                # Apply topic filter if specified
                if topic is not None:
                    topics = ind.get("topics", [])
                    if not any(t.get("id") == str(topic) for t in topics if isinstance(t, dict)):
                        continue
                matches.append(ind)

        total = len(matches)
        start = (page - 1) * per_page
        end = start + per_page
        page_results = matches[start:end]

        indicators = [
            {
                "id": ind["id"],
                "name": ind.get("name", ""),
                "source_note": (ind.get("sourceNote") or "")[:200],
                "source": ind.get("source", {}).get("value", "") if isinstance(ind.get("source"), dict) else "",
                "topics": [t.get("value", "") for t in ind.get("topics", []) if isinstance(t, dict) and t.get("value")],
            }
            for ind in page_results
        ]

        pagination = {
            "page": page,
            "pages": (total + per_page - 1) // per_page if per_page > 0 else 1,
            "per_page": per_page,
            "total": total,
        }
        return {"pagination": pagination, "indicators": indicators}

    async def get_indicator_data(
        self,
        country_codes: str,
        indicator_code: str,
        start_year: int | None = None,
        end_year: int | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Fetch indicator time-series data for specified countries."""
        path = f"/country/{country_codes}/indicator/{indicator_code}"
        params: dict[str, Any] = {"per_page": min(per_page, 1000), "page": page}
        if start_year is not None and end_year is not None:
            params["date"] = f"{start_year}:{end_year}"
        elif start_year is not None:
            params["date"] = f"{start_year}:{start_year}"

        meta, data = await self._get(path, params)

        # Filter out entries with null values
        records = [
            {
                "country": d.get("country", {}).get("value", ""),
                "country_code": d.get("countryiso3code", ""),
                "date": d.get("date", ""),
                "value": d["value"],
                "indicator": d.get("indicator", {}).get("value", ""),
            }
            for d in data
            if d.get("value") is not None
        ]

        return {"pagination": meta, "data": records}

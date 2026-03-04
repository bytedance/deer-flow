"""Async HTTP client for the U.S. Treasury Fiscal Data API."""

import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# All logging to stderr (stdout reserved for JSON-RPC)
logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, os.environ.get("FISCALDATA_MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("fiscaldata-mcp")

BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
DEFAULT_CACHE_TTL = 300  # 5 minutes

# Valid DTS table names
DTS_TABLES = frozenset({
    "operating_cash_balance",
    "deposits_withdrawals_operating_cash",
    "public_debt_transactions",
    "adjustment_public_debt_transactions_cash_basis",
    "inter_agency_tax_transfers",
    "income_tax_refunds_issued",
    "federal_tax_deposits",
    "short_term_cash_investments",
    "gulf_coast_restoration_trust_fund",
})


class FiscalDataAPIError(Exception):
    """Raised when the Treasury Fiscal Data API returns an error."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient failures worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


@dataclass
class _CacheEntry:
    """Cached API response with timestamp."""

    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class FiscalDataClient:
    """Async client for the U.S. Treasury Fiscal Data API."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._cache: dict[str, _CacheEntry] = {}

    async def close(self) -> None:
        await self._http.aclose()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def _get_raw(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        """Make a GET request with retry logic."""
        logger.debug(f"GET {endpoint} params={params}")
        resp = await self._http.get(endpoint, params=params)
        resp.raise_for_status()
        return resp

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        cache_key: str | None = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Make a GET request with caching and stale-cache fallback.

        The API returns JSON: {"data": [...], "meta": {...}, "links": {...}}.
        Returns (meta, data).
        """
        request_params = {**(params or {})}

        # Check cache
        if cache_key and cache_key in self._cache:
            entry = self._cache[cache_key]
            if (time.time() - entry.timestamp) < cache_ttl:
                logger.debug(f"Cache hit for {cache_key}")
                return entry.data["meta"], entry.data["data"]

        try:
            resp = await self._get_raw(endpoint, request_params)
            body = resp.json()
        except Exception as exc:
            # Stale cache fallback
            if cache_key and cache_key in self._cache:
                logger.warning(f"API request failed, using stale cache for {cache_key}: {exc}")
                stale = self._cache[cache_key].data
                stale_meta = {**stale["meta"], "warning": "stale data — API request failed"}
                return stale_meta, stale["data"]
            raise

        if not isinstance(body, dict) or "data" not in body:
            raise FiscalDataAPIError(f"Unexpected API response format: {type(body)}")

        data = body.get("data", [])
        meta = body.get("meta", {})
        links = body.get("links", {})
        meta["links"] = links

        # Update cache
        if cache_key:
            self._cache[cache_key] = _CacheEntry(data={"meta": meta, "data": data}, timestamp=time.time())

        return meta, data

    def _build_filter(self, **kwargs: str | None) -> str | None:
        """Build a filter string from keyword arguments.

        Each kwarg maps field_name:operator to value. Only non-None values are included.
        Example: record_date:gte="2024-01-01" -> "record_date:gte:2024-01-01"
        """
        parts = []
        for key, value in kwargs.items():
            if value is not None:
                parts.append(f"{key}:{value}")
        return ",".join(parts) if parts else None

    def _build_params(
        self,
        filter_str: str | None = None,
        fields: str | None = None,
        sort: str | None = None,
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Build common query parameters."""
        params: dict[str, Any] = {
            "page[number]": page,
            "page[size]": min(max(1, page_size), 10000),
        }
        if filter_str:
            params["filter"] = filter_str
        if fields:
            params["fields"] = fields
        if sort:
            params["sort"] = sort
        return params

    def _date_filter(self, start_date: str | None, end_date: str | None) -> dict[str, str | None]:
        """Build date range filter parts."""
        parts: dict[str, str | None] = {}
        if start_date:
            parts["record_date:gte"] = start_date
        if end_date:
            parts["record_date:lte"] = end_date
        return parts

    async def get_debt_to_penny(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        fields: str | None = None,
        sort: str = "-record_date",
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Query the Debt to the Penny dataset."""
        endpoint = "/v2/accounting/od/debt_to_penny"
        date_parts = self._date_filter(start_date, end_date)
        filter_str = self._build_filter(**date_parts)
        params = self._build_params(filter_str=filter_str, fields=fields, sort=sort, page_size=page_size, page=page)
        cache_key = f"debt_to_penny:{start_date}:{end_date}:{fields}:{sort}:{page_size}:{page}"
        meta, data = await self._get(endpoint, params, cache_key=cache_key)
        return {"meta": meta, "data": data}

    async def get_interest_rates(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        security_type: str | None = None,
        fields: str | None = None,
        sort: str = "-record_date",
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Query average interest rates on Treasury securities."""
        endpoint = "/v2/accounting/od/avg_interest_rates"
        date_parts = self._date_filter(start_date, end_date)
        if security_type:
            date_parts["security_desc:eq"] = security_type
        filter_str = self._build_filter(**date_parts)
        params = self._build_params(filter_str=filter_str, fields=fields, sort=sort, page_size=page_size, page=page)
        cache_key = f"interest_rates:{start_date}:{end_date}:{security_type}:{fields}:{sort}:{page_size}:{page}"
        meta, data = await self._get(endpoint, params, cache_key=cache_key)
        return {"meta": meta, "data": data}

    async def get_exchange_rates(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        country: str | None = None,
        currency: str | None = None,
        fields: str | None = None,
        sort: str = "-record_date",
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Query Treasury reporting rates of exchange."""
        endpoint = "/v1/accounting/od/rates_of_exchange"
        date_parts = self._date_filter(start_date, end_date)
        if country:
            date_parts["country:eq"] = country
        if currency:
            date_parts["currency:eq"] = currency
        filter_str = self._build_filter(**date_parts)
        params = self._build_params(filter_str=filter_str, fields=fields, sort=sort, page_size=page_size, page=page)
        cache_key = f"exchange_rates:{start_date}:{end_date}:{country}:{currency}:{fields}:{sort}:{page_size}:{page}"
        meta, data = await self._get(endpoint, params, cache_key=cache_key)
        return {"meta": meta, "data": data}

    async def get_interest_expense(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        fields: str | None = None,
        sort: str = "-record_date",
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Query interest expense on the public debt."""
        endpoint = "/v2/accounting/od/interest_expense"
        date_parts = self._date_filter(start_date, end_date)
        filter_str = self._build_filter(**date_parts)
        params = self._build_params(filter_str=filter_str, fields=fields, sort=sort, page_size=page_size, page=page)
        cache_key = f"interest_expense:{start_date}:{end_date}:{fields}:{sort}:{page_size}:{page}"
        meta, data = await self._get(endpoint, params, cache_key=cache_key)
        return {"meta": meta, "data": data}

    async def get_treasury_statement(
        self,
        table: str = "operating_cash_balance",
        start_date: str | None = None,
        end_date: str | None = None,
        fields: str | None = None,
        sort: str = "-record_date",
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Query the Daily Treasury Statement (DTS)."""
        if table not in DTS_TABLES:
            raise FiscalDataAPIError(f"Invalid DTS table: {table!r}. Valid tables: {', '.join(sorted(DTS_TABLES))}")
        endpoint = f"/v1/accounting/dts/{table}"
        date_parts = self._date_filter(start_date, end_date)
        filter_str = self._build_filter(**date_parts)
        params = self._build_params(filter_str=filter_str, fields=fields, sort=sort, page_size=page_size, page=page)
        cache_key = f"dts:{table}:{start_date}:{end_date}:{fields}:{sort}:{page_size}:{page}"
        meta, data = await self._get(endpoint, params, cache_key=cache_key)
        return {"meta": meta, "data": data}

    @staticmethod
    def validate_endpoint(endpoint: str) -> str:
        """Validate and sanitize a user-provided endpoint path.

        Must start with v1/ or v2/ and contain only safe characters.
        """
        if not re.match(r"^v[12]/[a-zA-Z0-9/_]+$", endpoint):
            raise FiscalDataAPIError(
                f"Invalid endpoint path: {endpoint!r}. "
                "Must start with 'v1/' or 'v2/' and contain only alphanumeric, '/', '_' characters."
            )
        return f"/{endpoint}"

    async def query_dataset(
        self,
        endpoint: str,
        filter_expr: str | None = None,
        fields: str | None = None,
        sort: str | None = None,
        page_size: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Generic query for any Fiscal Data API endpoint."""
        safe_endpoint = self.validate_endpoint(endpoint)
        params = self._build_params(filter_str=filter_expr, fields=fields, sort=sort, page_size=page_size, page=page)
        meta, data = await self._get(safe_endpoint, params)
        return {"meta": meta, "data": data}

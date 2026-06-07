"""Async HTTP client for tikhub.io Twitter Web API.

Endpoint paths follow the pattern observed at https://api.tikhub.io/#/Twitter-Web-API:
    GET /api/v1/twitter/web/fetch_tweet_detail?tweet_id=...
    GET /api/v1/twitter/web/fetch_search_timeline?keyword=...&search_type=...&cursor=...
    GET /api/v1/twitter/web/fetch_user_post_tweet?screen_name=...&cursor=...
    GET /api/v1/twitter/web/fetch_user_profile?screen_name=...

Authentication uses a Bearer token in the Authorization header.
"""

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("tg_crawler")


class TikHubAuthError(Exception):
    """Raised when the tikhub API rejects the API key (401/403)."""


class TikHubAPIError(Exception):
    """Raised on non-recoverable API errors."""


class TwitterClient:
    """Thin async wrapper around tikhub.io Twitter Web API endpoints."""

    DEFAULT_BASE_URL = "https://api.tikhub.io"
    DEFAULT_TIMEOUT = 30.0

    # Endpoint paths — tweak here if upstream API renames anything.
    PATH_SEARCH_TIMELINE = "/api/v1/twitter/web/fetch_search_timeline"
    PATH_USER_POST_TWEET = "/api/v1/twitter/web/fetch_user_post_tweet"
    PATH_USER_PROFILE = "/api/v1/twitter/web/fetch_user_profile"
    PATH_TWEET_DETAIL = "/api/v1/twitter/web/fetch_tweet_detail"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
    ):
        if not api_key:
            raise ValueError("tikhub api_key is required")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def __aenter__(self) -> "TwitterClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: dict) -> dict:
        """Issue a GET with retry on transient failures."""
        if self._client is None:
            raise RuntimeError("TwitterClient must be used as async context manager")

        # Drop None values so they don't show up as 'None' in the query string.
        clean = {k: v for k, v in params.items() if v is not None}

        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._client.get(path, params=clean)
                if resp.status_code in (401, 403):
                    raise TikHubAuthError(
                        f"tikhub auth failed ({resp.status_code}): {resp.text[:200]}"
                    )
                if resp.status_code == 429:
                    # Rate limited — back off and retry
                    delay = min(2 ** attempt, 30)
                    logger.warning(
                        f"tikhub 429 rate-limited on {path}; sleeping {delay}s "
                        f"(attempt {attempt}/{self._max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except TikHubAuthError:
                raise
            except (httpx.HTTPError, ValueError) as e:
                last_exc = e
                logger.warning(
                    f"tikhub request failed on {path} (attempt "
                    f"{attempt}/{self._max_retries}): {e}"
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2 ** attempt, 30))
        raise TikHubAPIError(
            f"tikhub GET {path} failed after {self._max_retries} attempts: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    async def search_timeline(
        self,
        keyword: str,
        search_type: str = "Latest",
        cursor: Optional[str] = None,
    ) -> dict:
        """Search tweets by keyword.

        Args:
            keyword: search query (supports operators like ``lang:zh``).
            search_type: ``Latest`` | ``Top`` | ``People`` | ``Photos`` | ``Videos``.
            cursor: pagination cursor returned from a previous response.
        """
        params: dict[str, Any] = {"keyword": keyword, "search_type": search_type}
        if cursor:
            params["cursor"] = cursor
        return await self._get(self.PATH_SEARCH_TIMELINE, params)

    async def user_post_tweet(
        self,
        screen_name: str,
        cursor: Optional[str] = None,
    ) -> dict:
        """Fetch tweets posted by a specific user (by @screen_name)."""
        params: dict[str, Any] = {"screen_name": screen_name}
        if cursor:
            params["cursor"] = cursor
        return await self._get(self.PATH_USER_POST_TWEET, params)

    async def user_profile(self, screen_name: str) -> dict:
        """Fetch a user's profile by @screen_name."""
        return await self._get(self.PATH_USER_PROFILE, {"screen_name": screen_name})

    async def tweet_detail(self, tweet_id: str) -> dict:
        """Fetch a single tweet by its ID."""
        return await self._get(self.PATH_TWEET_DETAIL, {"tweet_id": tweet_id})

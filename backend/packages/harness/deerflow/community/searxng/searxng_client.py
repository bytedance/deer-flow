import logging
from typing import Any

import httpx

from deerflow.community.search_time_range import SearchTimeRange

logger = logging.getLogger(__name__)


class SearxngResponseError(ValueError):
    """Raised when a SearXNG instance answers with a malformed success payload.

    The search API answers HTTP 200 with ``results`` as its only contract; an
    instance behind a reverse proxy or captive portal instead answers an HTML or
    plain-text error page with the same status. Such a payload is not an empty
    search, so the caller reports a format error rather than "No results found"
    -- the containment rule the sibling providers already follow.
    """


class SearxngClient:
    """Client for SearXNG meta search engine API."""

    # SearXNG's search API has no ``limit`` parameter: ``/search`` answers with
    # one page of results (the instance's ``results_per_page``, 10 by default)
    # and ignores a limit it is handed. A ``max_results`` larger than a page
    # therefore has to be collected by walking ``pageno``. Cap the walk so an
    # unexpectedly large ``max_results`` cannot fan out into unbounded requests.
    _MAX_PAGES = 5

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        categories: list[str] | None = None,
        time_range: SearchTimeRange | None = None,
    ) -> list[dict[str, Any]]:
        """Search the web using SearXNG.

        Args:
            query: The search query.
            max_results: Maximum number of results to return. SearXNG returns
                one page per request, so a value larger than a page is collected
                across ``pageno`` pages. A falsy value means "no cap".
            categories: Search categories to use.
            time_range: Optional relative publication/update window.

        Returns:
            List of search result dictionaries.
        """
        limit = max_results if isinstance(max_results, int) and max_results > 0 else None

        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for pageno in range(1, self._MAX_PAGES + 1):
            rows = await self._search_page(query, pageno=pageno, categories=categories, time_range=time_range)
            if not rows:
                break

            added = 0
            for row in rows:
                key = str(row.get("url") or row.get("title") or "")
                if key and key in seen:
                    continue
                seen.add(key)
                collected.append(row)
                added += 1
                if limit is not None and len(collected) >= limit:
                    return collected

            # A page that adds nothing new means the instance is repeating
            # itself or the query is exhausted -- ask for no more.
            if added == 0:
                break

        return collected

    @staticmethod
    def _response_rows(data: object) -> list[dict[str, Any]]:
        """Return the object rows of one page, or raise when the payload is malformed.

        A missing or null ``results`` is an empty search. A payload that is not
        an object, a ``results`` container that is not a list, and a non-empty
        list holding no object entries are all malformed: an instance behind a
        reverse proxy or captive portal answers an HTML or plain-text error page
        with HTTP 200, and reporting "No results found" for it would tell the
        agent the query legitimately matched nothing. Non-object entries in an
        otherwise valid list are skipped in order so the valid rows survive, and
        each skip is logged with the entry index: this is the provider where
        drift is most expected (a self-hosted instance serves whatever sits
        behind its reverse proxy), and with ``_MAX_PAGES`` requests per search a
        drifting instance would otherwise shed rows with no trace at all.
        """
        if not isinstance(data, dict):
            logger.error("SearXNG returned an unexpected payload type: %s", type(data).__name__)
            raise SearxngResponseError("SearXNG returned an unexpected response format")
        results = data.get("results")
        if results is None:
            return []
        if not isinstance(results, list):
            logger.error("SearXNG returned an unexpected 'results' payload type: %s", type(results).__name__)
            raise SearxngResponseError("SearXNG returned an unexpected response format")
        usable: list[dict[str, Any]] = []
        for index, row in enumerate(results):
            if not isinstance(row, dict):
                logger.warning("Skipping malformed SearXNG result entry at results[%d]", index)
                continue
            usable.append(row)
        if results and not usable:
            logger.error("SearXNG returned 'results' with no usable result objects")
            raise SearxngResponseError("SearXNG returned an unexpected response format")
        return usable

    async def _search_page(
        self,
        query: str,
        pageno: int,
        categories: list[str] | None,
        time_range: SearchTimeRange | None,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of results.

        ``limit`` is deliberately not sent: it is not part of the SearXNG search
        API, so an instance ignores it and the caller cannot tell a truncated
        response from a complete one.
        """
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": "auto",
            "pageno": pageno,
        }
        if categories:
            params["categories"] = ",".join(categories)
        if time_range is not None:
            params["time_range"] = time_range

        logger.debug(f"Searching SearXNG at {self.base_url} with query: {query} (page {pageno})")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; DeerFlow/1.0)",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError as e:
                    logger.error("SearXNG returned a response body that is not JSON")
                    raise SearxngResponseError("SearXNG returned an unexpected response format") from e
                return self._response_rows(data)
        except httpx.HTTPStatusError as e:
            logger.error(f"SearXNG search returned error status: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"SearXNG search request failed: {e}")
            raise
        except SearxngResponseError:
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during SearXNG search: {e}")
            raise

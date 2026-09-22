import logging
from typing import Any

import httpx

from deerflow.community.search_time_range import SearchTimeRange

logger = logging.getLogger(__name__)


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
                data = resp.json()
                return data.get("results") or []
        except httpx.HTTPStatusError as e:
            logger.error(f"SearXNG search returned error status: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"SearXNG search request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during SearXNG search: {e}")
            raise

import logging
from typing import Any

import httpx

from deerflow.community.search_time_range import SearchTimeRange

logger = logging.getLogger(__name__)

# SearXNG serves one page per /search request, sized by the instance's
# results_per_page (10 by default). Collecting more than one page worth of
# results therefore requires walking pageno. Cap the walk so an unusually
# large max_results cannot fan out into unbounded requests.
_MAX_PAGES = 5


class SearxngClient:
    """Client for SearXNG meta search engine API."""

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

        Walks result pages until max_results is collected, a page comes back
        empty, or a page adds nothing new. SearXNG has no limit parameter, so
        the per-page count is whatever the instance is configured with.

        Args:
            query: The search query.
            max_results: Maximum number of results to return.
            categories: Search categories to use.
            time_range: Optional relative publication/update window.

        Returns:
            List of search result dictionaries.
        """
        # Without a cap there is no target to paginate towards, so keep the
        # single-request shape instead of walking up to _MAX_PAGES pages.
        pages_to_fetch = _MAX_PAGES if max_results else 1

        collected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        async with httpx.AsyncClient(timeout=30) as client:
            for pageno in range(1, pages_to_fetch + 1):
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

                logger.debug(f"Searching SearXNG at {self.base_url} (page {pageno}) with query: {query}")
                try:
                    resp = await client.get(
                        f"{self.base_url}/search",
                        params=params,
                        headers={
                            "User-Agent": "Mozilla/5.0 (compatible; DeerFlow/1.0)",
                            "Accept": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    page = resp.json().get("results", [])
                except httpx.HTTPStatusError as e:
                    logger.error(f"SearXNG search returned error status: {e}")
                    raise
                except httpx.RequestError as e:
                    logger.error(f"SearXNG search request failed: {e}")
                    raise
                except Exception as e:
                    logger.error(f"An unexpected error occurred during SearXNG search: {e}")
                    raise

                if not page:
                    break

                fresh = 0
                for result in page:
                    key = (str(result.get("url", "")), str(result.get("title", "")))
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(result)
                    fresh += 1
                    if max_results and len(collected) >= max_results:
                        break

                if max_results and len(collected) >= max_results:
                    break
                if fresh == 0:
                    break

        return collected[:max_results] if max_results else collected

"""Provider adapters for multi-provider search system."""

import json
import logging

from deerflow.community.infoquest.tools import InfoQuestClient
from deerflow.community.tavily.tools import TavilyClient

from .types import SearchResult

logger = logging.getLogger(__name__)

try:
    from langchain_community.utilities import SearxSearchWrapper
except ImportError:
    SearxSearchWrapper = None  # type: ignore[assignment,misc]


class SearXNGAdapter:
    """Adapter for SearXNG search using langchain_community.utilities.SearxSearchWrapper."""

    def __init__(self, searx_host: str, engines: list[str] = None, categories: list[str] = None, language: str = "en", unsecure: bool = False):
        """
        Initialize SearXNG adapter.

        Args:
            searx_host: URL of SearXNG instance (e.g., "http://localhost:8888")
            engines: List of search engines to use (empty = instance defaults)
            categories: List of categories to search (empty = instance defaults)
            language: Search language (default: "en")
            unsecure: Whether to disable SSL verification (default: False)
        """
        try:
            if SearxSearchWrapper is None:
                raise ImportError("langchain-community not installed. Run: uv add langchain-community")

            self.client = SearxSearchWrapper(
                searx_host=searx_host,
                engines=engines or [],
                categories=categories or [],
                unsecure=unsecure,
            )
            self.language = language
            logger.info(f"✅ SearXNG adapter initialized | host={searx_host}")
        except ImportError:
            logger.error("langchain-community not installed. Run: uv add langchain-community")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize SearXNG adapter: {e}")
            raise

    def get_name(self) -> str:
        """Return provider name."""
        return "searxng"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """
        Search using SearXNG.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        try:
            # Use .results() method as requested
            raw_results = self.client.results(query, num_results=max_results)

            # Normalize SearXNG format: "link" → "url"
            results = []
            for r in raw_results:
                result = SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),  # SearXNG uses "link" not "url"
                    snippet=r.get("snippet", ""),
                    type="page",
                )
                results.append(result)

            logger.debug(f"SearXNG search completed | query={query} | results={len(results)}")
            return results

        except Exception as e:
            logger.error(f"SearXNG search failed: {e}")
            raise

    def fetch(self, url: str) -> str:
        """
        SearXNG does not support web fetch.

        Args:
            url: URL to fetch

        Raises:
            NotImplementedError: Always raised as SearXNG doesn't support fetching
        """
        raise NotImplementedError("SearXNG does not support web fetch. Use InfoQuest or Tavily for fetching content.")


class InfoQuestAdapter:
    """Adapter for InfoQuest search."""

    def __init__(self, search_time_range: int = -1):
        """
        Initialize InfoQuest adapter.

        Args:
            search_time_range: Time range in days for search results (-1 = disabled)
        """
        try:
            self.client = InfoQuestClient(search_time_range=search_time_range)
            logger.info("✅ InfoQuest adapter initialized")
        except Exception as e:
            logger.error(f"Failed to initialize InfoQuest adapter: {e}")
            raise

    def get_name(self) -> str:
        """Return provider name."""
        return "infoquest"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """
        Search using InfoQuest.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        try:
            result_json = self.client.web_search(query)
            results_list = json.loads(result_json)

            # Limit results if needed
            if len(results_list) > max_results:
                results_list = results_list[:max_results]

            # Convert to SearchResult objects
            results = []
            for r in results_list:
                result = SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("snippet", r.get("desc", "")),
                    type=r.get("type", "page"),
                )
                results.append(result)

            logger.debug(f"InfoQuest search completed | query={query} | results={len(results)}")
            return results

        except Exception as e:
            logger.error(f"InfoQuest search failed: {e}")
            raise

    def fetch(self, url: str) -> str:
        """
        Fetch content using InfoQuest.

        Args:
            url: URL to fetch

        Returns:
            Markdown content from the URL
        """
        try:
            return self.client.fetch(url)
        except Exception as e:
            logger.error(f"InfoQuest fetch failed: {e}")
            raise


class TavilyAdapter:
    """Adapter for Tavily search."""

    def __init__(self, api_key: str = None):
        """
        Initialize Tavily adapter.

        Args:
            api_key: Tavily API key (optional, reads from env if not provided)
        """
        try:
            self.client = TavilyClient(api_key=api_key)
            logger.info("✅ Tavily adapter initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Tavily adapter: {e}")
            raise

    def get_name(self) -> str:
        """Return provider name."""
        return "tavily"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """
        Search using Tavily.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        try:
            response = self.client.search(query, max_results=max_results)

            # Normalize Tavily format: "content" → "snippet"
            results = []
            if isinstance(response, dict) and "results" in response:
                for item in response["results"]:
                    result = SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),  # Tavily uses "content"
                        type="page",
                    )
                    results.append(result)

            logger.debug(f"Tavily search completed | query={query} | results={len(results)}")
            return results

        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            raise

    def fetch(self, url: str) -> str:
        """
        Fetch content using Tavily.

        Args:
            url: URL to fetch

        Returns:
            Extracted text content from the URL
        """
        try:
            response = self.client.extract([url])
            if "failed_results" in response and len(response["failed_results"]) > 0:
                raise Exception(response["failed_results"][0]["error"])
            elif "results" in response and len(response["results"]) > 0:
                result = response["results"][0]
                return f"# {result['title']}\n\n{result['raw_content'][:4096]}"
            else:
                raise Exception("No results found")
        except Exception as e:
            logger.error(f"Tavily fetch failed: {e}")
            raise

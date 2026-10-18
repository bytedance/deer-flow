"""Util that calls InfoQuest Search And Fetch API.

In order to set this up, follow instructions at:
https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest
"""

import json
import logging
import os
from typing import Any

import httpx

from deerflow.community.url_safety import safe_public_result_url as _safe_public_url

logger = logging.getLogger(__name__)

# httpx defaults to a 5s timeout. This bounds local connect/read inactivity;
# fetch_timeout and fetch_navigation_timeout configure the remote crawl only.
_REQUEST_TIMEOUT_SECONDS = 30


class InfoQuestResponseError(ValueError):
    """Raised when InfoQuest answers HTTP 200 with a payload that is not a result page.

    Search answers HTTP 200 with a ``search_result`` envelope as its only
    contract. An error document delivered with the same status is not an empty
    search, so the caller reports a format error rather than an empty result --
    the containment rule the sibling bundled providers already follow.
    """


class InfoQuestClient:
    """Client for interacting with the InfoQuest web search and fetch API."""

    def __init__(self, fetch_time: int = -1, fetch_timeout: int = -1, fetch_navigation_timeout: int = -1, search_time_range: int = -1, image_search_time_range: int = -1, image_size: str = "i"):
        logger.info("\n============================================\n🚀 BytePlus InfoQuest Client Initialization 🚀\n============================================")

        self.fetch_time = fetch_time
        self.fetch_timeout = fetch_timeout
        self.fetch_navigation_timeout = fetch_navigation_timeout
        self.search_time_range = search_time_range
        self.image_search_time_range = image_search_time_range
        self.image_size = image_size
        self.api_key_set = bool(os.getenv("INFOQUEST_API_KEY"))
        if logger.isEnabledFor(logging.DEBUG):
            config_details = (
                f"\n📋 Configuration Details:\n"
                f"├── Fetch time: {fetch_time} {'(Default: No fetch time)' if fetch_time == -1 else '(Custom)'}\n"
                f"├── Fetch Timeout: {fetch_timeout} {'(Default: No fetch timeout)' if fetch_timeout == -1 else '(Custom)'}\n"
                f"├── Navigation Timeout: {fetch_navigation_timeout} {'(Default: No Navigation Timeout)' if fetch_navigation_timeout == -1 else '(Custom)'}\n"
                f"├── Search Time Range: {search_time_range} {'(Default: No Search Time Range)' if search_time_range == -1 else '(Custom)'}\n"
                f"├── Image Search Time Range: {image_search_time_range} {'(Default: No Image Search Time Range)' if image_search_time_range == -1 else '(Custom)'}\n"
                f"├── Image Size: {image_size} {'(Default: Medium)' if image_size == 'm' else '(Custom)'}\n"
                f"└── API Key: {'✅ Configured' if self.api_key_set else '❌ Not set'}"
            )

            logger.debug(config_details)
            logger.debug("\n" + "*" * 70 + "\n")

    async def fetch(self, url: str, return_format: str = "html") -> str:
        if logger.isEnabledFor(logging.DEBUG):
            url_truncated = url[:50] + "..." if len(url) > 50 else url
            logger.debug(
                f"InfoQuest - Fetch API request initiated | "
                f"operation=crawl url | "
                f"url_truncated={url_truncated} | "
                f"has_timeout_filter={self.fetch_timeout > 0} | timeout_filter={self.fetch_timeout} | "
                f"has_fetch_time_filter={self.fetch_time > 0} | fetch_time_filter={self.fetch_time} | "
                f"has_navigation_timeout_filter={self.fetch_navigation_timeout > 0} | navi_timeout_filter={self.fetch_navigation_timeout} | "
                f"request_type=async"
            )

        # Prepare headers
        headers = self._prepare_headers()

        # Prepare request data
        data = self._prepare_crawl_request_data(url, return_format)

        logger.debug("Sending crawl request to InfoQuest API")
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.post("https://reader.infoquest.bytepluses.com", headers=headers, json=data, timeout=_REQUEST_TIMEOUT_SECONDS)

            # Check if status code is not 200
            if response.status_code != 200:
                error_message = f"fetch API returned status {response.status_code}: {response.text}"
                logger.debug("InfoQuest Crawler fetch API return status %d: %s for URL: %s", response.status_code, response.text, url)
                return f"Error: {error_message}"

            # Check for empty response
            if not response.text or not response.text.strip():
                error_message = "no result found"
                logger.debug("InfoQuest Crawler returned empty response for URL: %s", url)
                return f"Error: {error_message}"

            # Try to parse response as JSON and extract reader_result
            try:
                response_data = json.loads(response.text)
                # Extract reader_result if it exists
                if "reader_result" in response_data:
                    logger.debug("Successfully extracted reader_result from JSON response")
                    return response_data["reader_result"]
                elif "content" in response_data:
                    # Fallback to content field if reader_result is not available
                    logger.debug("reader_result missing in JSON response, falling back to content field: %s", response_data["content"])
                    return response_data["content"]
                else:
                    # If neither field exists, return the original response
                    logger.warning("Neither reader_result nor content field found in JSON response")
            except json.JSONDecodeError:
                # If response is not JSON, return the original text
                logger.debug("Response is not in JSON format, returning as-is")
                return response.text

            # Print partial response for debugging
            if logger.isEnabledFor(logging.DEBUG):
                response_sample = response.text[:200] + ("..." if len(response.text) > 200 else "")
                logger.debug("Successfully received response, content length: %d bytes, first 200 chars: %s", len(response.text), response_sample)
            return response.text
        except Exception as e:
            error_message = f"fetch API failed: {str(e)}"
            logger.error(error_message)
            return f"Error: {error_message}"

    @staticmethod
    def _prepare_headers() -> dict[str, str]:
        """Prepare request headers."""
        headers = {
            "Content-Type": "application/json",
        }

        # Add API key if available
        if os.getenv("INFOQUEST_API_KEY"):
            headers["Authorization"] = f"Bearer {os.getenv('INFOQUEST_API_KEY')}"
            logger.debug("API key added to request headers")
        else:
            logger.warning("InfoQuest API key is not set. Provide your own key for authentication.")

        return headers

    def _prepare_crawl_request_data(self, url: str, return_format: str) -> dict[str, Any]:
        """Prepare request data with formatted parameters."""
        # Normalize return_format
        if return_format and return_format.lower() == "html":
            normalized_format = "HTML"
        else:
            normalized_format = return_format

        data = {"url": url, "format": normalized_format}

        # Add timeout parameters if set to positive values
        timeout_params = {}
        if self.fetch_time > 0:
            timeout_params["fetch_time"] = self.fetch_time
        if self.fetch_timeout > 0:
            timeout_params["timeout"] = self.fetch_timeout
        if self.fetch_navigation_timeout > 0:
            timeout_params["navi_timeout"] = self.fetch_navigation_timeout

        # Log applied timeout parameters
        if timeout_params:
            logger.debug("Applying timeout parameters: %s", timeout_params)
            data.update(timeout_params)

        return data

    async def web_search_raw_results(
        self,
        query: str,
        site: str,
        output_format: str = "JSON",
    ) -> dict:
        """Get results from the InfoQuest Web-Search API asynchronously."""
        headers = self._prepare_headers()

        params = {"format": output_format, "query": query}
        if self.search_time_range > 0:
            params["time_range"] = self.search_time_range

        if site != "":
            params["site"] = site

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post("https://search.infoquest.bytepluses.com", headers=headers, json=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()

        # Print partial response for debugging
        response_json = response.json()
        if logger.isEnabledFor(logging.DEBUG):
            response_sample = json.dumps(response_json)[:200] + ("..." if len(json.dumps(response_json)) > 200 else "")
            logger.debug(f"Search API request completed successfully | service=InfoQuest | status=success | response_sample={response_sample}")

        return response_json

    @staticmethod
    def _envelope_entries(raw_results: object) -> list[dict]:
        """Return the ``content``/``results`` envelopes of a search payload.

        Search answers HTTP 200 with a ``search_result`` envelope as its only
        contract. A payload that is not a list, or whose entries are not objects
        carrying object ``content.results`` mappings, is a format error: indexing
        it directly raised ``TypeError``/``KeyError`` and the tool reported that
        raw Python error text to the agent instead of the provider's format
        error. Entries that do not fit the envelope are skipped in order so the
        usable pages of an otherwise valid payload survive.
        """
        if not isinstance(raw_results, list):
            logger.error("InfoQuest returned an unexpected search payload type: %s", type(raw_results).__name__)
            raise InfoQuestResponseError("InfoQuest returned an unexpected response format")
        entries: list[dict] = []
        for index, entry in enumerate(raw_results):
            if not isinstance(entry, dict):
                logger.warning("Skipping malformed InfoQuest result entry at index %d", index)
                continue
            content = entry.get("content")
            results = content.get("results") if isinstance(content, dict) else None
            if not isinstance(results, dict):
                logger.warning("Skipping InfoQuest result entry without a usable content.results mapping at index %d", index)
                continue
            entries.append(results)
        if raw_results and not entries:
            logger.error("InfoQuest returned a search payload with no usable result envelopes")
            raise InfoQuestResponseError("InfoQuest returned an unexpected response format")
        return entries

    @staticmethod
    def _rows(value: object, container: str) -> list[dict]:
        """Return the object rows of one vertical, or [] when the key is absent.

        A missing or null container is an empty search. A container that is not
        a list, or a non-empty list holding no object entries, is malformed: the
        caller reports the provider's format error rather than an empty result,
        which would tell the agent the query legitimately matched nothing.
        Non-object entries are skipped in order so the valid rows survive, and
        each skip is logged with the container name and the entry index --
        ``_envelope_entries`` reports its skips the same way, and a provider-side
        drift would otherwise shed entries with no trace at all.
        """
        if value is None:
            return []
        if not isinstance(value, list):
            logger.error("InfoQuest returned an unexpected result container type: %s", type(value).__name__)
            raise InfoQuestResponseError("InfoQuest returned an unexpected response format")
        rows: list[dict] = []
        for index, row in enumerate(value):
            if not isinstance(row, dict):
                logger.warning("Skipping malformed InfoQuest result entry at %s[%d]", container, index)
                continue
            rows.append(row)
        if value and not rows:
            logger.error("InfoQuest returned a result container with no usable entries")
            raise InfoQuestResponseError("InfoQuest returned an unexpected response format")
        return rows

    @classmethod
    def clean_results(cls, raw_results: list[dict[str, dict[str, dict[str, Any]]]]) -> list[dict]:
        """Clean results from InfoQuest Web-Search API."""
        logger.debug("Processing web-search results")

        seen_urls = set()
        clean_results = []
        counts = {"pages": 0, "news": 0}

        for results in cls._envelope_entries(raw_results):
            organic_results = cls._rows(results.get("organic"), "organic")
            for result in organic_results:
                clean_result = {
                    "type": "page",
                }
                if "title" in result:
                    clean_result["title"] = result["title"]
                if "desc" in result:
                    clean_result["desc"] = result["desc"]
                    clean_result["snippet"] = result["desc"]
                if "url" in result:
                    url = _safe_public_url(result["url"])
                    if not url or url in seen_urls:
                        continue
                    clean_result["url"] = url
                    seen_urls.add(url)
                    clean_results.append(clean_result)
                    counts["pages"] += 1

            top_stories = results.get("top_stories")
            if isinstance(top_stories, dict):
                news_items = cls._rows(top_stories.get("items"), "top_stories.items")
                for obj in news_items:
                    clean_result = {
                        "type": "news",
                    }
                    if "time_frame" in obj:
                        clean_result["time_frame"] = obj["time_frame"]
                    if "source" in obj:
                        clean_result["source"] = obj["source"]
                    title = obj.get("title")
                    url = _safe_public_url(obj.get("url"))
                    if title:
                        clean_result["title"] = title
                    if url:
                        clean_result["url"] = url
                    if title and url and url not in seen_urls:
                        seen_urls.add(url)
                        clean_results.append(clean_result)
                        counts["news"] += 1
            elif top_stories is not None:
                logger.error("InfoQuest returned an unexpected 'top_stories' container type: %s", type(top_stories).__name__)
                raise InfoQuestResponseError("InfoQuest returned an unexpected response format")
        logger.debug(f"Results processing completed | total_results={len(clean_results)} | pages={counts['pages']} | news_items={counts['news']} | unique_urls={len(seen_urls)}")

        return clean_results

    async def web_search(
        self,
        query: str,
        site: str = "",
        output_format: str = "JSON",
    ) -> str:
        if logger.isEnabledFor(logging.DEBUG):
            query_truncated = query[:50] + "..." if len(query) > 50 else query
            logger.debug(
                f"InfoQuest - Search API request initiated | "
                f"operation=search webs | "
                f"query_truncated={query_truncated} | "
                f"has_time_filter={self.search_time_range > 0} | time_filter={self.search_time_range} | "
                f"has_site_filter={bool(site)} | site={site} | "
                f"request_type=async"
            )

        try:
            logger.debug("InfoQuest Web-Search - Executing search with parameters")
            raw_results = await self.web_search_raw_results(
                query,
                site,
                output_format,
            )
            if not isinstance(raw_results, dict):
                logger.error("InfoQuest returned an unexpected search payload type: %s", type(raw_results).__name__)
                return "Error: InfoQuest returned an unexpected response format"
            if "search_result" in raw_results:
                logger.debug("InfoQuest Web-Search - Successfully extracted search_result from JSON response")
                results = raw_results["search_result"]
                if not isinstance(results, dict):
                    logger.error("InfoQuest returned an unexpected 'search_result' payload type: %s", type(results).__name__)
                    return "Error: InfoQuest returned an unexpected response format"

                logger.debug("InfoQuest Web-Search - Processing raw search results")
                # A missing or null ``results`` is an empty search; a container
                # that is not a list, or one holding no usable entry, is the
                # provider's format error (raised by ``clean_results``).
                cleaned_results = self.clean_results(results.get("results") if results.get("results") is not None else [])

                result_json = json.dumps(cleaned_results, indent=2, ensure_ascii=False)

                logger.debug(f"InfoQuest Web-Search - Search tool execution completed | mode=asynchronous | results_count={len(cleaned_results)}")
                return result_json

            elif "content" in raw_results:
                # Fallback to content field if search_result is not available
                error_message = "web search API return wrong format"
                logger.error("web search API return wrong format, no search_result nor content field found in JSON response, content: %s", raw_results["content"])
                return f"Error: {error_message}"
            else:
                # Unknown envelopes must not bypass result-URL screening.
                logger.warning("InfoQuest Web-Search - Missing search_result envelope")
                return "Error: InfoQuest returned an unexpected response format"

        except InfoQuestResponseError:
            return "Error: InfoQuest returned an unexpected response format"
        except Exception as e:
            error_message = f"InfoQuest Web-Search - Search tool execution failed | mode=asynchronous | error={str(e)}"
            logger.error(error_message)
            return f"Error: {error_message}"

    @classmethod
    def clean_results_with_image_search(cls, raw_results: list[dict[str, dict[str, dict[str, Any]]]]) -> list[dict]:
        """Clean results from InfoQuest Web-Search API."""
        logger.debug("Processing web-search results")

        seen_urls = set()
        clean_results = []
        counts = {"images": 0}

        for results in cls._envelope_entries(raw_results):
            for result in cls._rows(results.get("images_results"), "images_results"):
                clean_result = {}
                if "original" in result:
                    image_url = _safe_public_url(result["original"])
                    if not image_url or image_url in seen_urls:
                        continue
                    clean_result["image_url"] = image_url
                    seen_urls.add(image_url)
                    clean_results.append(clean_result)
                    counts["images"] += 1
                if "title" in result:
                    clean_result["title"] = result["title"]
        logger.debug(f"Results processing completed | total_results={len(clean_results)} | images={counts['images']} | unique_urls={len(seen_urls)}")

        return clean_results

    async def image_search_raw_results(
        self,
        query: str,
        site: str = "",
        output_format: str = "JSON",
    ) -> dict:
        """Get image search results from the InfoQuest Web-Search API asynchronously."""
        headers = self._prepare_headers()

        params = {"format": output_format, "query": query, "search_type": "Images"}

        # Add time_range filter if specified (1-365)
        if 1 <= self.image_search_time_range <= 365:
            params["time_range"] = self.image_search_time_range
        elif self.image_search_time_range > 0:
            logger.warning(f"time_range {self.image_search_time_range} is out of valid range (1-365), ignoring")

        # Add site filter if specified
        if site:
            params["site"] = site

        # Add image_size filter if specified
        if self.image_size and self.image_size in ["l", "m", "i"]:
            params["image_size"] = self.image_size
        elif self.image_size:
            logger.warning(f"image_size {self.image_size} is not valid, must be 'l', 'm', or 'i'")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post("https://search.infoquest.bytepluses.com", headers=headers, json=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()

        # Print partial response for debugging
        response_json = response.json()
        if logger.isEnabledFor(logging.DEBUG):
            response_sample = json.dumps(response_json)[:200] + ("..." if len(json.dumps(response_json)) > 200 else "")
            logger.debug(f"Image Search API request completed successfully | service=InfoQuest | status=success | response_sample={response_sample}")

        return response_json

    async def image_search(
        self,
        query: str,
        site: str = "",
        output_format: str = "JSON",
    ) -> str:
        if logger.isEnabledFor(logging.DEBUG):
            query_truncated = query[:50] + "..." if len(query) > 50 else query
            logger.debug(
                f"InfoQuest - Image Search API request initiated | "
                f"operation=search images | "
                f"query_truncated={query_truncated} | "
                f"has_site_filter={bool(site)} | site={site} | "
                f"image_search_time_range={self.image_search_time_range if self.image_search_time_range >= 1 and self.image_search_time_range <= 365 else 'default'} | "
                f"image_size={self.image_size} |"
                f"request_type=async"
            )

        try:
            logger.info("InfoQuest Image Search - Executing search with parameters")
            raw_results = await self.image_search_raw_results(
                query,
                site,
                output_format,
            )

            if not isinstance(raw_results, dict):
                logger.error("InfoQuest returned an unexpected image search payload type: %s", type(raw_results).__name__)
                return "Error: InfoQuest returned an unexpected response format"
            if "search_result" in raw_results:
                logger.debug("InfoQuest Image Search - Successfully extracted search_result from JSON response")
                results = raw_results["search_result"]
                if not isinstance(results, dict):
                    logger.error("InfoQuest returned an unexpected 'search_result' payload type: %s", type(results).__name__)
                    return "Error: InfoQuest returned an unexpected response format"

                logger.debug(f"InfoQuest Image Search - Processing raw image search results: {results}")
                images = results.get("results")
                cleaned_results = self.clean_results_with_image_search(images if images is not None else [])

                result_json = json.dumps(cleaned_results, indent=2, ensure_ascii=False)

                logger.debug(f"InfoQuest Image Search - Image search tool execution completed | mode=asynchronous | results_count={len(cleaned_results)}")
                return result_json

            elif "content" in raw_results:
                # Fallback to content field if search_result is not available
                error_message = "image search API return wrong format"
                logger.error("image search API return wrong format, no search_result nor content field found in JSON response, content: %s", raw_results["content"])
                return f"Error: {error_message}"
            else:
                # Unknown envelopes must not bypass result-URL screening.
                logger.warning("InfoQuest Image Search - Missing search_result envelope")
                return "Error: InfoQuest returned an unexpected response format"

        except InfoQuestResponseError:
            return "Error: InfoQuest returned an unexpected response format"
        except Exception as e:
            error_message = f"InfoQuest Image Search - Image search tool execution failed | mode=asynchronous | error={str(e)}"
            logger.error(error_message)
            return f"Error: {error_message}"

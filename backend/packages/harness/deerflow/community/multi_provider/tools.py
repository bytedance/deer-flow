"""
Multi-Provider Web Search Tool
Configurable search provider chain with automatic fallback
Supports: SearXNG, InfoQuest, Tavily
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from langchain.tools import tool

from deerflow.config import get_app_config

from .adapters import InfoQuestAdapter, SearXNGAdapter, TavilyAdapter
from .types import ProviderConfig, SearchProvider

logger = logging.getLogger(__name__)


class MultiProviderSearchClient:
    """Web search client with configurable multi-provider fallback chain."""

    def __init__(self):
        self.providers: list[SearchProvider] = []
        self.stats: dict[str, int] = defaultdict(int)
        self._initialize_providers()

    def _load_config(self) -> dict:
        """Load configuration from config.yaml."""
        config = get_app_config().get_tool_config("web_search")
        if config is None:
            logger.warning("No web_search tool config found, using defaults")
            return {}
        return config.model_extra

    def _get_provider_chain(self, config: dict) -> list[ProviderConfig]:
        """
        Get ordered list of providers from config.

        Args:
            config: Tool configuration dictionary

        Returns:
            List of ProviderConfig objects in order
        """
        providers_list = config.get("providers", None)

        # Backwards compatibility: if no providers key at all, default to infoquest → tavily
        if providers_list is None:
            logger.info("No providers array in config, defaulting to [infoquest, tavily]")
            return [ProviderConfig(name="infoquest", enabled=True), ProviderConfig(name="tavily", enabled=True)]

        # Parse providers array
        provider_configs = []
        for p in providers_list:
            if isinstance(p, dict):
                provider_configs.append(ProviderConfig(name=p.get("name", ""), enabled=p.get("enabled", True)))
            elif isinstance(p, str):
                provider_configs.append(ProviderConfig(name=p, enabled=True))

        # Filter to enabled providers only
        enabled_providers = [p for p in provider_configs if p.enabled]

        if not enabled_providers:
            logger.warning("No enabled providers in config")

        return enabled_providers

    def _initialize_providers(self):
        """Initialize search providers based on config."""
        config = self._load_config()
        provider_configs = self._get_provider_chain(config)

        logger.info(f"Initializing {len(provider_configs)} search providers")

        for provider_config in provider_configs:
            try:
                if provider_config.name == "searxng":
                    adapter = self._init_searxng(config)
                elif provider_config.name == "infoquest":
                    adapter = self._init_infoquest(config)
                elif provider_config.name == "tavily":
                    adapter = self._init_tavily(config)
                else:
                    logger.warning(f"Unknown provider: {provider_config.name}")
                    continue

                self.providers.append(adapter)
                self.stats[f"{provider_config.name}_success"] = 0
                self.stats[f"{provider_config.name}_failure"] = 0
                logger.info(f"✅ {provider_config.name} initialized ({len(self.providers)}/{len(provider_configs)})")

            except Exception as e:
                logger.warning(f"⚠️ {provider_config.name} initialization failed: {e}")
                continue

        if not self.providers:
            logger.error("No search providers initialized successfully")

    def _init_searxng(self, config: dict) -> SearXNGAdapter:
        """Initialize SearXNG adapter from config."""
        searx_host = config.get("searxng_host", "http://localhost:8888")
        engines = config.get("searxng_engines", [])
        categories = config.get("searxng_categories", [])
        language = config.get("searxng_language", "en")
        unsecure = config.get("searxng_unsecure", False)

        return SearXNGAdapter(searx_host=searx_host, engines=engines, categories=categories, language=language, unsecure=unsecure)

    def _init_infoquest(self, config: dict) -> InfoQuestAdapter:
        """Initialize InfoQuest adapter from config."""
        search_time_range = config.get("search_time_range", -1)
        return InfoQuestAdapter(search_time_range=search_time_range)

    def _init_tavily(self, config: dict) -> TavilyAdapter:
        """Initialize Tavily adapter from config."""
        api_key = config.get("tavily_api_key")
        return TavilyAdapter(api_key=api_key)

    def web_search(self, query: str, max_results: int = 5) -> str:
        """
        Search the web using configured provider chain.

        Tries providers in order until one succeeds. Tracks statistics for each provider.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            JSON string with search results

        Raises:
            Exception: If all providers fail
        """
        if not self.providers:
            raise Exception("No search providers available. Check configuration and API keys.")

        errors = []

        for idx, provider in enumerate(self.providers):
            try:
                provider_name = provider.get_name()
                logger.info(f"🔍 Searching with {provider_name} ({idx + 1}/{len(self.providers)}): {query}")

                results = provider.search(query, max_results)
                self.stats[f"{provider_name}_success"] += 1

                # Backwards compatibility: track tavily_fallback counter
                if provider_name == "tavily" and idx > 0:
                    self.stats["tavily_fallback"] += 1

                logger.info(f"✅ {provider_name} search successful | results={len(results)}")

                # Convert to JSON
                result_dicts = [r.to_dict() for r in results]
                return json.dumps(result_dicts, ensure_ascii=False, indent=2)

            except Exception as e:
                provider_name = provider.get_name()
                logger.warning(f"⚠️ {provider_name} search failed: {e}")
                self.stats[f"{provider_name}_failure"] += 1
                errors.append(f"{provider_name}: {str(e)}")
                continue

        # All providers failed
        error_msg = f"All search providers failed. Errors: {'; '.join(errors)}"
        logger.error(error_msg)
        raise Exception(error_msg)

    def web_fetch(self, url: str) -> str:
        """
        Fetch content from a URL using configured provider chain.

        Tries providers in order until one succeeds. SearXNG is automatically
        skipped as it doesn't support fetching.

        Args:
            url: URL to fetch content from

        Returns:
            Extracted text content

        Raises:
            Exception: If all providers fail
        """
        if not self.providers:
            raise Exception("No search providers available. Check configuration and API keys.")

        errors = []

        for idx, provider in enumerate(self.providers):
            provider_name = provider.get_name()

            # Skip SearXNG for fetch operations
            if provider_name == "searxng":
                logger.debug(f"⏭️ Skipping {provider_name} for fetch (not supported)")
                continue

            try:
                logger.info(f"📄 Fetching with {provider_name} ({idx + 1}/{len(self.providers)}): {url}")

                content = provider.fetch(url)
                self.stats[f"{provider_name}_fetch_success"] += 1

                logger.info(f"✅ {provider_name} fetch successful")
                return content

            except NotImplementedError:
                # Provider doesn't support fetch, skip it
                logger.debug(f"⏭️ {provider_name} doesn't support fetch")
                continue
            except Exception as e:
                logger.warning(f"⚠️ {provider_name} fetch failed: {e}")
                self.stats[f"{provider_name}_fetch_failure"] += 1
                errors.append(f"{provider_name}: {str(e)}")
                continue

        # All providers failed
        error_msg = f"All fetch providers failed for {url}. Errors: {'; '.join(errors)}"
        logger.error(error_msg)
        raise Exception(error_msg)

    def get_stats(self) -> dict[str, int]:
        """
        Get usage statistics for all providers.

        Returns:
            Dictionary with per-provider success/failure counters
        """
        return dict(self.stats)


# Global client instance — reset when config file changes (mtime-based)
_multi_client: MultiProviderSearchClient | None = None
_multi_client_config_mtime: float = 0.0


def get_multi_client() -> MultiProviderSearchClient:
    """Get or create the multi-provider client singleton, resetting on config change."""
    global _multi_client, _multi_client_config_mtime
    try:
        from deerflow.config.app_config import AppConfig

        config_path = AppConfig.resolve_config_path()
        mtime = config_path.stat().st_mtime if config_path.exists() else 0.0
    except Exception:
        mtime = 0.0

    if _multi_client is None or mtime > _multi_client_config_mtime:
        _multi_client = MultiProviderSearchClient()
        _multi_client_config_mtime = mtime
    return _multi_client  # type: ignore[return-value]


@tool
def web_search_multi(query: str) -> str:
    """
    Search the web using multi-provider setup with automatic fallback.

    Tries providers in configured order (default: InfoQuest → Tavily). Supports
    SearXNG, InfoQuest, and Tavily with configurable provider chain.

    Args:
        query: The search query string

    Returns:
        JSON string containing search results with title, url, snippet, and type

    Example:
        >>> result = web_search_multi("latest AI news")
        >>> # Returns: [{"title": "...", "url": "...", "snippet": "...", "type": "page"}, ...]
    """
    client = get_multi_client()
    return client.web_search(query)


@tool
def web_fetch_multi(url: str) -> str:
    """
    Fetch and extract content from a URL using multi-provider setup.

    Tries providers in configured order. SearXNG is automatically skipped as it
    doesn't support fetching.

    Args:
        url: The URL to fetch content from

    Returns:
        Extracted text content from the webpage
    """
    client = get_multi_client()
    return client.web_fetch(url)


@tool
def web_search_stats() -> str:
    """
    Get usage statistics for the multi-provider search system.

    Returns:
        JSON string with usage counts for each provider
    """
    client = get_multi_client()
    stats = client.get_stats()
    return json.dumps(stats, indent=2)


# Export tools
__all__ = ["web_search_multi", "web_fetch_multi", "web_search_stats", "get_multi_client"]

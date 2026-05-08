"""
Multi-provider web search with configurable fallback chain.
Supports: SearXNG, InfoQuest, Tavily
"""

from .tools import get_multi_client, web_fetch_multi, web_search_multi, web_search_stats

__all__ = ["web_search_multi", "web_fetch_multi", "web_search_stats", "get_multi_client"]

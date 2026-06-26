"""Type definitions for multi-provider search system."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    """Normalized search result format across all providers."""

    title: str
    url: str
    snippet: str
    type: str = "page"

    def to_dict(self) -> dict:
        """Convert to dictionary format for JSON serialization."""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "type": self.type,
        }


class SearchProvider(Protocol):
    """Protocol defining the interface for search provider adapters."""

    def get_name(self) -> str:
        """Return the provider name (e.g., 'searxng', 'infoquest', 'tavily')."""
        ...

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Execute a web search and return normalized results."""
        ...

    def fetch(self, url: str) -> str:
        """Fetch content from a URL. Returns markdown or text content."""
        ...


@dataclass
class ProviderConfig:
    """Configuration for a single search provider."""

    name: str
    enabled: bool = True

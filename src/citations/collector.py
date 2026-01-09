# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation collector for gathering and managing citations during research.
"""

import logging
from typing import Any, Dict, List, Optional

from .models import Citation, CitationMetadata

logger = logging.getLogger(__name__)


class CitationCollector:
    """
    Collects and manages citations during the research process.

    This class handles:
    - Collecting citations from search results and crawled pages
    - Deduplicating citations by URL
    - Assigning citation numbers
    - Tracking which citations are actually used in the report
    """

    def __init__(self):
        self._citations: Dict[str, CitationMetadata] = {}  # url -> metadata
        self._citation_order: List[str] = []  # ordered list of URLs
        self._used_citations: set[str] = set()  # URLs that are actually cited

    def add_from_search_results(
        self, results: List[Dict[str, Any]], query: str = ""
    ) -> List[CitationMetadata]:
        """
        Add citations from search results.

        Args:
            results: List of search result dictionaries
            query: The search query that produced these results

        Returns:
            List of CitationMetadata objects that were added
        """
        added = []
        for result in results:
            # Skip image results
            if result.get("type") == "image_url":
                continue

            url = result.get("url")
            if not url:
                continue

            # Create or update citation metadata
            metadata = CitationMetadata.from_search_result(result, query)

            if url not in self._citations:
                self._citations[url] = metadata
                self._citation_order.append(url)
                added.append(metadata)
                logger.debug(f"Added citation: {metadata.title} ({url})")
            else:
                # Update with potentially better metadata
                existing = self._citations[url]
                if metadata.relevance_score > existing.relevance_score:
                    self._citations[url] = metadata
                    logger.debug(f"Updated citation: {metadata.title} ({url})")

        return added

    def add_from_crawl_result(
        self, url: str, title: str, content: Optional[str] = None, **extra_metadata
    ) -> CitationMetadata:
        """
        Add or update a citation from a crawled page.

        Args:
            url: The URL of the crawled page
            title: The page title
            content: The page content
            **extra_metadata: Additional metadata fields

        Returns:
            The CitationMetadata object
        """
        if url in self._citations:
            # Update existing citation with crawled content
            metadata = self._citations[url]
            if title and title != "Untitled":
                metadata.title = title
            if content:
                metadata.raw_content = content
                if not metadata.content_snippet:
                    metadata.content_snippet = content[:500]
        else:
            # Create new citation
            metadata = CitationMetadata(
                url=url,
                title=title or "Untitled",
                content_snippet=content[:500] if content else None,
                raw_content=content,
                **extra_metadata,
            )
            self._citations[url] = metadata
            self._citation_order.append(url)

        return metadata

    def mark_used(self, url: str) -> Optional[int]:
        """
        Mark a citation as used and return its number.

        Args:
            url: The URL of the citation

        Returns:
            The citation number (1-indexed) or None if not found
        """
        if url in self._citations:
            self._used_citations.add(url)
            return self.get_number(url)
        return None

    def get_number(self, url: str) -> Optional[int]:
        """
        Get the citation number for a URL.

        Args:
            url: The URL to look up

        Returns:
            The citation number (1-indexed) or None if not found
        """
        try:
            return self._citation_order.index(url) + 1
        except ValueError:
            return None

    def get_metadata(self, url: str) -> Optional[CitationMetadata]:
        """
        Get the metadata for a URL.

        Args:
            url: The URL to look up

        Returns:
            The CitationMetadata or None if not found
        """
        return self._citations.get(url)

    def get_all_citations(self) -> List[Citation]:
        """
        Get all collected citations in order.

        Returns:
            List of Citation objects
        """
        citations = []
        for i, url in enumerate(self._citation_order):
            metadata = self._citations[url]
            citations.append(
                Citation(
                    number=i + 1,
                    metadata=metadata,
                )
            )
        return citations

    def get_used_citations(self) -> List[Citation]:
        """
        Get only the citations that have been marked as used.

        Returns:
            List of Citation objects that are actually used
        """
        citations = []
        number = 1
        for url in self._citation_order:
            if url in self._used_citations:
                metadata = self._citations[url]
                citations.append(
                    Citation(
                        number=number,
                        metadata=metadata,
                    )
                )
                number += 1
        return citations

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the collector state to a dictionary.

        Returns:
            Dictionary representation of the collector
        """
        return {
            "citations": [c.to_dict() for c in self.get_all_citations()],
            "used_urls": list(self._used_citations),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CitationCollector":
        """
        Deserialize a collector from a dictionary.

        Args:
            data: Dictionary representation

        Returns:
            CitationCollector instance
        """
        collector = cls()
        for citation_data in data.get("citations", []):
            citation = Citation.from_dict(citation_data)
            collector._citations[citation.url] = citation.metadata
            collector._citation_order.append(citation.url)
        collector._used_citations = set(data.get("used_urls", []))
        return collector

    def merge_with(self, other: "CitationCollector") -> None:
        """
        Merge another collector's citations into this one.

        Args:
            other: Another CitationCollector to merge
        """
        for url in other._citation_order:
            if url not in self._citations:
                self._citations[url] = other._citations[url]
                self._citation_order.append(url)
        self._used_citations.update(other._used_citations)

    @property
    def count(self) -> int:
        """Return the total number of citations."""
        return len(self._citations)

    @property
    def used_count(self) -> int:
        """Return the number of used citations."""
        return len(self._used_citations)

    def clear(self) -> None:
        """Clear all citations."""
        self._citations.clear()
        self._citation_order.clear()
        self._used_citations.clear()


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract URLs from markdown text.

    Args:
        text: Markdown text that may contain URLs

    Returns:
        List of URLs found in the text
    """
    import re

    urls = []

    # Match markdown links: [text](url)
    markdown_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
    for match in re.finditer(markdown_pattern, text):
        url = match.group(2)
        if url.startswith(("http://", "https://")):
            urls.append(url)

    # Match bare URLs
    bare_url_pattern = r"(?<![\(\[])(https?://[^\s\)>\]]+)"
    for match in re.finditer(bare_url_pattern, text):
        url = match.group(1)
        if url not in urls:
            urls.append(url)

    return urls

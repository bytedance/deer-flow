# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for CitationCollector optimization with reverse index cache.

Tests the O(1) URL lookup performance optimization via _url_to_index cache.
"""

from src.citations.collector import CitationCollector


class TestCitationCollectorOptimization:
    """Test CitationCollector reverse index cache optimization."""

    def test_url_to_index_cache_initialization(self):
        """Test that _url_to_index is properly initialized."""
        collector = CitationCollector()
        assert hasattr(collector, "_url_to_index")
        assert isinstance(collector._url_to_index, dict)
        assert len(collector._url_to_index) == 0

    def test_add_single_citation_updates_cache(self):
        """Test that adding a citation updates _url_to_index."""
        collector = CitationCollector()
        results = [
            {
                "url": "https://example.com",
                "title": "Example",
                "content": "Content",
                "score": 0.9,
            }
        ]

        collector.add_from_search_results(results)

        # Check cache is populated
        assert "https://example.com" in collector._url_to_index
        assert collector._url_to_index["https://example.com"] == 0

    def test_add_multiple_citations_updates_cache_correctly(self):
        """Test that multiple citations are indexed correctly."""
        collector = CitationCollector()
        results = [
            {
                "url": f"https://example.com/{i}",
                "title": f"Page {i}",
                "content": f"Content {i}",
                "score": 0.9,
            }
            for i in range(5)
        ]

        collector.add_from_search_results(results)

        # Check all URLs are indexed
        assert len(collector._url_to_index) == 5
        for i in range(5):
            url = f"https://example.com/{i}"
            assert collector._url_to_index[url] == i

    def test_get_number_uses_cache_for_o1_lookup(self):
        """Test that get_number uses cache for O(1) lookup."""
        collector = CitationCollector()
        urls = [f"https://example.com/{i}" for i in range(100)]
        results = [
            {
                "url": url,
                "title": f"Title {i}",
                "content": f"Content {i}",
                "score": 0.9,
            }
            for i, url in enumerate(urls)
        ]

        collector.add_from_search_results(results)

        # Test lookup for various positions
        assert collector.get_number("https://example.com/0") == 1
        assert collector.get_number("https://example.com/50") == 51
        assert collector.get_number("https://example.com/99") == 100

        # Non-existent URL returns None
        assert collector.get_number("https://nonexistent.com") is None

    def test_add_from_crawl_result_updates_cache(self):
        """Test that add_from_crawl_result updates cache."""
        collector = CitationCollector()

        collector.add_from_crawl_result(
            url="https://crawled.com/page",
            title="Crawled Page",
            content="Crawled content",
        )

        assert "https://crawled.com/page" in collector._url_to_index
        assert collector._url_to_index["https://crawled.com/page"] == 0

    def test_duplicate_url_does_not_change_cache(self):
        """Test that adding duplicate URLs doesn't change cache indices."""
        collector = CitationCollector()

        # Add first time
        collector.add_from_search_results(
            [
                {
                    "url": "https://example.com",
                    "title": "Title 1",
                    "content": "Content 1",
                    "score": 0.8,
                }
            ]
        )
        assert collector._url_to_index["https://example.com"] == 0

        # Add same URL again with better score
        collector.add_from_search_results(
            [
                {
                    "url": "https://example.com",
                    "title": "Title 1 Updated",
                    "content": "Content 1 Updated",
                    "score": 0.95,
                }
            ]
        )

        # Cache index should not change
        assert collector._url_to_index["https://example.com"] == 0
        # But metadata should be updated
        assert collector._citations["https://example.com"].relevance_score == 0.95

    def test_merge_with_updates_cache_correctly(self):
        """Test that merge_with correctly updates cache for new URLs."""
        collector1 = CitationCollector()
        collector2 = CitationCollector()

        # Add to collector1
        collector1.add_from_search_results(
            [
                {
                    "url": "https://a.com",
                    "title": "A",
                    "content": "Content A",
                    "score": 0.9,
                }
            ]
        )

        # Add to collector2
        collector2.add_from_search_results(
            [
                {
                    "url": "https://b.com",
                    "title": "B",
                    "content": "Content B",
                    "score": 0.9,
                }
            ]
        )

        collector1.merge_with(collector2)

        # Both URLs should be in cache
        assert "https://a.com" in collector1._url_to_index
        assert "https://b.com" in collector1._url_to_index
        assert collector1._url_to_index["https://a.com"] == 0
        assert collector1._url_to_index["https://b.com"] == 1

    def test_from_dict_rebuilds_cache(self):
        """Test that from_dict properly rebuilds cache."""
        # Create original collector
        original = CitationCollector()
        original.add_from_search_results(
            [
                {
                    "url": f"https://example.com/{i}",
                    "title": f"Page {i}",
                    "content": f"Content {i}",
                    "score": 0.9,
                }
                for i in range(3)
            ]
        )

        # Serialize and deserialize
        data = original.to_dict()
        restored = CitationCollector.from_dict(data)

        # Check cache is properly rebuilt
        assert len(restored._url_to_index) == 3
        for i in range(3):
            url = f"https://example.com/{i}"
            assert url in restored._url_to_index
            assert restored._url_to_index[url] == i

    def test_clear_resets_cache(self):
        """Test that clear() properly resets the cache."""
        collector = CitationCollector()
        collector.add_from_search_results(
            [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "content": "Content",
                    "score": 0.9,
                }
            ]
        )

        assert len(collector._url_to_index) > 0

        collector.clear()

        assert len(collector._url_to_index) == 0
        assert len(collector._citations) == 0
        assert len(collector._citation_order) == 0

    def test_cache_consistency_with_order_list(self):
        """Test that cache indices match positions in _citation_order."""
        collector = CitationCollector()
        urls = [f"https://example.com/{i}" for i in range(10)]
        results = [
            {
                "url": url,
                "title": f"Title {i}",
                "content": f"Content {i}",
                "score": 0.9,
            }
            for i, url in enumerate(urls)
        ]

        collector.add_from_search_results(results)

        # Verify cache indices match order list positions
        for i, url in enumerate(collector._citation_order):
            assert collector._url_to_index[url] == i

    def test_mark_used_with_cache(self):
        """Test that mark_used works correctly with cache."""
        collector = CitationCollector()
        collector.add_from_search_results(
            [
                {
                    "url": "https://example.com/1",
                    "title": "Page 1",
                    "content": "Content 1",
                    "score": 0.9,
                },
                {
                    "url": "https://example.com/2",
                    "title": "Page 2",
                    "content": "Content 2",
                    "score": 0.9,
                },
            ]
        )

        # Mark one as used
        number = collector.mark_used("https://example.com/2")
        assert number == 2

        # Verify it's in used set
        assert "https://example.com/2" in collector._used_citations

    def test_large_collection_cache_performance(self):
        """Test that cache works correctly with large collections."""
        collector = CitationCollector()
        num_citations = 1000
        results = [
            {
                "url": f"https://example.com/{i}",
                "title": f"Title {i}",
                "content": f"Content {i}",
                "score": 0.9,
            }
            for i in range(num_citations)
        ]

        collector.add_from_search_results(results)

        # Verify cache size
        assert len(collector._url_to_index) == num_citations

        # Test lookups at various positions
        test_indices = [0, 100, 500, 999]
        for idx in test_indices:
            url = f"https://example.com/{idx}"
            assert collector.get_number(url) == idx + 1

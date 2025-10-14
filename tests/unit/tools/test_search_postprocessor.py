import pytest

from src.tools.search_postprocessor import SearchResultPostProcessor


class TestSearchResultPostProcessor:
    """Test cases for SearchResultPostProcessor"""

    @pytest.fixture
    def post_processor(self):
        """Create a SearchResultPostProcessor instance for testing"""
        return SearchResultPostProcessor(
            min_score_threshold=0.5, max_content_length_per_page=100
        )

    def test_process_results_empty_input(self, post_processor):
        """Test processing empty results"""
        results = []
        processed = post_processor.process_results(results)
        assert processed == []

    def test_process_results_with_valid_page_results(self, post_processor):
        """Test processing valid page results"""
        results = [
            {
                "type": "page",
                "title": "Test Page",
                "url": "https://example.com",
                "content": "Test content",
                "score": 0.8,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["title"] == "Test Page"
        assert processed[0]["url"] == "https://example.com"
        assert processed[0]["content"] == "Test content"
        assert processed[0]["score"] == 0.8

    def test_process_results_filter_low_score(self, post_processor):
        """Test filtering out low score results"""
        results = [
            {
                "type": "page",
                "title": "Low Score Page",
                "url": "https://example.com/low",
                "content": "Low score content",
                "score": 0.3,  # Below threshold of 0.5
            },
            {
                "type": "page",
                "title": "High Score Page",
                "url": "https://example.com/high",
                "content": "High score content",
                "score": 0.9,
            },
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["title"] == "High Score Page"

    def test_process_results_remove_duplicates(self, post_processor):
        """Test removing duplicate URLs"""
        results = [
            {
                "type": "page",
                "title": "Page 1",
                "url": "https://example.com",
                "content": "Content 1",
                "score": 0.8,
            },
            {
                "type": "page",
                "title": "Page 2",
                "url": "https://example.com",  # Duplicate URL
                "content": "Content 2",
                "score": 0.7,
            },
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["title"] == "Page 1"  # First one should be kept

    def test_process_results_sort_by_score(self, post_processor):
        """Test sorting results by score in descending order"""
        results = [
            {
                "type": "page",
                "title": "Low Score",
                "url": "https://example.com/low",
                "content": "Low score content",
                "score": 0.3,
            },
            {
                "type": "page",
                "title": "High Score",
                "url": "https://example.com/high",
                "content": "High score content",
                "score": 0.9,
            },
            {
                "type": "page",
                "title": "Medium Score",
                "url": "https://example.com/medium",
                "content": "Medium score content",
                "score": 0.6,
            },
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 2  # Low score filtered out
        # Should be sorted by score descending
        assert processed[0]["title"] == "High Score"
        assert processed[1]["title"] == "Medium Score"

    def test_process_results_truncate_long_content(self, post_processor):
        """Test truncating long content"""
        long_content = "A" * 150  # Longer than max_content_length of 100
        results = [
            {
                "type": "page",
                "title": "Long Content Page",
                "url": "https://example.com",
                "content": long_content,
                "score": 0.8,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert len(processed[0]["content"]) == 103  # 100 + "..."
        assert processed[0]["content"].endswith("...")

    def test_process_results_remove_base64_images(self, post_processor):
        """Test removing base64 images from content"""
        content_with_base64 = (
            "Content with image "
            + "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        results = [
            {
                "type": "page",
                "title": "Page with Base64",
                "url": "https://example.com",
                "content": content_with_base64,
                "score": 0.8,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["content"] == "Content with image  "

    def test_process_results_with_image_type(self, post_processor):
        """Test processing image type results"""
        results = [
            {
                "type": "image",
                "image_url": "https://example.com/image.jpg",
                "image_description": "Test image",
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["type"] == "image"
        assert processed[0]["image_url"] == "https://example.com/image.jpg"
        assert processed[0]["image_description"] == "Test image"

    def test_process_results_filter_base64_image_urls(self, post_processor):
        """Test filtering out image results with base64 URLs"""
        results = [
            {
                "type": "image",
                "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
                "image_description": "Base64 image",
            },
            {
                "type": "image",
                "image_url": "https://example.com/image.jpg",
                "image_description": "Regular image",
            },
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["image_url"] == "https://example.com/image.jpg"

    def test_process_results_truncate_long_image_description(self, post_processor):
        """Test truncating long image descriptions"""
        long_description = "A" * 150  # Longer than max_content_length of 100
        results = [
            {
                "type": "image",
                "image_url": "https://example.com/image.jpg",
                "image_description": long_description,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert len(processed[0]["image_description"]) == 103  # 100 + "..."
        assert processed[0]["image_description"].endswith("...")

    def test_process_results_other_types_passthrough(self, post_processor):
        """Test that other result types pass through unchanged"""
        results = [
            {
                "type": "video",
                "title": "Test Video",
                "url": "https://example.com/video.mp4",
                "score": 0.8,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert processed[0]["type"] == "video"
        assert processed[0]["title"] == "Test Video"

    def test_process_results_truncate_long_content_with_no_config(self):
        """Test truncating long content"""
        post_processor = SearchResultPostProcessor(None, None)
        long_content = "A" * 150  # Longer than max_content_length of 100
        results = [
            {
                "type": "page",
                "title": "Long Content Page",
                "url": "https://example.com",
                "content": long_content,
                "score": 0.8,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert len(processed[0]["content"]) == len("A" * 150)

    def test_process_results_truncate_long_content_with_max_content_length_config(self):
        """Test truncating long content"""
        post_processor = SearchResultPostProcessor(None, 100)
        long_content = "A" * 150  # Longer than max_content_length of 100
        results = [
            {
                "type": "page",
                "title": "Long Content Page",
                "url": "https://example.com",
                "content": long_content,
                "score": 0.8,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 1
        assert len(processed[0]["content"]) == 103
        assert processed[0]["content"].endswith("...")

    def test_process_results_truncate_long_content_with_min_score_config(self):
        """Test truncating long content"""
        post_processor = SearchResultPostProcessor(0.8, None)
        long_content = "A" * 150  # Longer than max_content_length of 100
        results = [
            {
                "type": "page",
                "title": "Long Content Page",
                "url": "https://example.com",
                "content": long_content,
                "score": 0.3,
            }
        ]
        processed = post_processor.process_results(results)
        assert len(processed) == 0

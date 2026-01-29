# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


from unittest.mock import Mock, patch

import pytest
import requests

from src.tools.infoquest_search.infoquest_search_api import InfoQuestAPIWrapper


class TestInfoQuestAPIWrapper:
    @pytest.fixture
    def wrapper(self):
        # Create a wrapper instance with mock API key
        return InfoQuestAPIWrapper(infoquest_api_key="dummy-key")

    @pytest.fixture
    def mock_response_data(self):
        # Mock search result data
        return {
            "search_result": {
                "results": [
                    {
                        "content": {
                            "results": {
                                "organic": [
                                    {
                                        "title": "Test Title",
                                        "url": "https://example.com",
                                        "desc": "Test description"
                                    }
                                ],
                                "top_stories": {
                                    "items": [
                                        {
                                            "time_frame": "2 days ago",
                                            "title": "Test News",
                                            "url": "https://example.com/news",
                                            "source": "Test Source"
                                        }
                                    ]
                                },
                                "images": {
                                    "items": [
                                        {
                                            "url": "https://example.com/image.jpg",
                                            "alt": "Test image description"
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ]
            }
        }

    @patch("src.tools.infoquest_search.infoquest_search_api.requests.post")
    def test_raw_results_success(self, mock_post, wrapper, mock_response_data):
        # Test successful synchronous search results
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = wrapper.raw_results("test query", time_range=0, site="")

        assert result == mock_response_data["search_result"]
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "json" in call_args.kwargs
        assert call_args.kwargs["json"]["query"] == "test query"
        assert "time_range" not in call_args.kwargs["json"]
        assert "site" not in call_args.kwargs["json"]

    @patch("src.tools.infoquest_search.infoquest_search_api.requests.post")
    def test_raw_results_with_time_range_and_site(self, mock_post, wrapper, mock_response_data):
        # Test search with time range and site filtering
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = wrapper.raw_results("test query", time_range=30, site="example.com")

        assert result == mock_response_data["search_result"]
        call_args = mock_post.call_args
        params = call_args.kwargs["json"]
        assert params["time_range"] == 30
        assert params["site"] == "example.com"

    @patch("src.tools.infoquest_search.infoquest_search_api.requests.post")
    def test_raw_results_http_error(self, mock_post, wrapper):
        # Test HTTP error handling
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("API Error")
        mock_post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            wrapper.raw_results("test query", time_range=0, site="")

    # Check if pytest-asyncio is available, otherwise mark for conditional skipping
    try:
        import pytest_asyncio
        _asyncio_available = True
    except ImportError:
        _asyncio_available = False

    @pytest.mark.asyncio
    async def test_raw_results_async_success(self, wrapper, mock_response_data):
        # Skip only if pytest-asyncio is not installed
        if not self._asyncio_available:
            pytest.skip("pytest-asyncio is not installed")
        
        with patch('json.loads', return_value=mock_response_data):
            original_method = InfoQuestAPIWrapper.raw_results_async
            
            async def mock_raw_results_async(self, query, time_range=0, site="", output_format="json"):
                return mock_response_data["search_result"]
            
            InfoQuestAPIWrapper.raw_results_async = mock_raw_results_async
            
            try:
                result = await wrapper.raw_results_async("test query", time_range=0, site="")
                assert result == mock_response_data["search_result"]
            finally:
                InfoQuestAPIWrapper.raw_results_async = original_method

    @pytest.mark.asyncio
    async def test_raw_results_async_error(self, wrapper):
        if not self._asyncio_available:
            pytest.skip("pytest-asyncio is not installed")
        
        original_method = InfoQuestAPIWrapper.raw_results_async
        
        async def mock_raw_results_async_error(self, query, time_range=0, site="", output_format="json"):
            raise Exception("Error 400: Bad Request")
        
        InfoQuestAPIWrapper.raw_results_async = mock_raw_results_async_error
        
        try:
            with pytest.raises(Exception, match="Error 400: Bad Request"):
                await wrapper.raw_results_async("test query", time_range=0, site="")
        finally:
            InfoQuestAPIWrapper.raw_results_async = original_method

    def test_clean_results_with_images(self, wrapper, mock_response_data):
        # Test result cleaning functionality
        raw_results = mock_response_data["search_result"]["results"]
        cleaned_results = wrapper.clean_results_with_images(raw_results)

        assert len(cleaned_results) == 3

        # Test page result
        page_result = cleaned_results[0]
        assert page_result["type"] == "page"
        assert page_result["title"] == "Test Title"
        assert page_result["url"] == "https://example.com"
        assert page_result["desc"] == "Test description"

        # Test news result
        news_result = cleaned_results[1]
        assert news_result["type"] == "news"
        assert news_result["time_frame"] == "2 days ago"
        assert news_result["title"] == "Test News"
        assert news_result["url"] == "https://example.com/news"
        assert news_result["source"] == "Test Source"

        # Test image result
        image_result = cleaned_results[2]
        assert image_result["type"] == "image_url"
        assert image_result["image_url"] == "https://example.com/image.jpg"
        assert image_result["image_description"] == "Test image description"

    def test_clean_results_empty_categories(self, wrapper):
        # Test result cleaning with empty categories
        data = [
            {
                "content": {
                    "results": {
                        "organic": [],
                        "top_stories": {"items": []},
                        "images": {"items": []}
                    }
                }
            }
        ]

        result = wrapper.clean_results_with_images(data)
        assert len(result) == 0

    def test_clean_results_url_deduplication(self, wrapper):
        # Test URL deduplication functionality
        data = [
            {
                "content": {
                    "results": {
                        "organic": [
                            {
                                "title": "Test Title 1",
                                "url": "https://example.com",
                                "desc": "Description 1"
                            },
                            {
                                "title": "Test Title 2",
                                "url": "https://example.com",
                                "desc": "Description 2"
                            }
                        ]
                    }
                }
            }
        ]

        result = wrapper.clean_results_with_images(data)
        assert len(result) == 1
        assert result[0]["title"] == "Test Title 1"
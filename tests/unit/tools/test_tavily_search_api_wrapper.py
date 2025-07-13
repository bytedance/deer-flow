# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
import json
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import requests
from src.tools.tavily_search.tavily_search_api_wrapper import (
    EnhancedTavilySearchAPIWrapper,
)


class TestEnhancedTavilySearchAPIWrapper:

    @pytest.fixture
    def wrapper(self):
        with patch(
            "src.tools.tavily_search.tavily_search_api_wrapper.OriginalTavilySearchAPIWrapper"
        ):
            wrapper = EnhancedTavilySearchAPIWrapper(tavily_api_key="dummy-key")
            # The parent class is mocked, so initialization won't fail
            return wrapper

    @pytest.fixture
    def mock_response_data(self):
        return {
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "content": "Test content",
                    "score": 0.9,
                    "raw_content": "Raw test content",
                }
            ],
            "images": [
                {
                    "url": "https://example.com/image.jpg",
                    "description": "Test image description",
                }
            ],
        }

    @patch("src.tools.tavily_search.tavily_search_api_wrapper.requests.post")
    def test_raw_results_success(self, mock_post, wrapper, mock_response_data):
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = wrapper.raw_results("test query", max_results=10)

        assert result == mock_response_data
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "json" in call_args.kwargs
        assert call_args.kwargs["json"]["query"] == "test query"
        assert call_args.kwargs["json"]["max_results"] == 10

    @patch("src.tools.tavily_search.tavily_search_api_wrapper.requests.post")
    def test_raw_results_with_all_parameters(
        self, mock_post, wrapper, mock_response_data
    ):
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = wrapper.raw_results(
            "test query",
            max_results=3,
            search_depth="basic",
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
            include_answer=True,
            include_raw_content=True,
            include_images=True,
            include_image_descriptions=True,
        )

        assert result == mock_response_data
        call_args = mock_post.call_args
        params = call_args.kwargs["json"]
        assert params["include_domains"] == ["example.com"]
        assert params["exclude_domains"] == ["spam.com"]
        assert params["include_answer"] is True
        assert params["include_raw_content"] is True

    @patch("src.tools.tavily_search.tavily_search_api_wrapper.requests.post")
    def test_raw_results_http_error(self, mock_post, wrapper):
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("API Error")
        mock_post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            wrapper.raw_results("test query")

    @pytest.mark.asyncio
    async def test_raw_results_async_success(self, wrapper, mock_response_data):
        # Create a mock that acts as both the response and its context manager
        mock_response_cm = AsyncMock()
        mock_response_cm.__aenter__ = AsyncMock(return_value=mock_response_cm)
        mock_response_cm.__aexit__ = AsyncMock(return_value=None)
        mock_response_cm.status = 200
        mock_response_cm.text = AsyncMock(return_value=json.dumps(mock_response_data))

        # Create mock session that returns the context manager
        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=mock_response_cm
        )  # Use MagicMock, not AsyncMock

        # Create mock session class
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.tools.tavily_search.tavily_search_api_wrapper.aiohttp.ClientSession",
            return_value=mock_session_cm,
        ):
            result = await wrapper.raw_results_async("test query")

            assert result == mock_response_data

    @pytest.mark.asyncio
    async def test_raw_results_async_error(self, wrapper):
        # Create a mock that acts as both the response and its context manager
        mock_response_cm = AsyncMock()
        mock_response_cm.__aenter__ = AsyncMock(return_value=mock_response_cm)
        mock_response_cm.__aexit__ = AsyncMock(return_value=None)
        mock_response_cm.status = 400
        mock_response_cm.reason = "Bad Request"

        # Create mock session that returns the context manager
        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=mock_response_cm
        )  # Use MagicMock, not AsyncMock

        # Create mock session class
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.tools.tavily_search.tavily_search_api_wrapper.aiohttp.ClientSession",
            return_value=mock_session_cm,
        ):
            with pytest.raises(Exception, match="Error 400: Bad Request"):
                await wrapper.raw_results_async("test query")

    def test_clean_results_with_images(self, wrapper, mock_response_data):
        result = wrapper.clean_results_with_images(mock_response_data)

        assert len(result) == 2

        # Test page result
        page_result = result[0]
        assert page_result["type"] == "page"
        assert page_result["title"] == "Test Title"
        assert page_result["url"] == "https://example.com"
        assert page_result["content"] == "Test content"
        assert page_result["score"] == 0.9
        assert page_result["raw_content"] == "Raw test content"

        # Test image result
        image_result = result[1]
        assert image_result["type"] == "image"
        assert image_result["image_url"] == "https://example.com/image.jpg"
        assert image_result["image_description"] == "Test image description"

    def test_clean_results_without_raw_content(self, wrapper):
        data = {
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "content": "Test content",
                    "score": 0.9,
                }
            ],
            "images": [],
        }

        result = wrapper.clean_results_with_images(data)

        assert len(result) == 1
        assert "raw_content" not in result[0]

    def test_clean_results_empty_images(self, wrapper):
        data = {
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "content": "Test content",
                    "score": 0.9,
                }
            ],
            "images": [],
        }

        result = wrapper.clean_results_with_images(data)

        assert len(result) == 1
        assert result[0]["type"] == "page"

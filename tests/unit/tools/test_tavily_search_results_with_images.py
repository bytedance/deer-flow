# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchResultsWithImages,
)
from src.tools.tavily_search.tavily_search_api_wrapper import (
    EnhancedTavilySearchAPIWrapper,
)


class TestTavilySearchResultsWithImages:

    @pytest.fixture
    def mock_api_wrapper(self):
        """Create a mock API wrapper."""
        wrapper = Mock(spec=EnhancedTavilySearchAPIWrapper)
        return wrapper

    @pytest.fixture
    def search_tool(self, mock_api_wrapper):
        """Create a TavilySearchResultsWithImages instance with mocked dependencies."""
        tool = TavilySearchResultsWithImages(
            max_results=5,
            include_answer=True,
            include_raw_content=True,
            include_images=True,
            include_image_descriptions=True,
        )
        tool.api_wrapper = mock_api_wrapper
        return tool

    @pytest.fixture
    def sample_raw_results(self):
        """Sample raw results from Tavily API."""
        return {
            "query": "test query",
            "answer": "Test answer",
            "images": ["https://example.com/image1.jpg"],
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "content": "Test content",
                    "score": 0.95,
                    "raw_content": "Raw test content",
                }
            ],
            "response_time": 1.5,
        }

    @pytest.fixture
    def sample_cleaned_results(self):
        """Sample cleaned results."""
        return [
            {
                "title": "Test Title",
                "url": "https://example.com",
                "content": "Test content",
            }
        ]

    def test_init_default_values(self):
        """Test initialization with default values."""
        tool = TavilySearchResultsWithImages()
        assert tool.include_image_descriptions is False
        assert isinstance(tool.api_wrapper, EnhancedTavilySearchAPIWrapper)

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        tool = TavilySearchResultsWithImages(
            max_results=10, include_image_descriptions=True
        )
        assert tool.max_results == 10
        assert tool.include_image_descriptions is True

    @patch("builtins.print")
    def test_run_success(
        self,
        mock_print,
        search_tool,
        mock_api_wrapper,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test successful synchronous run."""
        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results_with_images.return_value = sample_cleaned_results

        result, raw = search_tool._run("test query")

        assert result == sample_cleaned_results
        assert raw == sample_raw_results

        mock_api_wrapper.raw_results.assert_called_once_with(
            "test query",
            search_tool.max_results,
            search_tool.search_depth,
            search_tool.include_domains,
            search_tool.exclude_domains,
            search_tool.include_answer,
            search_tool.include_raw_content,
            search_tool.include_images,
            search_tool.include_image_descriptions,
        )

        mock_api_wrapper.clean_results_with_images.assert_called_once_with(
            sample_raw_results
        )
        mock_print.assert_called_once()

    @patch("builtins.print")
    def test_run_exception(self, mock_print, search_tool, mock_api_wrapper):
        """Test synchronous run with exception."""
        mock_api_wrapper.raw_results.side_effect = Exception("API Error")

        result, raw = search_tool._run("test query")

        assert "API Error" in result
        assert raw == {}
        mock_api_wrapper.clean_results_with_images.assert_not_called()

    @pytest.mark.asyncio
    @patch("builtins.print")
    async def test_arun_success(
        self,
        mock_print,
        search_tool,
        mock_api_wrapper,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test successful asynchronous run."""
        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results_with_images.return_value = sample_cleaned_results

        result, raw = await search_tool._arun("test query")

        assert result == sample_cleaned_results
        assert raw == sample_raw_results

        mock_api_wrapper.raw_results_async.assert_called_once_with(
            "test query",
            search_tool.max_results,
            search_tool.search_depth,
            search_tool.include_domains,
            search_tool.exclude_domains,
            search_tool.include_answer,
            search_tool.include_raw_content,
            search_tool.include_images,
            search_tool.include_image_descriptions,
        )

        mock_api_wrapper.clean_results_with_images.assert_called_once_with(
            sample_raw_results
        )
        mock_print.assert_called_once()

    @pytest.mark.asyncio
    @patch("builtins.print")
    async def test_arun_exception(self, mock_print, search_tool, mock_api_wrapper):
        """Test asynchronous run with exception."""
        mock_api_wrapper.raw_results_async = AsyncMock(
            side_effect=Exception("Async API Error")
        )

        result, raw = await search_tool._arun("test query")

        assert "Async API Error" in result
        assert raw == {}
        mock_api_wrapper.clean_results_with_images.assert_not_called()

    @patch("builtins.print")
    def test_run_with_run_manager(
        self,
        mock_print,
        search_tool,
        mock_api_wrapper,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test run with callback manager."""
        mock_run_manager = Mock()
        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results_with_images.return_value = sample_cleaned_results

        result, raw = search_tool._run("test query", run_manager=mock_run_manager)

        assert result == sample_cleaned_results
        assert raw == sample_raw_results

    @pytest.mark.asyncio
    @patch("builtins.print")
    async def test_arun_with_run_manager(
        self,
        mock_print,
        search_tool,
        mock_api_wrapper,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test async run with callback manager."""
        mock_run_manager = Mock()
        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results_with_images.return_value = sample_cleaned_results

        result, raw = await search_tool._arun(
            "test query", run_manager=mock_run_manager
        )

        assert result == sample_cleaned_results
        assert raw == sample_raw_results

    @patch("builtins.print")
    def test_print_output_format(
        self,
        mock_print,
        search_tool,
        mock_api_wrapper,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test that print outputs correctly formatted JSON."""
        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results_with_images.return_value = sample_cleaned_results

        search_tool._run("test query")

        # Verify print was called with expected format
        call_args = mock_print.call_args[0]
        assert call_args[0] == "sync"
        assert isinstance(call_args[1], str)  # Should be JSON string

        # Verify it's valid JSON
        json_data = json.loads(call_args[1])
        assert json_data == sample_cleaned_results

    @pytest.mark.asyncio
    @patch("builtins.print")
    async def test_async_print_output_format(
        self,
        mock_print,
        search_tool,
        mock_api_wrapper,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test that async print outputs correctly formatted JSON."""
        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results_with_images.return_value = sample_cleaned_results

        await search_tool._arun("test query")

        # Verify print was called with expected format
        call_args = mock_print.call_args[0]
        assert call_args[0] == "async"
        assert isinstance(call_args[1], str)  # Should be JSON string

        # Verify it's valid JSON
        json_data = json.loads(call_args[1])
        assert json_data == sample_cleaned_results

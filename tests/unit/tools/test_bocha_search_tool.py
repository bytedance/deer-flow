# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
from unittest.mock import AsyncMock, Mock

import pytest

from src.tools.bocha_search.bocha_search_api_wrapper import BochaSearchAPIWrapper
from src.tools.bocha_search.bocha_search_tool import BochaSearchTool


class TestBochaSearchTool:
    @pytest.fixture
    def mock_api_wrapper(self) -> Mock:
        """Create a mock BochaSearchAPIWrapper."""

        return Mock(spec=BochaSearchAPIWrapper)

    @pytest.fixture
    def search_tool(self, mock_api_wrapper: Mock) -> BochaSearchTool:
        """Create a BochaSearchTool instance with mocked dependencies."""

        tool = BochaSearchTool(
            max_results=5,
            freshness="noLimit",
            summary=True,
        )
        tool.api_wrapper = mock_api_wrapper
        return tool

    @pytest.fixture
    def sample_raw_results(self):
        return {
            "code": 200,
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "Test Title",
                            "url": "https://example.com",
                            "summary": "Test summary",
                            "siteName": "Example",
                            "siteIcon": "https://example.com/favicon.ico",
                            "dateLastCrawled": "2024-01-01T00:00:00Z",
                            "score": 0.9,
                        }
                    ]
                }
            },
        }

    @pytest.fixture
    def sample_cleaned_results(self):
        return [
            {
                "type": "page",
                "title": "Test Title",
                "url": "https://example.com",
                "content": "Test summary",
                "score": 0.9,
            }
        ]

    def test_init_default_values(self):
        tool = BochaSearchTool()
        assert tool.max_results == 5
        assert tool.freshness == "noLimit"
        assert tool.summary is True
        assert isinstance(tool.api_wrapper, BochaSearchAPIWrapper)

    def test_run_success(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test successful synchronous run."""

        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        result, raw = search_tool._run("test query")

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results

        mock_api_wrapper.raw_results.assert_called_once_with(
            query="test query",
            max_results=search_tool.max_results,
            freshness=search_tool.freshness,
            summary=search_tool.summary,
        )
        mock_api_wrapper.clean_results.assert_called_once_with(sample_raw_results)

    def test_run_exception(self, search_tool, mock_api_wrapper):
        """Test synchronous run with exception."""

        mock_api_wrapper.raw_results.side_effect = Exception("API Error")

        result, raw = search_tool._run("test query")

        result_dict = json.loads(result)
        assert "error" in result_dict
        assert "API Error" in result_dict["error"]
        assert raw == {}
        mock_api_wrapper.clean_results.assert_not_called()

    @pytest.mark.asyncio
    async def test_arun_success(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test successful asynchronous run."""

        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        result, raw = await search_tool._arun("test query")

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results

        mock_api_wrapper.raw_results_async.assert_called_once_with(
            query="test query",
            max_results=search_tool.max_results,
            freshness=search_tool.freshness,
            summary=search_tool.summary,
        )
        mock_api_wrapper.clean_results.assert_called_once_with(sample_raw_results)

    @pytest.mark.asyncio
    async def test_arun_exception(self, search_tool, mock_api_wrapper):
        """Test asynchronous run with exception."""

        mock_api_wrapper.raw_results_async = AsyncMock(side_effect=Exception("Async API Error"))

        result, raw = await search_tool._arun("test query")

        result_dict = json.loads(result)
        assert "error" in result_dict
        assert "Async API Error" in result_dict["error"]
        assert raw == {}
        mock_api_wrapper.clean_results.assert_not_called()

    def test_run_with_run_manager(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test run with callback manager provided (no special logic yet)."""

        mock_run_manager = Mock()
        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        result, raw = search_tool._run("test query", run_manager=mock_run_manager)

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results

    @pytest.mark.asyncio
    async def test_arun_with_run_manager(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test async run with callback manager provided (no special logic yet)."""

        mock_run_manager = Mock()
        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        result, raw = await search_tool._arun("test query", run_manager=mock_run_manager)

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results

    def test_run_with_query_in_kwargs(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test run when query is passed as keyword argument in tool_kwargs."""

        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        # Simulate LangChain passing query as keyword argument
        result, raw = search_tool._run(query="test query from kwargs")

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results
        mock_api_wrapper.raw_results.assert_called_once_with(
            query="test query from kwargs",
            max_results=search_tool.max_results,
            freshness=search_tool.freshness,
            summary=search_tool.summary,
        )

    def test_run_with_nested_kwargs_dict(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test run when query is nested inside a kwargs dict (the TypeError pattern)."""

        mock_api_wrapper.raw_results.return_value = sample_raw_results
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        # Simulate LangChain/LangGraph passing kwargs as a nested dict
        result, raw = search_tool._run(kwargs={"query": "nested query"})

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results
        mock_api_wrapper.raw_results.assert_called_once_with(
            query="nested query",
            max_results=search_tool.max_results,
            freshness=search_tool.freshness,
            summary=search_tool.summary,
        )

    def test_run_missing_query(self, search_tool, mock_api_wrapper):
        """Test run without providing query parameter."""

        result, raw = search_tool._run()

        result_dict = json.loads(result)
        assert "error" in result_dict
        assert "requires a 'query' argument" in result_dict["error"]
        assert raw == {}
        mock_api_wrapper.raw_results.assert_not_called()

    @pytest.mark.asyncio
    async def test_arun_with_query_in_kwargs(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test async run when query is passed as keyword argument in tool_kwargs."""

        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        result, raw = await search_tool._arun(query="test query from kwargs")

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results

    @pytest.mark.asyncio
    async def test_arun_with_nested_kwargs_dict(self, search_tool, mock_api_wrapper, sample_raw_results, sample_cleaned_results):
        """Test async run when query is nested inside a kwargs dict."""

        mock_api_wrapper.raw_results_async = AsyncMock(return_value=sample_raw_results)
        mock_api_wrapper.clean_results.return_value = sample_cleaned_results

        result, raw = await search_tool._arun(kwargs={"query": "nested query"})

        assert result == json.dumps(sample_cleaned_results, ensure_ascii=False)
        assert raw == sample_raw_results

    @pytest.mark.asyncio
    async def test_arun_missing_query(self, search_tool, mock_api_wrapper):
        """Test async run without providing query parameter."""

        result, raw = await search_tool._arun()

        result_dict = json.loads(result)
        assert "error" in result_dict
        assert "requires a 'query' argument" in result_dict["error"]
        assert raw == {}
        mock_api_wrapper.raw_results_async.assert_not_called()

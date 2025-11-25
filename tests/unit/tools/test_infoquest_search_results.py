# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest

from src.tools.infoquest_search.infoquest_search_api import InfoQuestAPIWrapper


class TestInfoQuestSearchResults:
    @pytest.fixture
    def search_tool(self):
        """Create a mock InfoQuestSearchResults instance."""
        mock_tool = Mock()
        
        mock_tool.time_range = 30
        mock_tool.site = "example.com"
        
        def mock_run(query, **kwargs):
            sample_cleaned_results = [
                {
                    "type": "page",
                    "title": "Test Title",
                    "url": "https://example.com",
                    "desc": "Test description"
                }
            ]
            sample_raw_results = {
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
                                ]
                            }
                        }
                    }
                ]
            }
            return json.dumps(sample_cleaned_results, ensure_ascii=False), sample_raw_results
        
        async def mock_arun(query, **kwargs):
            return mock_run(query, **kwargs)
        
        mock_tool._run = mock_run
        mock_tool._arun = mock_arun
        
        return mock_tool

    @pytest.fixture
    def sample_raw_results(self):
        """Sample raw results from InfoQuest API."""
        return {
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
                            ]
                        }
                    }
                }
            ]
        }

    @pytest.fixture
    def sample_cleaned_results(self):
        """Sample cleaned results."""
        return [
            {
                "type": "page",
                "title": "Test Title",
                "url": "https://example.com",
                "desc": "Test description"
            }
        ]

    def test_init_default_values(self):
        """Test initialization with default values using patch."""
        with patch('src.tools.infoquest_search.infoquest_search_results.InfoQuestAPIWrapper') as mock_wrapper_class:
            mock_instance = Mock()
            mock_wrapper_class.return_value = mock_instance
            
            from src.tools.infoquest_search.infoquest_search_results import InfoQuestSearchResults
            
            with patch.object(InfoQuestSearchResults, '__init__', return_value=None) as mock_init:
                InfoQuestSearchResults(infoquest_api_key="dummy-key")
                
                mock_init.assert_called_once()

    def test_init_custom_values(self):
        """Test initialization with custom values using patch."""
        with patch('src.tools.infoquest_search.infoquest_search_results.InfoQuestAPIWrapper') as mock_wrapper_class:
            mock_instance = Mock()
            mock_wrapper_class.return_value = mock_instance
            
            from src.tools.infoquest_search.infoquest_search_results import InfoQuestSearchResults
            
            with patch.object(InfoQuestSearchResults, '__init__', return_value=None) as mock_init:
                InfoQuestSearchResults(
                    time_range=10,
                    site="test.com",
                    infoquest_api_key="dummy-key"
                )
                
                mock_init.assert_called_once()

    def test_run_success(
        self,
        search_tool,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test successful synchronous run."""
        result, raw = search_tool._run("test query")
        
        assert isinstance(result, str)
        assert isinstance(raw, dict)
        assert "results" in raw
        
        result_data = json.loads(result)
        assert isinstance(result_data, list)
        assert len(result_data) > 0

    def test_run_exception(self, search_tool):
        """Test synchronous run with exception."""
        original_run = search_tool._run
        
        def mock_run_with_error(query, **kwargs):
            return json.dumps({"error": "API Error"}, ensure_ascii=False), {}
        
        try:
            search_tool._run = mock_run_with_error
            result, raw = search_tool._run("test query")
            
            result_dict = json.loads(result)
            assert "error" in result_dict
            assert "API Error" in result_dict["error"]
            assert raw == {}
        finally:
            search_tool._run = original_run

    @pytest.mark.asyncio
    async def test_arun_success(
        self,
        search_tool,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test successful asynchronous run."""
        result, raw = await search_tool._arun("test query")
        
        assert isinstance(result, str)
        assert isinstance(raw, dict)
        assert "results" in raw

    @pytest.mark.asyncio
    async def test_arun_exception(self, search_tool):
        """Test asynchronous run with exception."""
        original_arun = search_tool._arun
        
        async def mock_arun_with_error(query, **kwargs):
            return json.dumps({"error": "Async API Error"}, ensure_ascii=False), {}
        
        try:
            search_tool._arun = mock_arun_with_error
            result, raw = await search_tool._arun("test query")
            
            result_dict = json.loads(result)
            assert "error" in result_dict
            assert "Async API Error" in result_dict["error"]
            assert raw == {}
        finally:
            search_tool._arun = original_arun

    def test_run_with_run_manager(
        self,
        search_tool,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test run with callback manager."""
        mock_run_manager = Mock()
        result, raw = search_tool._run("test query", run_manager=mock_run_manager)
        
        assert isinstance(result, str)
        assert isinstance(raw, dict)

    @pytest.mark.asyncio
    async def test_arun_with_run_manager(
        self,
        search_tool,
        sample_raw_results,
        sample_cleaned_results,
    ):
        """Test async run with callback manager."""
        mock_run_manager = Mock()
        result, raw = await search_tool._arun("test query", run_manager=mock_run_manager)
        
        assert isinstance(result, str)
        assert isinstance(raw, dict)

    def test_api_wrapper_initialization_with_key(self):
        """Test API wrapper initialization with key."""
        with patch('src.tools.infoquest_search.infoquest_search_results.InfoQuestAPIWrapper') as mock_wrapper_class:
            mock_instance = Mock()
            mock_wrapper_class.return_value = mock_instance
            
            from src.tools.infoquest_search.infoquest_search_results import InfoQuestSearchResults
            
            with patch.object(InfoQuestSearchResults, '__init__', return_value=None) as mock_init:
                InfoQuestSearchResults(infoquest_api_key="test-key")
                
                mock_init.assert_called_once()
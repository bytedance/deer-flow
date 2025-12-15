# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import SearchEngine
from src.tools.search import get_web_search_tool


class TestGetWebSearchTool:
    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    def test_get_web_search_tool_tavily(self):
        tool = get_web_search_tool(max_search_results=5)
        assert tool.name == "web_search"
        assert tool.max_results == 5
        assert tool.include_raw_content is True
        assert tool.include_images is True
        assert tool.include_image_descriptions is True
        assert tool.include_answer is False
        assert tool.search_depth == "advanced"

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.DUCKDUCKGO.value)
    def test_get_web_search_tool_duckduckgo(self):
        tool = get_web_search_tool(max_search_results=3)
        assert tool.name == "web_search"
        assert tool.max_results == 3

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.BRAVE_SEARCH.value)
    @patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test_api_key"})
    def test_get_web_search_tool_brave(self):
        tool = get_web_search_tool(max_search_results=4)
        assert tool.name == "web_search"
        assert tool.search_wrapper.api_key.get_secret_value() == "test_api_key"

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.ARXIV.value)
    def test_get_web_search_tool_arxiv(self):
        tool = get_web_search_tool(max_search_results=2)
        assert tool.name == "web_search"
        assert tool.api_wrapper.top_k_results == 2
        assert tool.api_wrapper.load_max_docs == 2
        assert tool.api_wrapper.load_all_available_meta is True

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", "unsupported_engine")
    def test_get_web_search_tool_unsupported_engine(self):
        with pytest.raises(
            ValueError, match="Unsupported search engine: unsupported_engine"
        ):
            get_web_search_tool(max_search_results=1)

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.BRAVE_SEARCH.value)
    @patch.dict(os.environ, {}, clear=True)
    def test_get_web_search_tool_brave_no_api_key(self):
        tool = get_web_search_tool(max_search_results=1)
        assert tool.search_wrapper.api_key.get_secret_value() == ""

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.SERPER.value)
    @patch.dict(os.environ, {"SERPER_API_KEY": "test_serper_key"})
    def test_get_web_search_tool_serper(self):
        tool = get_web_search_tool(max_search_results=6)
        assert tool.name == "web_search"
        assert tool.api_wrapper.k == 6
        assert tool.api_wrapper.serper_api_key == "test_serper_key"

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.SERPER.value)
    @patch.dict(os.environ, {}, clear=True)
    def test_get_web_search_tool_serper_no_api_key(self):
        with pytest.raises(ValidationError):
            get_web_search_tool(max_search_results=1)

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_get_web_search_tool_tavily_with_custom_config(self, mock_config):
        """Test Tavily tool with custom configuration values."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_answer": True,
                "search_depth": "basic",
                "include_raw_content": False,
                "include_images": False,
                "include_image_descriptions": True,
                "include_domains": ["example.com"],
                "exclude_domains": ["spam.com"],
            }
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.name == "web_search"
        assert tool.max_results == 5
        assert tool.include_answer is True
        assert tool.search_depth == "basic"
        assert tool.include_raw_content is False
        assert tool.include_images is False
        # include_image_descriptions should be False because include_images is False
        assert tool.include_image_descriptions is False
        assert tool.include_domains == ["example.com"]
        assert tool.exclude_domains == ["spam.com"]

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_get_web_search_tool_tavily_with_empty_config(self, mock_config):
        """Test Tavily tool uses defaults when config is empty."""
        mock_config.return_value = {"SEARCH_ENGINE": {}}
        tool = get_web_search_tool(max_search_results=10)
        assert tool.name == "web_search"
        assert tool.max_results == 10
        assert tool.include_answer is False
        assert tool.search_depth == "advanced"
        assert tool.include_raw_content is True
        assert tool.include_images is True
        assert tool.include_image_descriptions is True
        assert tool.include_domains == []
        assert tool.exclude_domains == []

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_get_web_search_tool_tavily_image_descriptions_disabled_when_images_disabled(
        self, mock_config
    ):
        """Test that include_image_descriptions is False when include_images is False."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_images": False,
                "include_image_descriptions": True,  # This should be ignored
            }
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_images is False
        assert tool.include_image_descriptions is False

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_get_web_search_tool_tavily_partial_config(self, mock_config):
        """Test Tavily tool with partial configuration."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_answer": True,
                "include_domains": ["trusted.com"],
            }
        }
        tool = get_web_search_tool(max_search_results=3)
        assert tool.include_answer is True
        assert tool.search_depth == "advanced"  # default
        assert tool.include_raw_content is True  # default
        assert tool.include_domains == ["trusted.com"]
        assert tool.exclude_domains == []  # default

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_get_web_search_tool_tavily_with_no_config_file(self, mock_config):
        """Test Tavily tool when config file doesn't exist."""
        mock_config.return_value = {}
        tool = get_web_search_tool(max_search_results=5)
        assert tool.name == "web_search"
        assert tool.max_results == 5
        assert tool.include_answer is False
        assert tool.search_depth == "advanced"
        assert tool.include_raw_content is True
        assert tool.include_images is True

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_get_web_search_tool_tavily_multiple_domains(self, mock_config):
        """Test Tavily tool with multiple domains in include/exclude lists."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_domains": ["example.com", "trusted.com", "gov.cn"],
                "exclude_domains": ["spam.com", "scam.org"],
            }
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_domains == ["example.com", "trusted.com", "gov.cn"]
        assert tool.exclude_domains == ["spam.com", "scam.org"]

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_no_search_engine_section(self, mock_config):
        """Test Tavily tool when SEARCH_ENGINE section doesn't exist in config."""
        mock_config.return_value = {"OTHER_CONFIG": {}}
        tool = get_web_search_tool(max_search_results=5)
        assert tool.name == "web_search"
        assert tool.max_results == 5
        assert tool.include_answer is False
        assert tool.search_depth == "advanced"
        assert tool.include_raw_content is True
        assert tool.include_images is True
        assert tool.include_domains == []
        assert tool.exclude_domains == []

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_completely_empty_config(self, mock_config):
        """Test Tavily tool with completely empty config."""
        mock_config.return_value = {}
        tool = get_web_search_tool(max_search_results=5)
        assert tool.name == "web_search"
        assert tool.max_results == 5
        assert tool.include_answer is False
        assert tool.search_depth == "advanced"
        assert tool.include_raw_content is True
        assert tool.include_images is True

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_only_include_answer_param(self, mock_config):
        """Test Tavily tool with only include_answer parameter specified."""
        mock_config.return_value = {"SEARCH_ENGINE": {"include_answer": True}}
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_answer is True
        assert tool.search_depth == "advanced"
        assert tool.include_raw_content is True
        assert tool.include_images is True

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_only_search_depth_param(self, mock_config):
        """Test Tavily tool with only search_depth parameter specified."""
        mock_config.return_value = {"SEARCH_ENGINE": {"search_depth": "basic"}}
        tool = get_web_search_tool(max_search_results=5)
        assert tool.search_depth == "basic"
        assert tool.include_answer is False
        assert tool.include_raw_content is True
        assert tool.include_images is True

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_only_include_domains_param(self, mock_config):
        """Test Tavily tool with only include_domains parameter specified."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {"include_domains": ["example.com"]}
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_domains == ["example.com"]
        assert tool.exclude_domains == []
        assert tool.include_answer is False
        assert tool.search_depth == "advanced"

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_explicit_false_boolean_values(self, mock_config):
        """Test that explicitly False boolean values are respected (not treated as missing)."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
            }
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_answer is False
        assert tool.include_raw_content is False
        assert tool.include_images is False
        assert tool.include_image_descriptions is False

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_with_empty_domain_lists(self, mock_config):
        """Test that empty domain lists are treated as optional."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_domains": [],
                "exclude_domains": [],
            }
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_domains == []
        assert tool.exclude_domains == []

    @patch("src.tools.search.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value)
    @patch("src.tools.search.load_yaml_config")
    def test_tavily_all_parameters_optional_mix(self, mock_config):
        """Test that any combination of optional parameters works."""
        mock_config.return_value = {
            "SEARCH_ENGINE": {
                "include_answer": True,
                "include_images": False,
                # Deliberately omit search_depth, include_raw_content, domains
            }
        }
        tool = get_web_search_tool(max_search_results=5)
        assert tool.include_answer is True
        assert tool.include_images is False
        assert (
            tool.include_image_descriptions is False
        )  # should be False since include_images is False
        assert tool.search_depth == "advanced"  # default
        assert tool.include_raw_content is True  # default
        assert tool.include_domains == []  # default
        assert tool.exclude_domains == []  # default

# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for PPT composer localization functionality.

These tests verify that the ppt_composer_node correctly passes locale information
to get_prompt_template, allowing for locale-specific prompt selection.
"""

import pytest


class MockLLMResponse:
    """Mock LLM response object."""
    
    def __init__(self, content: str = "Mock PPT content"):
        self.content = content


class MockLLM:
    """Mock LLM model with invoke method."""
    
    def invoke(self, messages):
        """Return a mock response."""
        return MockLLMResponse()


class TestPPTLocalization:
    """Test suite for PPT composer locale handling."""
    
    def test_locale_passed_to_prompt_template(self, monkeypatch):
        """
        Test that when locale is provided in state, it is passed to get_prompt_template.
        
        This test verifies that ppt_composer_node correctly extracts the locale
        from the state dict and passes it to get_prompt_template.
        """
        # Track calls to get_prompt_template
        captured_calls = []
        
        def mock_get_prompt_template(prompt_name, locale="en-US"):
            """Capture the arguments passed to get_prompt_template."""
            captured_calls.append({"prompt_name": prompt_name, "locale": locale})
            return "Mock prompt template"
        
        def mock_get_llm_by_type(llm_type):
            """Return a mock LLM."""
            return MockLLM()
        
        # Import here to ensure monkeypatching happens before module import
        import src.ppt.graph.ppt_composer_node as ppt_module
        
        # Monkeypatch the functions
        monkeypatch.setattr(
            ppt_module,
            "get_prompt_template",
            mock_get_prompt_template
        )
        monkeypatch.setattr(
            ppt_module,
            "get_llm_by_type",
            mock_get_llm_by_type
        )
        
        # Create state with input and locale
        state = {
            "input": "hello",
            "locale": "zh-CN"
        }
        
        # Call the ppt_composer_node
        result = ppt_module.ppt_composer_node(state)
        
        # Verify get_prompt_template was called with the correct locale
        assert len(captured_calls) == 1, "get_prompt_template should be called once"
        assert captured_calls[0]["prompt_name"] == "ppt/ppt_composer"
        assert captured_calls[0]["locale"] == "zh-CN", \
            "get_prompt_template should be called with locale 'zh-CN'"
        
        # Verify result structure
        assert "ppt_content" in result
        assert "ppt_file_path" in result
    
    def test_default_locale_fallback(self, monkeypatch):
        """
        Test that when locale is missing from state, default locale 'en-US' is used.
        
        This test verifies that ppt_composer_node falls back to the default locale
        'en-US' when no locale is provided in the state dict.
        """
        # Track calls to get_prompt_template
        captured_calls = []
        
        def mock_get_prompt_template(prompt_name, locale="en-US"):
            """Capture the arguments passed to get_prompt_template."""
            captured_calls.append({"prompt_name": prompt_name, "locale": locale})
            return "Mock prompt template"
        
        def mock_get_llm_by_type(llm_type):
            """Return a mock LLM."""
            return MockLLM()
        
        # Import here to ensure monkeypatching happens before module import
        import src.ppt.graph.ppt_composer_node as ppt_module
        
        # Monkeypatch the functions
        monkeypatch.setattr(
            ppt_module,
            "get_prompt_template",
            mock_get_prompt_template
        )
        monkeypatch.setattr(
            ppt_module,
            "get_llm_by_type",
            mock_get_llm_by_type
        )
        
        # Create state without locale (only input)
        state = {
            "input": "hello"
        }
        
        # Call the ppt_composer_node
        result = ppt_module.ppt_composer_node(state)
        
        # Verify get_prompt_template was called with the default locale
        assert len(captured_calls) == 1, "get_prompt_template should be called once"
        assert captured_calls[0]["prompt_name"] == "ppt/ppt_composer"
        assert captured_calls[0]["locale"] == "en-US", \
            "get_prompt_template should be called with default locale 'en-US'"
        
        # Verify result structure
        assert "ppt_content" in result
        assert "ppt_file_path" in result

# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock
from langchain.schema import HumanMessage, SystemMessage

from src.prompt_enhancer.graph.enhancer_node import prompt_enhancer_node
from src.prompt_enhancer.graph.state import PromptEnhancerState
from src.config.report_style import ReportStyle


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a test response."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="Enhanced test prompt")
    return llm


@pytest.fixture
def mock_messages():
    """Mock messages returned by apply_prompt_template."""
    return [
        SystemMessage(content="System prompt template"),
        HumanMessage(content="Test human message"),
    ]


class TestPromptEnhancerNode:
    """Test cases for prompt_enhancer_node function."""

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_basic_prompt_enhancement(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test basic prompt enhancement without context or report style."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(prompt="Write about AI")

        result = prompt_enhancer_node(state)

        # Verify LLM was called
        mock_get_llm.assert_called_once_with("basic")
        mock_llm.invoke.assert_called_once_with(mock_messages)

        # Verify apply_prompt_template was called correctly
        mock_apply_template.assert_called_once()
        call_args = mock_apply_template.call_args
        assert call_args[0][0] == "prompt_enhancer/prompt_enhancer"
        assert "messages" in call_args[0][1]
        assert "report_style" in call_args[0][1]

        # Verify result
        assert result == {"output": "Enhanced test prompt"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_prompt_enhancement_with_report_style(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test prompt enhancement with report style."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(
            prompt="Write about AI", report_style=ReportStyle.ACADEMIC
        )

        result = prompt_enhancer_node(state)

        # Verify apply_prompt_template was called with report_style
        mock_apply_template.assert_called_once()
        call_args = mock_apply_template.call_args
        assert call_args[0][0] == "prompt_enhancer/prompt_enhancer"
        assert call_args[0][1]["report_style"] == ReportStyle.ACADEMIC

        # Verify result
        assert result == {"output": "Enhanced test prompt"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_prompt_enhancement_with_context(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test prompt enhancement with additional context."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(
            prompt="Write about AI", context="Focus on machine learning applications"
        )

        result = prompt_enhancer_node(state)

        # Verify apply_prompt_template was called
        mock_apply_template.assert_called_once()
        call_args = mock_apply_template.call_args

        # Check that the context was included in the human message
        messages_arg = call_args[0][1]["messages"]
        assert len(messages_arg) == 1
        human_message = messages_arg[0]
        assert isinstance(human_message, HumanMessage)
        assert "Focus on machine learning applications" in human_message.content

        assert result == {"output": "Enhanced test prompt"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_error_handling(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test error handling when LLM call fails."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        # Mock LLM to raise an exception
        mock_llm.invoke.side_effect = Exception("LLM error")

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        # Should return original prompt on error
        assert result == {"output": "Test prompt"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_template_error_handling(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test error handling when template application fails."""
        mock_get_llm.return_value = mock_llm

        # Mock apply_prompt_template to raise an exception
        mock_apply_template.side_effect = Exception("Template error")

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        # Should return original prompt on error
        assert result == {"output": "Test prompt"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_prefix_removal(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test that common prefixes are removed from LLM response."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        # Test different prefixes that should be removed
        test_cases = [
            "Enhanced Prompt: This is the enhanced prompt",
            "Enhanced prompt: This is the enhanced prompt",
            "Here's the enhanced prompt: This is the enhanced prompt",
            "Here is the enhanced prompt: This is the enhanced prompt",
            "**Enhanced Prompt**: This is the enhanced prompt",
            "**Enhanced prompt**: This is the enhanced prompt",
        ]

        for response_with_prefix in test_cases:
            mock_llm.invoke.return_value = MagicMock(content=response_with_prefix)

            state = PromptEnhancerState(prompt="Test prompt")
            result = prompt_enhancer_node(state)

            assert result == {"output": "This is the enhanced prompt"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_whitespace_handling(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test that whitespace is properly stripped from LLM response."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        # Mock LLM response with extra whitespace
        mock_llm.invoke.return_value = MagicMock(
            content="  \n\n  Enhanced prompt  \n\n  "
        )

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        assert result == {"output": "Enhanced prompt"}

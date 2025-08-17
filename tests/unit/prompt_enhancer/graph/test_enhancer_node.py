# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock, patch

import pytest
from langchain.schema import HumanMessage, SystemMessage

from src.config.report_style import ReportStyle
from src.prompt_enhancer.graph.enhancer_node import prompt_enhancer_node
from src.prompt_enhancer.graph.state import PromptEnhancerState


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a test response."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content="""Thoughts: LLM thinks a lot
<enhanced_prompt>
Enhanced test prompt
</enhanced_prompt>
"""
    )
    return llm


@pytest.fixture
def mock_llm_xml_with_whitespace():
    """Mock LLM that returns XML response with extra whitespace."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content="""
Some thoughts here...

<enhanced_prompt>

  Enhanced prompt with whitespace

</enhanced_prompt>

Additional content after XML
"""
    )
    return llm


@pytest.fixture
def mock_llm_xml_multiline():
    """Mock LLM that returns XML response with multiline content."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content="""
<enhanced_prompt>
This is a multiline enhanced prompt
that spans multiple lines
and includes various formatting.

It should preserve the structure.
</enhanced_prompt>
"""
    )
    return llm


@pytest.fixture
def mock_llm_no_xml():
    """Mock LLM that returns response without XML tags."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content="Enhanced Prompt: This is an enhanced prompt without XML tags"
    )
    return llm


@pytest.fixture
def mock_llm_malformed_xml():
    """Mock LLM that returns response with malformed XML."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content="""
<enhanced_prompt>
This XML tag is not properly closed
<enhanced_prompt>
"""
    )
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

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_xml_with_whitespace_handling(
        self,
        mock_get_llm,
        mock_apply_template,
        mock_llm_xml_with_whitespace,
        mock_messages,
    ):
        """Test XML extraction with extra whitespace inside tags."""
        mock_get_llm.return_value = mock_llm_xml_with_whitespace
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        assert result == {"output": "Enhanced prompt with whitespace"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_xml_multiline_content(
        self, mock_get_llm, mock_apply_template, mock_llm_xml_multiline, mock_messages
    ):
        """Test XML extraction with multiline content."""
        mock_get_llm.return_value = mock_llm_xml_multiline
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        expected_output = """This is a multiline enhanced prompt
that spans multiple lines
and includes various formatting.

It should preserve the structure."""
        assert result == {"output": expected_output}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_fallback_to_prefix_removal(
        self, mock_get_llm, mock_apply_template, mock_llm_no_xml, mock_messages
    ):
        """Test fallback to prefix removal when no XML tags are found."""
        mock_get_llm.return_value = mock_llm_no_xml
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        assert result == {"output": "This is an enhanced prompt without XML tags"}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_malformed_xml_fallback(
        self, mock_get_llm, mock_apply_template, mock_llm_malformed_xml, mock_messages
    ):
        """Test handling of malformed XML tags."""
        mock_get_llm.return_value = mock_llm_malformed_xml
        mock_apply_template.return_value = mock_messages

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        # Should fall back to using the entire content since XML is malformed
        expected_content = """<enhanced_prompt>
This XML tag is not properly closed
<enhanced_prompt>"""
        assert result == {"output": expected_content}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_case_sensitive_prefix_removal(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test that prefix removal is case-sensitive."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        # Test case variations that should NOT be removed
        test_cases = [
            "ENHANCED PROMPT: This should not be removed",
            "enhanced prompt: This should not be removed",
            "Enhanced Prompt This should not be removed",  # Missing colon
            "Enhanced Prompt :: This should not be removed",  # Double colon
        ]

        for response_content in test_cases:
            mock_llm.invoke.return_value = MagicMock(content=response_content)

            state = PromptEnhancerState(prompt="Test prompt")
            result = prompt_enhancer_node(state)

            # Should return the full content since prefix doesn't match exactly
            assert result == {"output": response_content}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_prefix_with_extra_whitespace(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test prefix removal with extra whitespace after colon."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        test_cases = [
            ("Enhanced Prompt:   This has extra spaces", "This has extra spaces"),
            ("Enhanced prompt:\t\tThis has tabs", "This has tabs"),
            ("Here's the enhanced prompt:\n\nThis has newlines", "This has newlines"),
        ]

        for response_content, expected_output in test_cases:
            mock_llm.invoke.return_value = MagicMock(content=response_content)

            state = PromptEnhancerState(prompt="Test prompt")
            result = prompt_enhancer_node(state)

            assert result == {"output": expected_output}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_xml_with_special_characters(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test XML extraction with special characters and symbols."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        special_content = """<enhanced_prompt>
Enhanced prompt with special chars: @#$%^&*()
Unicode: 🚀 ✨ 💡
Quotes: "double" and 'single'
Backslashes: \\n \\t \\r
</enhanced_prompt>"""

        mock_llm.invoke.return_value = MagicMock(content=special_content)

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        expected_output = """Enhanced prompt with special chars: @#$%^&*()
Unicode: 🚀 ✨ 💡
Quotes: "double" and 'single'
Backslashes: \\n \\t \\r"""
        assert result == {"output": expected_output}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_very_long_response(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test handling of very long LLM responses."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        # Create a very long response
        long_content = "This is a very long enhanced prompt. " * 100
        xml_response = f"<enhanced_prompt>\n{long_content}\n</enhanced_prompt>"

        mock_llm.invoke.return_value = MagicMock(content=xml_response)

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        assert result == {"output": long_content.strip()}
        assert len(result["output"]) > 1000  # Verify it's actually long

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_empty_response_content(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test handling of empty response content."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        mock_llm.invoke.return_value = MagicMock(content="")

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        assert result == {"output": ""}

    @patch("src.prompt_enhancer.graph.enhancer_node.apply_prompt_template")
    @patch("src.prompt_enhancer.graph.enhancer_node.get_llm_by_type")
    @patch(
        "src.prompt_enhancer.graph.enhancer_node.AGENT_LLM_MAP",
        {"prompt_enhancer": "basic"},
    )
    def test_only_whitespace_response(
        self, mock_get_llm, mock_apply_template, mock_llm, mock_messages
    ):
        """Test handling of response with only whitespace."""
        mock_get_llm.return_value = mock_llm
        mock_apply_template.return_value = mock_messages

        mock_llm.invoke.return_value = MagicMock(content="   \n\n\t\t   ")

        state = PromptEnhancerState(prompt="Test prompt")
        result = prompt_enhancer_node(state)

        assert result == {"output": ""}

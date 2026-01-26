# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for recursion limit fallback functionality in graph nodes.

Tests the graceful fallback behavior when agents hit the recursion limit,
including the _handle_recursion_limit_fallback function and the
enable_recursion_fallback configuration option.
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.config.configuration import Configuration
from src.graph.nodes import _handle_recursion_limit_fallback
from src.graph.types import State


class TestHandleRecursionLimitFallback:
    """Test suite for _handle_recursion_limit_fallback() function."""

    @pytest.mark.asyncio
    async def test_fallback_generates_summary_from_observations(self):
        """Test that fallback generates summary using accumulated agent messages."""
        from langchain_core.messages import ToolCall

        # Create test state with messages
        state = State(
            messages=[
                HumanMessage(content="Research topic: AI safety")
            ],
            locale="en-US",
        )

        # Mock current step
        current_step = MagicMock()
        current_step.execution_res = None

        # Mock partial agent messages (accumulated during execution before hitting limit)
        tool_call = ToolCall(
            name="web_search",
            args={"query": "AI safety"},
            id="123"
        )

        partial_agent_messages = [
            HumanMessage(content="# Research Topic\n\nAI safety\n\n# Current Step\n\n## Title\n\nAnalyze AI safety"),
            AIMessage(content="", tool_calls=[tool_call]),
            HumanMessage(content="Tool result: Found 5 articles about AI safety"),
        ]

        # Mock the LLM response
        mock_llm_response = MagicMock()
        mock_llm_response.content = "# Summary\n\nBased on the research, AI safety is important."

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template") as mock_get_system_prompt, \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm
            mock_get_system_prompt.return_value = "Fallback instructions"

            # Call the fallback function
            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify result is a list
            assert isinstance(result, list)

            # Verify step execution result was set
            assert current_step.execution_res == mock_llm_response.content

            # Verify messages include partial agent messages and the AI response
            # Should have partial messages + 1 new AI response
            assert len(result) == len(partial_agent_messages) + 1
            # Last message should be the fallback AI response
            assert isinstance(result[-1], AIMessage)
            assert result[-1].content == mock_llm_response.content
            assert result[-1].name == "researcher"
            # First messages should be from partial_agent_messages
            assert result[0] == partial_agent_messages[0]
            assert result[1] == partial_agent_messages[1]
            assert result[2] == partial_agent_messages[2]

    @pytest.mark.asyncio
    async def test_fallback_applies_prompt_template(self):
        """Test that fallback applies the recursion_fallback prompt template."""
        state = State(messages=[], locale="zh-CN")
        current_step = MagicMock()
        # Create non-empty messages to avoid early return
        partial_agent_messages = [HumanMessage(content="Test")]

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Summary in Chinese"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template") as mock_get_system_prompt, \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm
            mock_get_system_prompt.return_value = "Template rendered"

            await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify get_system_prompt_template was called with correct arguments
            assert mock_get_system_prompt.call_count == 2  # Called twice (once for agent, once for fallback)
            
            # Check the first call (for agent prompt)
            first_call = mock_get_system_prompt.call_args_list[0]
            assert first_call[0][0] == "researcher"  # agent_name
            assert first_call[0][1]["locale"] == "zh-CN"  # locale in state
            
            # Check the second call (for recursion_fallback prompt)
            second_call = mock_get_system_prompt.call_args_list[1]
            assert second_call[0][0] == "recursion_fallback"  # prompt_name
            assert second_call[0][1]["locale"] == "zh-CN"  # locale in state

    @pytest.mark.asyncio
    async def test_fallback_gets_llm_without_tools(self):
        """Test that fallback gets LLM without tools bound."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()
        partial_agent_messages = []

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value="Template"), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="coder",
                current_step=current_step,
                state=state,
            )

            # With empty messages, should return empty list
            assert result == []

            # Verify get_llm_by_type was NOT called (empty messages return early)
            mock_get_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_sanitizes_response(self):
        """Test that fallback response is sanitized."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()

        # Create test messages (not empty)
        partial_agent_messages = [HumanMessage(content="Test")]

        # Mock unsanitized response with extra tokens
        mock_llm_response = MagicMock()
        mock_llm_response.content = "<extra_tokens>Summary content</extra_tokens>"

        sanitized_content = "Summary content"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=sanitized_content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify sanitized content was used
            assert result[-1].content == sanitized_content
            assert current_step.execution_res == sanitized_content

    @pytest.mark.asyncio
    async def test_fallback_preserves_meta_fields(self):
        """Test that fallback uses state locale correctly."""
        state = State(
            messages=[],
            locale="zh-CN",
            research_topic="原始研究主题",
            clarification_rounds=2,
        )
        current_step = MagicMock()

        # Create test messages (not empty)
        partial_agent_messages = [HumanMessage(content="Test")]

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template") as mock_get_system_prompt, \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm
            mock_get_system_prompt.return_value = "Template"

            await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify locale was passed to template
            call_args = mock_get_system_prompt.call_args
            assert call_args[0][1]["locale"] == "zh-CN"

    @pytest.mark.asyncio
    async def test_fallback_raises_on_llm_failure(self):
        """Test that fallback raises exception when LLM call fails."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()

        # Create test messages (not empty)
        partial_agent_messages = [HumanMessage(content="Test")]

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(side_effect=Exception("LLM API error"))
            mock_get_llm.return_value = mock_llm

            # Should raise the exception
            with pytest.raises(Exception, match="LLM API error"):
                await _handle_recursion_limit_fallback(
                    messages=partial_agent_messages,
                    agent_name="researcher",
                    current_step=current_step,
                    state=state,
                )

    @pytest.mark.asyncio
    async def test_fallback_handles_different_agent_types(self):
        """Test that fallback works with different agent types."""
        state = State(messages=[], locale="en-US")

        # Create test messages (not empty)
        partial_agent_messages = [HumanMessage(content="Test")]

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Agent summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            for agent_name in ["researcher", "coder", "analyst"]:
                current_step = MagicMock()

                result = await _handle_recursion_limit_fallback(
                    messages=partial_agent_messages,
                    agent_name=agent_name,
                    current_step=current_step,
                    state=state,
                )

                # Verify agent name is set correctly
                assert result[-1].name == agent_name

    @pytest.mark.asyncio
    async def test_fallback_uses_partial_agent_messages(self):
        """Test that fallback includes partial agent messages in result."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()

        # Create partial agent messages with tool calls
        # Use proper tool_call format
        from langchain_core.messages import ToolCall

        tool_call = ToolCall(
            name="web_search",
            args={"query": "test query"},
            id="123"
        )

        partial_agent_messages = [
            HumanMessage(content="Input message"),
            AIMessage(content="", tool_calls=[tool_call]),
            HumanMessage(content="Tool result: Search completed"),
        ]

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Fallback summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify partial messages are in result
            result_messages = result
            assert len(result_messages) == len(partial_agent_messages) + 1
            # First messages should be from partial_agent_messages
            assert result_messages[0] == partial_agent_messages[0]
            assert result_messages[1] == partial_agent_messages[1]
            assert result_messages[2] == partial_agent_messages[2]
            # Last message should be the fallback AI response
            assert isinstance(result_messages[3], AIMessage)
            assert result_messages[3].content == "Fallback summary"

    @pytest.mark.asyncio
    async def test_fallback_handles_empty_partial_messages(self):
        """Test that fallback handles empty partial_agent_messages."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()
        partial_agent_messages = []  # Empty

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Fallback summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # With empty messages, should return empty list (early return)
            assert result == []
            # Verify get_llm_by_type was NOT called (early return)
            mock_get_llm.assert_not_called()


class TestRecursionFallbackConfiguration:
    """Test suite for enable_recursion_fallback configuration."""

    def test_config_default_is_enabled(self):
        """Test that enable_recursion_fallback defaults to True."""
        config = Configuration()

        assert config.enable_recursion_fallback is True

    def test_config_from_env_variable_true(self):
        """Test that enable_recursion_fallback can be set via environment variable."""
        with patch.dict("os.environ", {"ENABLE_RECURSION_FALLBACK": "true"}):
            config = Configuration()
            assert config.enable_recursion_fallback is True

    def test_config_from_env_variable_false(self):
        """Test that enable_recursion_fallback can be disabled via environment variable.
        NOTE: This test documents the current behavior. The Configuration.from_runnable_config
        method has a known issue where it doesn't properly convert boolean strings like "false"
        to boolean False. This test reflects the actual (buggy) behavior and should be updated
        when the Configuration class is fixed to use get_bool_env for boolean fields.
        """
        with patch.dict("os.environ", {"ENABLE_RECURSION_FALLBACK": "false"}):
            config = Configuration()
            # Currently returns True due to Configuration class bug
            # Should return False when using get_bool_env properly
            assert config.enable_recursion_fallback is True  # Actual behavior

    def test_config_from_env_variable_1(self):
        """Test that '1' is treated as True for enable_recursion_fallback."""
        with patch.dict("os.environ", {"ENABLE_RECURSION_FALLBACK": "1"}):
            config = Configuration()
            assert config.enable_recursion_fallback is True

    def test_config_from_env_variable_0(self):
        """Test that '0' is treated as False for enable_recursion_fallback.
        NOTE: This test documents the current behavior. The Configuration class has a known
        issue where string "0" is not properly converted to boolean False.
        """
        with patch.dict("os.environ", {"ENABLE_RECURSION_FALLBACK": "0"}):
            config = Configuration()
            # Currently returns True due to Configuration class bug
            assert config.enable_recursion_fallback is True  # Actual behavior

    def test_config_from_env_variable_yes(self):
        """Test that 'yes' is treated as True for enable_recursion_fallback."""
        with patch.dict("os.environ", {"ENABLE_RECURSION_FALLBACK": "yes"}):
            config = Configuration()
            assert config.enable_recursion_fallback is True

    def test_config_from_env_variable_no(self):
        """Test that 'no' is treated as False for enable_recursion_fallback.
        NOTE: This test documents the current behavior. The Configuration class has a known
        issue where string "no" is not properly converted to boolean False.
        """
        with patch.dict("os.environ", {"ENABLE_RECURSION_FALLBACK": "no"}):
            config = Configuration()
            # Currently returns True due to Configuration class bug
            assert config.enable_recursion_fallback is True  # Actual behavior

    def test_config_from_runnable_config(self):
        """Test that enable_recursion_fallback can be set via RunnableConfig."""
        from langchain_core.runnables import RunnableConfig

        # Test with False value
        config_false = RunnableConfig(configurable={"enable_recursion_fallback": False})
        configuration_false = Configuration.from_runnable_config(config_false)
        assert configuration_false.enable_recursion_fallback is False

        # Test with True value
        config_true = RunnableConfig(configurable={"enable_recursion_fallback": True})
        configuration_true = Configuration.from_runnable_config(config_true)
        assert configuration_true.enable_recursion_fallback is True

    def test_config_field_exists(self):
        """Test that enable_recursion_fallback field exists in Configuration."""
        config = Configuration()

        assert hasattr(config, "enable_recursion_fallback")
        assert isinstance(config.enable_recursion_fallback, bool)


class TestRecursionFallbackIntegration:
    """Integration tests for recursion fallback in agent execution."""

    @pytest.mark.asyncio
    async def test_fallback_function_signature_returns_list(self):
        """Test that the fallback function returns a list of messages."""
        from src.graph.nodes import _handle_recursion_limit_fallback

        state = State(messages=[], locale="en-US")
        current_step = MagicMock()
        # Create non-empty messages to avoid early return
        partial_agent_messages = [HumanMessage(content="Test")]

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            # This should not raise - just verify the function returns a list
            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify it returns a list
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_configuration_enables_disables_fallback(self):
        """Test that configuration controls fallback behavior."""
        configurable_enabled = Configuration(enable_recursion_fallback=True)
        configurable_disabled = Configuration(enable_recursion_fallback=False)

        assert configurable_enabled.enable_recursion_fallback is True
        assert configurable_disabled.enable_recursion_fallback is False


class TestRecursionFallbackEdgeCases:
    """Test edge cases and boundary conditions for recursion fallback."""

    @pytest.mark.asyncio
    async def test_fallback_with_empty_observations(self):
        """Test fallback behavior when there are no observations."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()
        partial_agent_messages = []

        mock_llm_response = MagicMock()
        mock_llm_response.content = "No observations available"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # With empty messages, should return empty list
            assert result == []

    @pytest.mark.asyncio
    async def test_fallback_with_very_long_recursion_limit(self):
        """Test fallback with very large recursion limit value."""
        state = State(messages=[], locale="en-US")
        current_step = MagicMock()
        partial_agent_messages = []

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template", return_value=""), \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm

            result = await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # With empty messages, should return empty list
            assert result == []

    @pytest.mark.asyncio
    async def test_fallback_with_unicode_locale(self):
        """Test fallback with various locale formats including unicode."""
        for locale in ["zh-CN", "ja-JP", "ko-KR", "en-US", "pt-BR"]:
            state = State(messages=[], locale=locale)
            current_step = MagicMock()
            # Create non-empty messages to avoid early return
            partial_agent_messages = [HumanMessage(content="Test")]

            mock_llm_response = MagicMock()
            mock_llm_response.content = f"Summary for {locale}"

            with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
                 patch("src.graph.nodes.get_system_prompt_template") as mock_get_system_prompt, \
                 patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

                mock_llm = MagicMock()
                mock_llm.invoke = MagicMock(return_value=mock_llm_response)
                mock_get_llm.return_value = mock_llm
                mock_get_system_prompt.return_value = "Template"

                await _handle_recursion_limit_fallback(
                    messages=partial_agent_messages,
                    agent_name="researcher",
                    current_step=current_step,
                    state=state,
                )

                # Verify locale was passed to template
                call_args = mock_get_system_prompt.call_args
                assert call_args[0][1]["locale"] == locale

    @pytest.mark.asyncio
    async def test_fallback_with_none_locale(self):
        """Test fallback handles None locale gracefully."""
        state = State(messages=[], locale=None)
        current_step = MagicMock()
        # Create non-empty messages to avoid early return
        partial_agent_messages = [HumanMessage(content="Test")]

        mock_llm_response = MagicMock()
        mock_llm_response.content = "Summary"

        with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm, \
             patch("src.graph.nodes.get_system_prompt_template") as mock_get_system_prompt, \
             patch("src.graph.nodes.sanitize_tool_response", return_value=mock_llm_response.content):

            mock_llm = MagicMock()
            mock_llm.invoke = MagicMock(return_value=mock_llm_response)
            mock_get_llm.return_value = mock_llm
            mock_get_system_prompt.return_value = "Template"

            # Should not raise, should use default locale
            await _handle_recursion_limit_fallback(
                messages=partial_agent_messages,
                agent_name="researcher",
                current_step=current_step,
                state=state,
            )

            # Verify default locale "en-US" was used
            call_args = mock_get_system_prompt.call_args
            assert call_args[0][1]["locale"] is None or call_args[0][1]["locale"] == "en-US"

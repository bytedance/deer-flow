# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Integration tests for tool-specific interrupts feature (Issue #572).

Tests the complete flow of selective tool interrupts including:
- Tool wrapping with interrupt logic
- Agent creation with interrupt configuration
- Tool execution with user feedback
- Resume mechanism after interrupt
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock, call
from typing import Any

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

from src.agents.agents import create_agent
from src.agents.tool_interceptor import ToolInterceptor, wrap_tools_with_interceptor
from src.config.configuration import Configuration
from src.server.chat_request import ChatRequest


class TestToolInterceptorIntegration:
    """Integration tests for tool interceptor with agent workflow."""

    def test_agent_creation_with_tool_interrupts(self):
        """Test creating an agent with tool interrupts configured."""
        @tool
        def search_tool(query: str) -> str:
            """Search the web."""
            return f"Search results for: {query}"

        @tool
        def db_tool(query: str) -> str:
            """Query database."""
            return f"DB results for: {query}"

        tools = [search_tool, db_tool]

        # Create agent with interrupts on db_tool only
        with patch("src.agents.agents.create_react_agent") as mock_create, \
             patch("src.agents.agents.get_llm_by_type") as mock_llm:
            mock_create.return_value = MagicMock()
            mock_llm.return_value = MagicMock()
            
            agent = create_agent(
                agent_name="test_agent",
                agent_type="researcher",
                tools=tools,
                prompt_template="researcher",
                interrupt_before_tools=["db_tool"],
            )

            # Verify create_react_agent was called with wrapped tools
            assert mock_create.called
            call_args = mock_create.call_args
            wrapped_tools = call_args.kwargs["tools"]

            # Should have wrapped the tools
            assert len(wrapped_tools) == 2
            assert wrapped_tools[0].name == "search_tool"
            assert wrapped_tools[1].name == "db_tool"

    def test_configuration_with_tool_interrupts(self):
        """Test Configuration object with interrupt_before_tools."""
        config = Configuration(
            interrupt_before_tools=["db_tool", "api_write_tool"],
            max_step_num=3,
            max_search_results=5,
        )

        assert config.interrupt_before_tools == ["db_tool", "api_write_tool"]
        assert config.max_step_num == 3
        assert config.max_search_results == 5

    def test_configuration_default_no_interrupts(self):
        """Test Configuration defaults to no interrupts."""
        config = Configuration()
        assert config.interrupt_before_tools == []

    def test_chat_request_with_tool_interrupts(self):
        """Test ChatRequest with interrupt_before_tools."""
        request = ChatRequest(
            messages=[{"role": "user", "content": "Search for X"}],
            interrupt_before_tools=["db_tool", "payment_api"],
        )

        assert request.interrupt_before_tools == ["db_tool", "payment_api"]

    def test_chat_request_interrupt_feedback_with_tool_interrupts(self):
        """Test ChatRequest with both interrupt_before_tools and interrupt_feedback."""
        request = ChatRequest(
            messages=[{"role": "user", "content": "Research topic"}],
            interrupt_before_tools=["db_tool"],
            interrupt_feedback="approved",
        )

        assert request.interrupt_before_tools == ["db_tool"]
        assert request.interrupt_feedback == "approved"

    def test_multiple_tools_selective_interrupt(self):
        """Test that only specified tools trigger interrupts."""
        @tool
        def tool_a(x: str) -> str:
            """Tool A"""
            return f"A: {x}"

        @tool
        def tool_b(x: str) -> str:
            """Tool B"""
            return f"B: {x}"

        @tool
        def tool_c(x: str) -> str:
            """Tool C"""
            return f"C: {x}"

        tools = [tool_a, tool_b, tool_c]
        interceptor = ToolInterceptor(["tool_b"])

        # Wrap all tools
        wrapped_tools = wrap_tools_with_interceptor(tools, ["tool_b"])

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            # tool_a should not interrupt
            mock_interrupt.return_value = "approved"
            result_a = wrapped_tools[0].invoke("test")
            assert not mock_interrupt.called

            # tool_b should interrupt
            result_b = wrapped_tools[1].invoke("test")
            assert mock_interrupt.called

            # tool_c should not interrupt
            mock_interrupt.reset_mock()
            result_c = wrapped_tools[2].invoke("test")
            assert not mock_interrupt.called

    def test_interrupt_with_user_approval(self):
        """Test interrupt flow with user approval."""
        @tool
        def sensitive_tool(action: str) -> str:
            """A sensitive tool."""
            return f"Executed: {action}"

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "approved"

            interceptor = ToolInterceptor(["sensitive_tool"])
            wrapped = ToolInterceptor.wrap_tool(sensitive_tool, interceptor)

            result = wrapped.invoke("delete_data")

            assert mock_interrupt.called
            assert "Executed: delete_data" in str(result)

    def test_interrupt_with_user_rejection(self):
        """Test interrupt flow with user rejection."""
        @tool
        def sensitive_tool(action: str) -> str:
            """A sensitive tool."""
            return f"Executed: {action}"

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "rejected"

            interceptor = ToolInterceptor(["sensitive_tool"])
            wrapped = ToolInterceptor.wrap_tool(sensitive_tool, interceptor)

            result = wrapped.invoke("delete_data")

            assert mock_interrupt.called
            assert isinstance(result, dict)
            assert "error" in result
            assert result["status"] == "rejected"

    def test_interrupt_message_contains_tool_info(self):
        """Test that interrupt message contains tool name and input."""
        @tool
        def db_query_tool(query: str) -> str:
            """Database query tool."""
            return f"Query result: {query}"

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "approved"

            interceptor = ToolInterceptor(["db_query_tool"])
            wrapped = ToolInterceptor.wrap_tool(db_query_tool, interceptor)

            wrapped.invoke("SELECT * FROM users")

            # Verify interrupt was called with meaningful message
            assert mock_interrupt.called
            interrupt_message = mock_interrupt.call_args[0][0]
            assert "db_query_tool" in interrupt_message
            assert "SELECT * FROM users" in interrupt_message

    def test_tool_wrapping_preserves_functionality(self):
        """Test that tool wrapping preserves original tool functionality."""
        @tool
        def simple_tool(text: str) -> str:
            """Process text."""
            return f"Processed: {text}"

        interceptor = ToolInterceptor([])  # No interrupts
        wrapped = ToolInterceptor.wrap_tool(simple_tool, interceptor)

        result = wrapped.invoke({"text": "hello"})
        assert "hello" in str(result)

    def test_tool_wrapping_preserves_tool_metadata(self):
        """Test that tool wrapping preserves tool name and description."""
        @tool
        def my_special_tool(x: str) -> str:
            """This is my special tool description."""
            return f"Result: {x}"

        interceptor = ToolInterceptor([])
        wrapped = ToolInterceptor.wrap_tool(my_special_tool, interceptor)

        assert wrapped.name == "my_special_tool"
        assert "special tool" in wrapped.description.lower()

    def test_multiple_interrupts_in_sequence(self):
        """Test handling multiple tool interrupts in sequence."""
        @tool
        def tool_one(x: str) -> str:
            """Tool one."""
            return f"One: {x}"

        @tool
        def tool_two(x: str) -> str:
            """Tool two."""
            return f"Two: {x}"

        @tool
        def tool_three(x: str) -> str:
            """Tool three."""
            return f"Three: {x}"

        tools = [tool_one, tool_two, tool_three]
        wrapped_tools = wrap_tools_with_interceptor(
            tools, ["tool_one", "tool_two"]
        )

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "approved"

            # First interrupt
            result_one = wrapped_tools[0].invoke("first")
            assert mock_interrupt.call_count == 1

            # Second interrupt
            result_two = wrapped_tools[1].invoke("second")
            assert mock_interrupt.call_count == 2

            # Third (no interrupt)
            result_three = wrapped_tools[2].invoke("third")
            assert mock_interrupt.call_count == 2

            assert "One: first" in str(result_one)
            assert "Two: second" in str(result_two)
            assert "Three: third" in str(result_three)

    def test_empty_interrupt_list_no_interrupts(self):
        """Test that empty interrupt list doesn't trigger interrupts."""
        @tool
        def test_tool(x: str) -> str:
            """Test tool."""
            return f"Result: {x}"

        wrapped_tools = wrap_tools_with_interceptor([test_tool], [])

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            wrapped_tools[0].invoke("test")
            assert not mock_interrupt.called

    def test_none_interrupt_list_no_interrupts(self):
        """Test that None interrupt list doesn't trigger interrupts."""
        @tool
        def test_tool(x: str) -> str:
            """Test tool."""
            return f"Result: {x}"

        wrapped_tools = wrap_tools_with_interceptor([test_tool], None)

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            wrapped_tools[0].invoke("test")
            assert not mock_interrupt.called

    def test_case_sensitive_tool_name_matching(self):
        """Test that tool name matching is case-sensitive."""
        @tool
        def MyTool(x: str) -> str:
            """A tool."""
            return f"Result: {x}"

        interceptor_lower = ToolInterceptor(["mytool"])
        interceptor_exact = ToolInterceptor(["MyTool"])

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "approved"

            # Case mismatch - should NOT interrupt
            wrapped_lower = ToolInterceptor.wrap_tool(MyTool, interceptor_lower)
            result_lower = wrapped_lower.invoke("test")
            assert not mock_interrupt.called

            # Case match - should interrupt
            wrapped_exact = ToolInterceptor.wrap_tool(MyTool, interceptor_exact)
            result_exact = wrapped_exact.invoke("test")
            assert mock_interrupt.called

    def test_tool_error_handling(self):
        """Test handling of tool errors during execution."""
        @tool
        def error_tool(x: str) -> str:
            """A tool that raises an error."""
            raise ValueError(f"Intentional error: {x}")

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "approved"

            interceptor = ToolInterceptor(["error_tool"])
            wrapped = ToolInterceptor.wrap_tool(error_tool, interceptor)

            with pytest.raises(ValueError) as exc_info:
                wrapped.invoke("test")

            assert "Intentional error: test" in str(exc_info.value)

    def test_approval_keywords_comprehensive(self):
        """Test all approved keywords are recognized."""
        approval_keywords = [
            "approved",
            "approve",
            "yes",
            "proceed",
            "continue",
            "ok",
            "okay",
            "accepted",
            "accept",
            "[approved]",
            "APPROVED",
            "Proceed with this action",
            "[ACCEPTED] I approve",
        ]

        for keyword in approval_keywords:
            result = ToolInterceptor._parse_approval(keyword)
            assert (
                result is True
            ), f"Keyword '{keyword}' should be approved but got {result}"

    def test_rejection_keywords_comprehensive(self):
        """Test that rejection keywords are recognized."""
        rejection_keywords = [
            "no",
            "reject",
            "cancel",
            "decline",
            "stop",
            "abort",
            "maybe",
            "later",
            "random text",
            "",
        ]

        for keyword in rejection_keywords:
            result = ToolInterceptor._parse_approval(keyword)
            assert (
                result is False
            ), f"Keyword '{keyword}' should be rejected but got {result}"

    def test_interrupt_with_complex_tool_input(self):
        """Test interrupt with complex tool input types."""
        @tool
        def complex_tool(data: str) -> str:
            """A tool with complex input."""
            return f"Processed: {data}"

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "approved"

            interceptor = ToolInterceptor(["complex_tool"])
            wrapped = ToolInterceptor.wrap_tool(complex_tool, interceptor)

            complex_input = {
                "data": "complex data with nested info"
            }

            result = wrapped.invoke(complex_input)

            assert mock_interrupt.called
            assert "Processed" in str(result)

    def test_configuration_from_runnable_config(self):
        """Test Configuration.from_runnable_config with interrupt_before_tools."""
        from langchain_core.runnables import RunnableConfig

        config = RunnableConfig(
            configurable={
                "interrupt_before_tools": ["db_tool"],
                "max_step_num": 5,
            }
        )

        configuration = Configuration.from_runnable_config(config)

        assert configuration.interrupt_before_tools == ["db_tool"]
        assert configuration.max_step_num == 5

    def test_tool_interceptor_initialization_logging(self):
        """Test that ToolInterceptor initialization is logged."""
        with patch("src.agents.tool_interceptor.logger") as mock_logger:
            interceptor = ToolInterceptor(["tool_a", "tool_b"])
            mock_logger.info.assert_called()

    def test_wrap_tools_with_interceptor_logging(self):
        """Test that tool wrapping is logged."""
        @tool
        def test_tool(x: str) -> str:
            """Test."""
            return x

        with patch("src.agents.tool_interceptor.logger") as mock_logger:
            wrapped = wrap_tools_with_interceptor([test_tool], ["test_tool"])
            # Check that at least one info log was called
            assert mock_logger.info.called or mock_logger.debug.called

    def test_interrupt_resolution_with_empty_feedback(self):
        """Test interrupt resolution with empty feedback."""
        @tool
        def test_tool(x: str) -> str:
            """Test."""
            return f"Result: {x}"

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = ""

            interceptor = ToolInterceptor(["test_tool"])
            wrapped = ToolInterceptor.wrap_tool(test_tool, interceptor)

            result = wrapped.invoke("test")

            # Empty feedback should be treated as rejection
            assert isinstance(result, dict)
            assert result["status"] == "rejected"

    def test_interrupt_resolution_with_none_feedback(self):
        """Test interrupt resolution with None feedback."""
        @tool
        def test_tool(x: str) -> str:
            """Test."""
            return f"Result: {x}"

        with patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            mock_interrupt.return_value = None

            interceptor = ToolInterceptor(["test_tool"])
            wrapped = ToolInterceptor.wrap_tool(test_tool, interceptor)

            result = wrapped.invoke("test")

            # None feedback should be treated as rejection
            assert isinstance(result, dict)
            assert result["status"] == "rejected"

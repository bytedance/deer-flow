# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from langchain_core.tools import tool, BaseTool

from src.agents.tool_interceptor import (
    ToolInterceptor,
    wrap_tools_with_interceptor,
)


class TestToolInterceptor:
    """Tests for ToolInterceptor class."""

    def test_init_with_tools(self):
        """Test initializing interceptor with tool list."""
        tools = ["db_tool", "api_tool"]
        interceptor = ToolInterceptor(tools)
        assert interceptor.interrupt_before_tools == tools

    def test_init_without_tools(self):
        """Test initializing interceptor without tools."""
        interceptor = ToolInterceptor()
        assert interceptor.interrupt_before_tools == []

    def test_should_interrupt_with_matching_tool(self):
        """Test should_interrupt returns True for matching tools."""
        tools = ["db_tool", "api_tool"]
        interceptor = ToolInterceptor(tools)
        assert interceptor.should_interrupt("db_tool") is True
        assert interceptor.should_interrupt("api_tool") is True

    def test_should_interrupt_with_non_matching_tool(self):
        """Test should_interrupt returns False for non-matching tools."""
        tools = ["db_tool", "api_tool"]
        interceptor = ToolInterceptor(tools)
        assert interceptor.should_interrupt("search_tool") is False
        assert interceptor.should_interrupt("crawl_tool") is False

    def test_should_interrupt_empty_list(self):
        """Test should_interrupt with empty interrupt list."""
        interceptor = ToolInterceptor([])
        assert interceptor.should_interrupt("db_tool") is False

    def test_parse_approval_with_approval_keywords(self):
        """Test parsing user feedback with approval keywords."""
        assert ToolInterceptor._parse_approval("approved") is True
        assert ToolInterceptor._parse_approval("approve") is True
        assert ToolInterceptor._parse_approval("yes") is True
        assert ToolInterceptor._parse_approval("proceed") is True
        assert ToolInterceptor._parse_approval("continue") is True
        assert ToolInterceptor._parse_approval("ok") is True
        assert ToolInterceptor._parse_approval("okay") is True
        assert ToolInterceptor._parse_approval("accepted") is True
        assert ToolInterceptor._parse_approval("accept") is True
        assert ToolInterceptor._parse_approval("[approved]") is True

    def test_parse_approval_case_insensitive(self):
        """Test parsing is case-insensitive."""
        assert ToolInterceptor._parse_approval("APPROVED") is True
        assert ToolInterceptor._parse_approval("Approved") is True
        assert ToolInterceptor._parse_approval("PROCEED") is True

    def test_parse_approval_with_surrounding_text(self):
        """Test parsing with surrounding text."""
        assert ToolInterceptor._parse_approval("Sure, proceed with the tool") is True
        assert ToolInterceptor._parse_approval("[ACCEPTED] I approve this") is True

    def test_parse_approval_rejection(self):
        """Test parsing rejects non-approval feedback."""
        assert ToolInterceptor._parse_approval("no") is False
        assert ToolInterceptor._parse_approval("reject") is False
        assert ToolInterceptor._parse_approval("cancel") is False
        assert ToolInterceptor._parse_approval("random feedback") is False

    def test_parse_approval_empty_string(self):
        """Test parsing empty string."""
        assert ToolInterceptor._parse_approval("") is False

    def test_parse_approval_none(self):
        """Test parsing None."""
        assert ToolInterceptor._parse_approval(None) is False

    @patch("src.agents.tool_interceptor.interrupt")
    def test_wrap_tool_with_interrupt(self, mock_interrupt):
        """Test wrapping a tool with interrupt."""
        mock_interrupt.return_value = "approved"

        # Create a simple test tool
        @tool
        def test_tool(input_text: str) -> str:
            """Test tool."""
            return f"Result: {input_text}"

        interceptor = ToolInterceptor(["test_tool"])

        # Wrap the tool
        wrapped_tool = ToolInterceptor.wrap_tool(test_tool, interceptor)

        # Invoke the wrapped tool
        result = wrapped_tool.invoke("hello")

        # Verify interrupt was called
        mock_interrupt.assert_called_once()
        assert "test_tool" in mock_interrupt.call_args[0][0]

    @patch("src.agents.tool_interceptor.interrupt")
    def test_wrap_tool_without_interrupt(self, mock_interrupt):
        """Test wrapping a tool that doesn't trigger interrupt."""
        # Create a simple test tool
        @tool
        def test_tool(input_text: str) -> str:
            """Test tool."""
            return f"Result: {input_text}"

        interceptor = ToolInterceptor(["other_tool"])

        # Wrap the tool
        wrapped_tool = ToolInterceptor.wrap_tool(test_tool, interceptor)

        # Invoke the wrapped tool
        result = wrapped_tool.invoke("hello")

        # Verify interrupt was NOT called
        mock_interrupt.assert_not_called()
        assert "Result: hello" in str(result)

    @patch("src.agents.tool_interceptor.interrupt")
    def test_wrap_tool_user_rejects(self, mock_interrupt):
        """Test user rejecting tool execution."""
        mock_interrupt.return_value = "no"

        @tool
        def test_tool(input_text: str) -> str:
            """Test tool."""
            return f"Result: {input_text}"

        interceptor = ToolInterceptor(["test_tool"])
        wrapped_tool = ToolInterceptor.wrap_tool(test_tool, interceptor)

        # Invoke the wrapped tool
        result = wrapped_tool.invoke("hello")

        # Verify tool was not executed
        assert isinstance(result, dict)
        assert "error" in result
        assert result["status"] == "rejected"

    def test_wrap_tools_with_interceptor_empty_list(self):
        """Test wrapping tools with empty interrupt list."""
        @tool
        def test_tool(input_text: str) -> str:
            """Test tool."""
            return f"Result: {input_text}"

        tools = [test_tool]
        wrapped_tools = wrap_tools_with_interceptor(tools, [])

        # Should return tools as-is
        assert len(wrapped_tools) == 1
        assert wrapped_tools[0].name == "test_tool"

    def test_wrap_tools_with_interceptor_none(self):
        """Test wrapping tools with None interrupt list."""
        @tool
        def test_tool(input_text: str) -> str:
            """Test tool."""
            return f"Result: {input_text}"

        tools = [test_tool]
        wrapped_tools = wrap_tools_with_interceptor(tools, None)

        # Should return tools as-is
        assert len(wrapped_tools) == 1

    @patch("src.agents.tool_interceptor.interrupt")
    def test_wrap_tools_with_interceptor_multiple(self, mock_interrupt):
        """Test wrapping multiple tools."""
        mock_interrupt.return_value = "approved"

        @tool
        def db_tool(query: str) -> str:
            """DB tool."""
            return f"Query result: {query}"

        @tool
        def search_tool(query: str) -> str:
            """Search tool."""
            return f"Search result: {query}"

        tools = [db_tool, search_tool]
        wrapped_tools = wrap_tools_with_interceptor(tools, ["db_tool"])

        # Only db_tool should trigger interrupt
        db_result = wrapped_tools[0].invoke("test query")
        assert mock_interrupt.call_count == 1

        search_result = wrapped_tools[1].invoke("test query")
        # No additional interrupt calls for search_tool
        assert mock_interrupt.call_count == 1

    def test_wrap_tool_preserves_tool_properties(self):
        """Test that wrapping preserves tool properties."""
        @tool
        def my_tool(input_text: str) -> str:
            """My tool description."""
            return f"Result: {input_text}"

        interceptor = ToolInterceptor([])
        wrapped_tool = ToolInterceptor.wrap_tool(my_tool, interceptor)

        assert wrapped_tool.name == "my_tool"
        assert wrapped_tool.description == "My tool description."

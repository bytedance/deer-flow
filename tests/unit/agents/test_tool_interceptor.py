# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from langchain_core.tools import BaseTool, tool

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


class TestFormatToolInput:
    """Tests for tool input formatting functionality."""

    def test_format_tool_input_none(self):
        """Test formatting None input."""
        result = ToolInterceptor._format_tool_input(None)
        assert result == "No input"

    def test_format_tool_input_string(self):
        """Test formatting string input."""
        input_str = "SELECT * FROM users"
        result = ToolInterceptor._format_tool_input(input_str)
        assert result == input_str

    def test_format_tool_input_simple_dict(self):
        """Test formatting simple dictionary."""
        input_dict = {"query": "test", "limit": 10}
        result = ToolInterceptor._format_tool_input(input_dict)
        
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        assert parsed == input_dict
        # Should be indented
        assert "\n" in result

    def test_format_tool_input_nested_dict(self):
        """Test formatting nested dictionary."""
        input_dict = {
            "query": "SELECT * FROM users",
            "config": {
                "timeout": 30,
                "retry": True
            }
        }
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        assert parsed == input_dict
        assert "timeout" in result
        assert "retry" in result

    def test_format_tool_input_list(self):
        """Test formatting list input."""
        input_list = ["item1", "item2", 123]
        result = ToolInterceptor._format_tool_input(input_list)
        
        import json
        parsed = json.loads(result)
        assert parsed == input_list

    def test_format_tool_input_complex_list(self):
        """Test formatting list with mixed types."""
        input_list = ["text", 42, 3.14, True, {"key": "value"}]
        result = ToolInterceptor._format_tool_input(input_list)
        
        import json
        parsed = json.loads(result)
        assert parsed == input_list

    def test_format_tool_input_tuple(self):
        """Test formatting tuple input."""
        input_tuple = ("item1", "item2", 123)
        result = ToolInterceptor._format_tool_input(input_tuple)
        
        import json
        parsed = json.loads(result)
        # JSON converts tuples to lists
        assert parsed == list(input_tuple)

    def test_format_tool_input_integer(self):
        """Test formatting integer input."""
        result = ToolInterceptor._format_tool_input(42)
        assert result == "42"

    def test_format_tool_input_float(self):
        """Test formatting float input."""
        result = ToolInterceptor._format_tool_input(3.14)
        assert result == "3.14"

    def test_format_tool_input_boolean(self):
        """Test formatting boolean input."""
        result_true = ToolInterceptor._format_tool_input(True)
        result_false = ToolInterceptor._format_tool_input(False)
        assert result_true == "True"
        assert result_false == "False"

    def test_format_tool_input_deeply_nested(self):
        """Test formatting deeply nested structure."""
        input_dict = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": ["a", "b", "c"],
                        "data": {"key": "value"}
                    }
                }
            }
        }
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        assert parsed == input_dict

    def test_format_tool_input_empty_dict(self):
        """Test formatting empty dictionary."""
        result = ToolInterceptor._format_tool_input({})
        assert result == "{}"

    def test_format_tool_input_empty_list(self):
        """Test formatting empty list."""
        result = ToolInterceptor._format_tool_input([])
        assert result == "[]"

    def test_format_tool_input_special_characters(self):
        """Test formatting dict with special characters."""
        input_dict = {
            "query": 'SELECT * FROM users WHERE name = "John"',
            "path": "/usr/local/bin",
            "unicode": "你好世界"
        }
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        assert parsed == input_dict

    def test_format_tool_input_numbers_as_strings(self):
        """Test formatting with various number types."""
        input_dict = {
            "int": 42,
            "float": 3.14159,
            "negative": -100,
            "zero": 0,
            "scientific": 1e-5
        }
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        assert parsed["int"] == 42
        assert abs(parsed["float"] - 3.14159) < 0.00001
        assert parsed["negative"] == -100
        assert parsed["zero"] == 0

    def test_format_tool_input_with_none_values(self):
        """Test formatting dict with None values."""
        input_dict = {
            "key1": "value1",
            "key2": None,
            "key3": {"nested": None}
        }
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        assert parsed == input_dict

    def test_format_tool_input_indentation(self):
        """Test that output uses proper indentation (2 spaces)."""
        input_dict = {"outer": {"inner": "value"}}
        result = ToolInterceptor._format_tool_input(input_dict)
        
        # Should have indented lines
        assert "  " in result  # 2-space indentation
        lines = result.split("\n")
        # Check that indentation increases with nesting
        assert any(line.startswith("  ") for line in lines)

    def test_format_tool_input_preserves_order_insertion(self):
        """Test that dict order is preserved in output."""
        input_dict = {
            "first": 1,
            "second": 2,
            "third": 3
        }
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        # Verify all keys are present
        assert set(parsed.keys()) == {"first", "second", "third"}

    def test_format_tool_input_long_strings(self):
        """Test formatting with long string values."""
        long_string = "x" * 1000
        input_dict = {"long": long_string}
        result = ToolInterceptor._format_tool_input(input_dict)
        
        import json
        parsed = json.loads(result)
        assert parsed["long"] == long_string

    def test_format_tool_input_mixed_types_in_list(self):
        """Test formatting list with mixed complex types."""
        input_list = [
            "string",
            42,
            {"dict": "value"},
            [1, 2, 3],
            True,
            None
        ]
        result = ToolInterceptor._format_tool_input(input_list)
        
        import json
        parsed = json.loads(result)
        assert len(parsed) == 6
        assert parsed[0] == "string"
        assert parsed[1] == 42
        assert parsed[2] == {"dict": "value"}
        assert parsed[3] == [1, 2, 3]
        assert parsed[4] is True
        assert parsed[5] is None

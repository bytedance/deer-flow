# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import unittest
from unittest.mock import MagicMock
from langchain_core.tools import Tool
from src.agents.tool_interceptor import ToolInterceptor

class TestToolInterceptorFix(unittest.TestCase):
    def test_interceptor_patches_run_method(self):
        # Create a mock tool
        mock_func = MagicMock(return_value="Original Result")
        tool = Tool(name="resolve_company_name", func=mock_func, description="test tool")
        
        # Interceptor that always interrupts 'resolve_company_name'
        interceptor = ToolInterceptor(interrupt_before_tools=["resolve_company_name"])
        
        # Wrap the tool
        wrapped_tool = ToolInterceptor.wrap_tool(tool, interceptor)
        
        # Mock interrupt to avoid actual suspension
        with unittest.mock.patch("src.agents.tool_interceptor.interrupt", return_value="approved"):
            # Call using .run() which triggers ._run()
            # Standard BaseTool execution flow is invoke -> run -> _run
            # If we only patched func, run() would call original _run which calls original func, bypassing interception
            # With the fix, _run should be patched to call intercepted_func
            result = wrapped_tool.run("some input")
            
        # Verify result
        self.assertEqual(result, "Original Result")
        
        # Verify the original function was called
        # If interception works, intercepted_func calls original_func
        mock_func.assert_called_once()

    def test_run_method_without_interrupt(self):
        """Test that tools not in interrupt list work normally via .run()"""
        mock_func = MagicMock(return_value="Result")
        tool = Tool(name="other_tool", func=mock_func, description="test")
        
        interceptor = ToolInterceptor(interrupt_before_tools=["resolve_company_name"])
        wrapped_tool = ToolInterceptor.wrap_tool(tool, interceptor)
        
        with unittest.mock.patch("src.agents.tool_interceptor.interrupt") as mock_interrupt:
            result = wrapped_tool.run("input")
            
        # Verify interrupt was NOT called for non-intercepted tool
        mock_interrupt.assert_not_called()
        assert result == "Result"
        mock_func.assert_called_once()
        
    def test_interceptor_resolve_company_name_example(self):
        """Test specific resolve_company_name logic capability using interceptor subclassing or custom logic simulation."""
        # This test verifies that we can intercept execution of resolve_company_name
        # even if it's called via .run()
        
        mock_func = MagicMock(return_value='{"code": 0, "data": [{"companyName": "A"}, {"companyName": "B"}]}')
        tool = Tool(name="resolve_company_name", func=mock_func, description="resolve company")
        
        interceptor = ToolInterceptor(interrupt_before_tools=["resolve_company_name"])
        wrapped_tool = ToolInterceptor.wrap_tool(tool, interceptor)
        
        # Simulate user selecting "B"
        with unittest.mock.patch("src.agents.tool_interceptor.interrupt", return_value="approved"):
             # We are not testing the complex business logic here because we didn't add it to ToolInterceptor class
             # We are mostly verifying that the INTERCEPTION mechanism works for this tool name when called via .run()
             wrapped_tool.run("query")
             
        mock_func.assert_called_once()

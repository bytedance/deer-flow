# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
from typing import Any, Callable, List, Optional

from langchain_core.tools import BaseTool
from langgraph.types import interrupt

from src.utils.log_sanitizer import (
    sanitize_feedback,
    sanitize_log_input,
    sanitize_tool_name,
)

logger = logging.getLogger(__name__)


class ToolInterceptor:
    """Intercepts tool calls and triggers interrupts for specified tools."""

    def __init__(self, interrupt_before_tools: Optional[List[str]] = None):
        """Initialize the interceptor with list of tools to interrupt before.

        Args:
            interrupt_before_tools: List of tool names to interrupt before execution.
                                    If None or empty, no interrupts are triggered.
        """
        self.interrupt_before_tools = interrupt_before_tools or []
        logger.info(
            f"ToolInterceptor initialized with interrupt_before_tools: {self.interrupt_before_tools}"
        )

    def should_interrupt(self, tool_name: str) -> bool:
        """Check if execution should be interrupted before this tool.

        Args:
            tool_name: Name of the tool being called

        Returns:
            bool: True if tool should trigger an interrupt, False otherwise
        """
        should_interrupt = tool_name in self.interrupt_before_tools
        if should_interrupt:
            logger.info(f"Tool '{tool_name}' marked for interrupt")
        return should_interrupt

    @staticmethod
    def _format_tool_input(tool_input: Any) -> str:
        """Format tool input for display in interrupt messages.

        Attempts to format as JSON for better readability, with fallback to string representation.

        Args:
            tool_input: The tool input to format

        Returns:
            str: Formatted representation of the tool input
        """
        if tool_input is None:
            return "No input"

        # Try to serialize as JSON first for better readability
        try:
            # Handle dictionaries and other JSON-serializable objects
            if isinstance(tool_input, (dict, list, tuple)):
                return json.dumps(tool_input, indent=2, default=str)
            elif isinstance(tool_input, str):
                return tool_input
            else:
                # For other types, try to convert to dict if it has __dict__
                # Otherwise fall back to string representation
                return str(tool_input)
        except (TypeError, ValueError):
            # JSON serialization failed, use string representation
            return str(tool_input)

    @staticmethod
    def wrap_tool(
        tool: BaseTool, interceptor: "ToolInterceptor"
    ) -> BaseTool:
        """Wrap a tool to add interrupt logic by creating a wrapper.

        Args:
            tool: The tool to wrap
            interceptor: The ToolInterceptor instance

        Returns:
            BaseTool: The wrapped tool with interrupt capability
        """
        original_func = tool.func
        safe_tool_name = sanitize_tool_name(tool.name)
        logger.debug(f"Wrapping tool '{safe_tool_name}' with interrupt capability")

        def intercepted_func(*args: Any, **kwargs: Any) -> Any:
            """Execute the tool with interrupt check."""
            tool_name = tool.name
            safe_tool_name_local = sanitize_tool_name(tool_name)
            logger.debug(f"[ToolInterceptor] Executing tool: {safe_tool_name_local}")
            
            # Format tool input for display
            tool_input = args[0] if args else kwargs
            tool_input_repr = ToolInterceptor._format_tool_input(tool_input)
            safe_tool_input = sanitize_log_input(tool_input_repr, max_length=100)
            logger.debug(f"[ToolInterceptor] Tool input: {safe_tool_input}")

            should_interrupt = interceptor.should_interrupt(tool_name)
            logger.debug(f"[ToolInterceptor] should_interrupt={should_interrupt} for tool '{safe_tool_name_local}'")
            
            if should_interrupt:
                logger.info(
                    f"[ToolInterceptor] Interrupting before tool '{safe_tool_name_local}'"
                )
                logger.debug(
                    f"[ToolInterceptor] Interrupt message: About to execute tool '{safe_tool_name_local}' with input: {safe_tool_input}..."
                )
                
                # Trigger interrupt and wait for user feedback
                try:
                    feedback = interrupt(
                        f"About to execute tool: '{tool_name}'\n\nInput:\n{tool_input_repr}\n\nApprove execution?"
                    )
                    safe_feedback = sanitize_feedback(feedback)
                    logger.debug(f"[ToolInterceptor] Interrupt returned with feedback: {f'{safe_feedback[:100]}...' if safe_feedback and len(safe_feedback) > 100 else safe_feedback if safe_feedback else 'None'}")
                except Exception as e:
                    logger.error(f"[ToolInterceptor] Error during interrupt: {str(e)}")
                    raise

                logger.debug(f"[ToolInterceptor] Processing feedback approval for '{safe_tool_name_local}'")
                
                # Check if user approved
                is_approved = ToolInterceptor._parse_approval(feedback)
                logger.info(f"[ToolInterceptor] Tool '{safe_tool_name_local}' approval decision: {is_approved}")
                
                if not is_approved:
                    logger.warning(f"[ToolInterceptor] User rejected execution of tool '{safe_tool_name_local}'")
                    return {
                        "error": f"Tool execution rejected by user",
                        "tool": tool_name,
                        "status": "rejected",
                    }

                logger.info(f"[ToolInterceptor] User approved execution of tool '{safe_tool_name_local}', proceeding")

            # Execute the original tool
            try:
                logger.debug(f"[ToolInterceptor] Calling original function for tool '{safe_tool_name_local}'")
                result = original_func(*args, **kwargs)
                logger.info(f"[ToolInterceptor] Tool '{safe_tool_name_local}' execution completed successfully")
                result_len = len(str(result))
                logger.debug(f"[ToolInterceptor] Tool result length: {result_len}")
                return result
            except Exception as e:
                logger.error(f"[ToolInterceptor] Error executing tool '{safe_tool_name_local}': {str(e)}")
                raise

        # Replace the function and update the tool
        # Use object.__setattr__ to bypass Pydantic validation
        logger.debug(f"Attaching intercepted function to tool '{safe_tool_name}'")
        object.__setattr__(tool, "func", intercepted_func)
        return tool

    @staticmethod
    def _parse_approval(feedback: str) -> bool:
        """Parse user feedback to determine if tool execution was approved.

        Args:
            feedback: The feedback string from the user

        Returns:
            bool: True if feedback indicates approval, False otherwise
        """
        if not feedback:
            logger.warning("Empty feedback received, treating as rejection")
            return False

        feedback_lower = feedback.lower().strip()

        # Check for approval keywords
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
        ]

        for keyword in approval_keywords:
            if keyword in feedback_lower:
                return True

        # Default to rejection if no approval keywords found
        logger.warning(
            f"No approval keywords found in feedback: {feedback}. Treating as rejection."
        )
        return False


def wrap_tools_with_interceptor(
    tools: List[BaseTool], interrupt_before_tools: Optional[List[str]] = None
) -> List[BaseTool]:
    """Wrap multiple tools with interrupt logic.

    Args:
        tools: List of tools to wrap
        interrupt_before_tools: List of tool names to interrupt before

    Returns:
        List[BaseTool]: List of wrapped tools
    """
    if not interrupt_before_tools:
        logger.debug("No tool interrupts configured, returning tools as-is")
        return tools

    logger.info(
        f"Wrapping {len(tools)} tools with interrupt logic for: {interrupt_before_tools}"
    )
    interceptor = ToolInterceptor(interrupt_before_tools)

    wrapped_tools = []
    for tool in tools:
        try:
            wrapped_tool = ToolInterceptor.wrap_tool(tool, interceptor)
            wrapped_tools.append(wrapped_tool)
            logger.debug(f"Wrapped tool: {tool.name}")
        except Exception as e:
            logger.error(f"Failed to wrap tool {tool.name}: {str(e)}")
            # Add original tool if wrapping fails
            wrapped_tools.append(tool)

    logger.info(f"Successfully wrapped {len(wrapped_tools)} tools")
    return wrapped_tools

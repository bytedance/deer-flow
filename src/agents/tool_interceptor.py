# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import Any, Callable, List, Optional

from langchain_core.tools import BaseTool
from langgraph.types import interrupt

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

        def intercepted_func(*args: Any, **kwargs: Any) -> Any:
            """Execute the tool with interrupt check."""
            tool_name = tool.name
            # Build a string representation of the input
            tool_input_repr = str(args[0] if args else kwargs) if (args or kwargs) else "No input"

            if interceptor.should_interrupt(tool_name):
                logger.info(
                    f"Interrupting before tool '{tool_name}' with input: {tool_input_repr}"
                )
                # Trigger interrupt and wait for user feedback
                feedback = interrupt(
                    f"About to execute tool: '{tool_name}'\n\nInput: {tool_input_repr}\n\nApprove execution?"
                )

                logger.info(f"Interrupt feedback for '{tool_name}': {feedback}")

                # Check if user approved
                if not ToolInterceptor._parse_approval(feedback):
                    logger.warning(f"User rejected execution of tool '{tool_name}'")
                    return {
                        "error": f"Tool execution rejected by user",
                        "tool": tool_name,
                        "status": "rejected",
                    }

                logger.info(f"User approved execution of tool '{tool_name}'")

            # Execute the original tool
            try:
                result = original_func(*args, **kwargs)
                logger.debug(f"Tool '{tool_name}' execution completed")
                return result
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}': {str(e)}")
                raise

        # Replace the function and update the tool
        # Use object.__setattr__ to bypass Pydantic validation
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

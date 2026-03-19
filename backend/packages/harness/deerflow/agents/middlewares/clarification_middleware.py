"""中间件 for intercepting clarification requests and presenting them to the 用户."""

from collections.abc import Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


class ClarificationMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Intercepts clarification 工具 calls and interrupts execution to present questions to the 用户.

    When the 模型 calls the `ask_clarification` 工具, this 中间件:
    1. Intercepts the 工具 call before execution
    2. Extracts the clarification question and metadata
    3. Formats a 用户-friendly 消息
    4. Returns a Command that interrupts execution and presents the question
    5. Waits for 用户 响应 before continuing

    This replaces the 工具-based approach where clarification continued the conversation flow.
    """

    state_schema = ClarificationMiddlewareState

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters.

        Args:
            text: Text to 检查

        Returns:
            True if text contains Chinese characters
        """
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        """Format the clarification arguments into a 用户-friendly 消息.

        Args:
            args: The 工具 call arguments containing clarification details

        Returns:
            Formatted 消息 字符串
        """
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = args.get("options", [])

        #    Type-specific icons


        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        #    Build the 消息 naturally


        message_parts = []

        #    Add icon and question together 对于 a more natural flow


        if context:
            #    If there's context, present it 第一 as background


            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            #    Just the question with icon


            message_parts.append(f"{icon} {question}")

        #    Add options in a cleaner format


        if options and len(options) > 0:
            message_parts.append("")  #    blank line 对于 spacing


            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        """Handle clarification 请求 and 返回 command to interrupt execution.

        Args:
            请求: 工具 call 请求

        Returns:
            Command that interrupts execution with the formatted clarification 消息
        """
        #    Extract clarification arguments


        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        print("[ClarificationMiddleware] Intercepted clarification request")
        print(f"[ClarificationMiddleware] Question: {question}")

        #    Format the clarification 消息


        formatted_message = self._format_clarification_message(args)

        #    Get the 工具 call ID


        tool_call_id = request.tool_call.get("id", "")

        #    Create a ToolMessage with the formatted question


        #    This will be added to the 消息 history


        tool_message = ToolMessage(
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

        #    Return a Command that:


        #    1. Adds the formatted 工具 消息


        #    2. Interrupts execution by going to __end__


        #    Note: We don't add an extra AIMessage here - the 前端 will detect


        #    and display ask_clarification 工具 messages directly


        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification 工具 calls and interrupt execution (sync version).

        Args:
            请求: 工具 call 请求
            handler: Original 工具 execution handler

        Returns:
            Command that interrupts execution with the formatted clarification 消息
        """
        #    Check 如果 this is an ask_clarification 工具 call


        if request.tool_call.get("name") != "ask_clarification":
            #    Not a clarification call, 执行 normally


            return handler(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification 工具 calls and interrupt execution (异步 version).

        Args:
            请求: 工具 call 请求
            handler: Original 工具 execution handler (异步)

        Returns:
            Command that interrupts execution with the formatted clarification 消息
        """
        #    Check 如果 this is an ask_clarification 工具 call


        if request.tool_call.get("name") != "ask_clarification":
            #    Not a clarification call, 执行 normally


            return await handler(request)

        return self._handle_clarification(request)

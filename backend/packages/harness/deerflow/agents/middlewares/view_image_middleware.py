"""
图像查看中间件 - 在LLM调用前将图像详情注入到对话中

===================
设计思路说明
===================

**核心职责**：
当view_image工具完成后，将图像详情作为人类消息注入：
1. **时机检测**：检查view_image工具调用是否完成
2. **图像注入**：将base64图像数据注入到消息中
3. **LLM可见**：让LLM能够"看到"并分析图像
4. **去重机制**：避免重复注入相同的图像信息

**为什么需要这个中间件**：
1. **视觉能力**：让LLM能够分析图像内容
2. **自动化**：无需用户明确描述图像
3. **上下文保持**：图像信息与对话上下文结合
4. **多模态支持**：启用视觉模型的能力

**设计决策**：
- 在before_model中注入：LLM调用前提供图像信息
- 检查完成状态：确保工具调用已完成
- 使用HumanMessage：避免SystemMessage限制
- base64格式：直接嵌入图像数据

**为什么使用base64嵌入**：
- **无需外部引用**：图像数据直接在消息中
- **可靠性**：不依赖外部URL的可用性
- **安全性**：不暴露内部文件路径
- **兼容性**：所有支持视觉的模型都支持
"""

import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ViewedImageData

logger = logging.getLogger(__name__)


class ViewImageMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    viewed_images: NotRequired[dict[str, ViewedImageData] | None]


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    """在view_image工具完成后将图像详情作为人类消息注入

    **为什么需要这个中间件**：
    - **自动视觉**：LLM自动接收并分析图像
    - **无需提示**：不需要用户明确描述图像
    - **多模态支持**：启用视觉模型的分析能力
    - **上下文集成**：图像信息与对话上下文结合

    **工作流程**：
    1. 在每次LLM调用前运行
    2. 检查最后一条助手消息是否包含view_image工具调用
    3. 验证该消息中的所有工具调用都已完成（有对应的ToolMessages）
    4. 如果满足条件，创建包含所有查看图像详情的人类消息（包括base64数据）
    5. 将消息添加到state，使LLM可以看到并分析图像

    **为什么这样设计**：
    - **自动化**：无需用户干预，自动提供图像信息
    - **条件触发**：只在工具完成后注入，避免不完整数据
    - **去重机制**：检查是否已注入，避免重复
    - **完整性**：确保所有图像都包含在消息中
    """

    state_schema = ViewImageMiddlewareState

    def _get_last_assistant_message(self, messages: list) -> AIMessage | None:
        """Get the last assistant message from the message list.

        Args:
            messages: List of messages

        Returns:
            Last AIMessage or None if not found
        """
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg
        return None

    def _has_view_image_tool(self, message: AIMessage) -> bool:
        """Check if the assistant message contains view_image tool calls.

        Args:
            message: Assistant message to check

        Returns:
            True if message contains view_image tool calls
        """
        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return False

        return any(tool_call.get("name") == "view_image" for tool_call in message.tool_calls)

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        """Check if all tool calls in the assistant message have been completed.

        Args:
            messages: List of all messages
            assistant_msg: The assistant message containing tool calls

        Returns:
            True if all tool calls have corresponding ToolMessages
        """
        if not hasattr(assistant_msg, "tool_calls") or not assistant_msg.tool_calls:
            return False

        # Get all tool call IDs from the assistant message
        tool_call_ids = {tool_call.get("id") for tool_call in assistant_msg.tool_calls if tool_call.get("id")}

        # Find the index of the assistant message
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False

        # Get all ToolMessages after the assistant message
        completed_tool_ids = set()
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and msg.tool_call_id:
                completed_tool_ids.add(msg.tool_call_id)

        # Check if all tool calls have been completed
        return tool_call_ids.issubset(completed_tool_ids)

    def _create_image_details_message(self, state: ViewImageMiddlewareState) -> list[str | dict]:
        """Create a formatted message with all viewed image details.

        Args:
            state: Current state containing viewed_images

        Returns:
            List of content blocks (text and images) for the HumanMessage
        """
        viewed_images = state.get("viewed_images", {})
        if not viewed_images:
            # Return a properly formatted text block, not a plain string array
            return [{"type": "text", "text": "No images have been viewed."}]

        # Build the message with image information
        content_blocks: list[str | dict] = [{"type": "text", "text": "Here are the images you've viewed:"}]

        for image_path, image_data in viewed_images.items():
            mime_type = image_data.get("mime_type", "unknown")
            base64_data = image_data.get("base64", "")

            # Add text description
            content_blocks.append({"type": "text", "text": f"\n- **{image_path}** ({mime_type})"})

            # Add the actual image data so LLM can "see" it
            if base64_data:
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
                    }
                )

        return content_blocks

    def _should_inject_image_message(self, state: ViewImageMiddlewareState) -> bool:
        """Determine if we should inject an image details message.

        Args:
            state: Current state

        Returns:
            True if we should inject the message
        """
        messages = state.get("messages", [])
        if not messages:
            return False

        # Get the last assistant message
        last_assistant_msg = self._get_last_assistant_message(messages)
        if not last_assistant_msg:
            return False

        # Check if it has view_image tool calls
        if not self._has_view_image_tool(last_assistant_msg):
            return False

        # Check if all tools have been completed
        if not self._all_tools_completed(messages, last_assistant_msg):
            return False

        # Check if we've already added an image details message
        # Look for a human message after the last assistant message that contains image details
        assistant_idx = messages.index(last_assistant_msg)
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                content_str = str(msg.content)
                if "Here are the images you've viewed" in content_str or "Here are the details of the images you've viewed" in content_str:
                    # Already added, don't add again
                    return False

        return True

    def _inject_image_message(self, state: ViewImageMiddlewareState) -> dict | None:
        """Internal helper to inject image details message.

        Args:
            state: Current state

        Returns:
            State update with additional human message, or None if no update needed
        """
        if not self._should_inject_image_message(state):
            return None

        # Create the image details message with text and image content
        image_content = self._create_image_details_message(state)

        # Create a new human message with mixed content (text + images)
        human_msg = HumanMessage(content=image_content)

        logger.debug("Injecting image details message with images before LLM call")

        # Return state update with the new message
        return {"messages": [human_msg]}

    @override
    def before_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject image details message before LLM call if view_image tools have completed (sync version).

        This runs before each LLM call, checking if the previous turn included view_image
        tool calls that have all completed. If so, it injects a human message with the image
        details so the LLM can see and analyze the images.

        Args:
            state: Current state
            runtime: Runtime context (unused but required by interface)

        Returns:
            State update with additional human message, or None if no update needed
        """
        return self._inject_image_message(state)

    @override
    async def abefore_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject image details message before LLM call if view_image tools have completed (async version).

        This runs before each LLM call, checking if the previous turn included view_image
        tool calls that have all completed. If so, it injects a human message with the image
        details so the LLM can see and analyze the images.

        Args:
            state: Current state
            runtime: Runtime context (unused but required by interface)

        Returns:
            State update with additional human message, or None if no update needed
        """
        return self._inject_image_message(state)

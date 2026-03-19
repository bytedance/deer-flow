"""中间件 for injecting image details into conversation before LLM call."""

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ViewedImageData


class ViewImageMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    viewed_images: NotRequired[dict[str, ViewedImageData] | None]


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    """Injects image details as a human 消息 before LLM calls when view_image tools have completed.

    This 中间件:
    1. Runs before each LLM call
    2. Checks if the 最后 assistant 消息 contains view_image 工具 calls
    3. Verifies all 工具 calls in that 消息 have been completed (have corresponding ToolMessages)
    4. If conditions are met, creates a human 消息 with all viewed image details (including base64 数据)
    5. Adds the 消息 to 状态 so the LLM can see and analyze the images

    This enables the LLM to automatically receive and analyze images that were loaded via view_image 工具,
    without requiring explicit 用户 prompts to describe the images.
    """

    state_schema = ViewImageMiddlewareState

    def _get_last_assistant_message(self, messages: list) -> AIMessage | None:
        """Get the 最后 assistant 消息 from the 消息 列表.

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
        """Check if the assistant 消息 contains view_image 工具 calls.

        Args:
            消息: Assistant 消息 to 检查

        Returns:
            True if 消息 contains view_image 工具 calls
        """
        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return False

        return any(tool_call.get("name") == "view_image" for tool_call in message.tool_calls)

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        """Check if all 工具 calls in the assistant 消息 have been completed.

        Args:
            messages: List of all messages
            assistant_msg: The assistant 消息 containing 工具 calls

        Returns:
            True if all 工具 calls have corresponding ToolMessages
        """
        if not hasattr(assistant_msg, "tool_calls") or not assistant_msg.tool_calls:
            return False

        #    Get all 工具 call IDs from the assistant 消息


        tool_call_ids = {tool_call.get("id") for tool_call in assistant_msg.tool_calls if tool_call.get("id")}

        #    Find the 索引 of the assistant 消息


        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False

        #    Get all ToolMessages after the assistant 消息


        completed_tool_ids = set()
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and msg.tool_call_id:
                completed_tool_ids.add(msg.tool_call_id)

        #    Check 如果 all 工具 calls have been completed


        return tool_call_ids.issubset(completed_tool_ids)

    def _create_image_details_message(self, state: ViewImageMiddlewareState) -> list[str | dict]:
        """Create a formatted 消息 with all viewed image details.

        Args:
            状态: Current 状态 containing viewed_images

        Returns:
            List of content blocks (text and images) for the HumanMessage
        """
        viewed_images = state.get("viewed_images", {})
        if not viewed_images:
            return ["No images have been viewed."]

        #    Build the 消息 with image information


        content_blocks: list[str | dict] = [{"type": "text", "text": "Here are the images you've viewed:"}]

        for image_path, image_data in viewed_images.items():
            mime_type = image_data.get("mime_type", "unknown")
            base64_data = image_data.get("base64", "")

            #    Add text 描述


            content_blocks.append({"type": "text", "text": f"\n- **{image_path}** ({mime_type})"})

            #    Add the actual image 数据 so LLM can "see" it


            if base64_data:
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
                    }
                )

        return content_blocks

    def _should_inject_image_message(self, state: ViewImageMiddlewareState) -> bool:
        """Determine if we should inject an image details 消息.

        Args:
            状态: Current 状态

        Returns:
            True if we should inject the 消息
        """
        messages = state.get("messages", [])
        if not messages:
            return False

        #    Get the 最后 assistant 消息


        last_assistant_msg = self._get_last_assistant_message(messages)
        if not last_assistant_msg:
            return False

        #    Check 如果 it has view_image 工具 calls


        if not self._has_view_image_tool(last_assistant_msg):
            return False

        #    Check 如果 all tools have been completed


        if not self._all_tools_completed(messages, last_assistant_msg):
            return False

        #    Check 如果 we've already added an image details 消息


        #    Look 对于 a human 消息 after the 最后 assistant 消息 that contains image details


        assistant_idx = messages.index(last_assistant_msg)
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                content_str = str(msg.content)
                if "Here are the images you've viewed" in content_str or "Here are the details of the images you've viewed" in content_str:
                    #    Already added, don't add again


                    return False

        return True

    def _inject_image_message(self, state: ViewImageMiddlewareState) -> dict | None:
        """Internal helper to inject image details 消息.

        Args:
            状态: Current 状态

        Returns:
            状态 更新 with additional human 消息, or None if no 更新 needed
        """
        if not self._should_inject_image_message(state):
            return None

        #    Create the image details 消息 with text and image content


        image_content = self._create_image_details_message(state)

        #    Create a 新建 human 消息 with mixed content (text + images)


        human_msg = HumanMessage(content=image_content)

        print("[ViewImageMiddleware] Injecting image details message with images before LLM call")

        #    Return 状态 更新 with the 新建 消息


        return {"messages": [human_msg]}

    @override
    def before_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject image details 消息 before LLM call if view_image tools have completed (sync version).

        This runs before each LLM call, checking if the 上一个 turn included view_image
        工具 calls that have all completed. If so, it injects a human 消息 with the image
        details so the LLM can see and analyze the images.

        Args:
            状态: Current 状态
            runtime: Runtime context (unused but required by 接口)

        Returns:
            状态 更新 with additional human 消息, or None if no 更新 needed
        """
        return self._inject_image_message(state)

    @override
    async def abefore_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject image details 消息 before LLM call if view_image tools have completed (异步 version).

        This runs before each LLM call, checking if the 上一个 turn included view_image
        工具 calls that have all completed. If so, it injects a human 消息 with the image
        details so the LLM can see and analyze the images.

        Args:
            状态: Current 状态
            runtime: Runtime context (unused but required by 接口)

        Returns:
            状态 更新 with additional human 消息, or None if no 更新 needed
        """
        return self._inject_image_message(state)

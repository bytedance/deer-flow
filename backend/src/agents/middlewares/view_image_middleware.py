"""Middleware for injecting image details into conversation before LLM call."""

import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from src.agents.thread_state import ViewedImageData

logger = logging.getLogger(__name__)


class ViewImageMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    viewed_images: NotRequired[dict[str, ViewedImageData] | None]


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    """Injects image details as a human message before LLM calls when view_image tools have completed.

    This middleware:
    1. Runs before each LLM call
    2. Checks if the last assistant message contains view_image tool calls
    3. Verifies all tool calls in that message have been completed (have corresponding ToolMessages)
    4. If conditions are met, creates a human message with all viewed image details (including base64 data)
    5. Adds the message to state so the LLM can see and analyze the images

    This enables the LLM to automatically receive and analyze images that were loaded via view_image tool,
    without requiring explicit user prompts to describe the images.
    """

    state_schema = ViewImageMiddlewareState

    def __init__(self, model_name: str | None = None):
        super().__init__()
        self._model_name = model_name

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

    def _extract_view_image_paths(self, message: AIMessage) -> list[str]:
        """Extract image paths from view_image tool calls in an assistant message."""
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return []

        paths: list[str] = []
        for tool_call in tool_calls:
            if tool_call.get("name") != "view_image":
                continue
            args = tool_call.get("args")
            if not isinstance(args, dict):
                continue
            image_path = args.get("image_path")
            if isinstance(image_path, str) and image_path:
                paths.append(image_path)
        return paths

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

    def _create_image_details_message(
        self,
        state: ViewImageMiddlewareState,
        runtime: Runtime,
        image_paths: list[str] | None = None,
    ) -> list[str | dict]:
        """Create a formatted message with all viewed image details.

        Args:
            state: Current state containing viewed_images
            runtime: Runtime context

        Returns:
            List of content blocks (text and images) for the HumanMessage
        """
        viewed_images = state.get("viewed_images") or {}
        if not isinstance(viewed_images, dict) or not viewed_images:
            return ["No images have been viewed."]

        # Conditionally add vision prompt if configured
        vision_prompt = None
        model_name = self._model_name
        if model_name is None and hasattr(runtime, "context") and runtime.context and hasattr(runtime.context, "get"):
            configurable = runtime.context.get("configurable") or {}
            if isinstance(configurable, dict):
                model_name = configurable.get("model_name") or configurable.get("model")

        if model_name:
            from src.config import get_app_config

            app_config = get_app_config()
            model_config = app_config.get_model_config(model_name)
            if model_config and model_config.vision_prompt:
                vision_prompt = model_config.vision_prompt

        default_prompt = (
            "Here are the images you've viewed. "
            "As an expert scientific data analyst, please deeply analyze these scientific images "
            "(e.g., Western Blot, t-SNE, FACS, astronomical spectra, microscopy, etc.). "
            "Do not just describe them superficially. You must:\n"
            "1. Extract quantitative trends and structural patterns directly from the visual data.\n"
            "2. Identify key features, anomalies, and control group comparisons.\n"
            "3. Draw rigorous scientific conclusions based on the visual evidence."
        )

        # Build the message with image information
        content_blocks: list[str | dict] = [
            {
                "type": "text",
                "text": vision_prompt or default_prompt,
            }
        ]

        if image_paths:
            image_items = [(p, viewed_images.get(p)) for p in image_paths if viewed_images.get(p)]
        else:
            image_items = list(viewed_images.items())

        for image_path, image_data in image_items:
            if not isinstance(image_data, dict):
                continue
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
                injected = (msg.additional_kwargs or {}).get("deerflow_injected")
                if injected == "view_image":
                    # Already added, don't add again
                    return False
                content_str = str(msg.content)
                if "Here are the images you've viewed" in content_str or "Here are the details of the images you've viewed" in content_str:
                    # Backward-compatible fallback for existing conversations
                    return False

        return True

    def _inject_image_message(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Internal helper to inject image details message.

        Args:
            state: Current state
            runtime: Runtime context

        Returns:
            State update with additional human message, or None if no update needed
        """
        if not self._should_inject_image_message(state):
            return None

        messages = state.get("messages", [])
        last_assistant_msg = self._get_last_assistant_message(messages)
        image_paths: list[str] | None = None
        if last_assistant_msg is not None:
            extracted = self._extract_view_image_paths(last_assistant_msg)
            image_paths = extracted or None

        # Create the image details message with text and image content
        image_content = self._create_image_details_message(state, runtime, image_paths=image_paths)

        # Create a new human message with mixed content (text + images)
        human_msg = HumanMessage(content=image_content, additional_kwargs={"deerflow_injected": "view_image"})

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
        return self._inject_image_message(state, runtime)

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
        return self._inject_image_message(state, runtime)

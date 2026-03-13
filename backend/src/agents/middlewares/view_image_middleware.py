"""Middleware for injecting image details into conversation before LLM call.

Key behaviors:
1. Only injects images from the MOST RECENT view_image call (not accumulated history)
2. Clears viewed_images from state after injection to prevent re-injection on next turn
3. This means each LLM call only sees the images it just viewed, not every image ever viewed
"""

import json
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from src.agents.thread_state import ViewedImageData


class ViewImageMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    viewed_images: NotRequired[dict[str, ViewedImageData] | None]


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    """Injects viewed images into LLM context, then clears them.

    Flow:
    1. Agent calls view_image → image stored in state.viewed_images
    2. Before next LLM call, this middleware injects the image as a HumanMessage
    3. Clears viewed_images so it's NOT re-injected on subsequent turns
    4. LLM sees only the images from THIS turn, not accumulated history

    This prevents context bloat: without clearing, 5 iterations would mean
    5 images injected on every subsequent LLM call.
    """

    state_schema = ViewImageMiddlewareState

    def _get_last_assistant_message(self, messages: list) -> AIMessage | None:
        """Get the last assistant message from the message list."""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg
        return None

    def _has_view_image_tool(self, message: AIMessage) -> bool:
        """Check if the assistant message contains view_image tool calls."""
        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return False
        return any(tool_call.get("name") == "view_image" for tool_call in message.tool_calls)

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        """Check if all tool calls in the assistant message have been completed."""
        if not hasattr(assistant_msg, "tool_calls") or not assistant_msg.tool_calls:
            return False

        tool_call_ids = {tool_call.get("id") for tool_call in assistant_msg.tool_calls if tool_call.get("id")}

        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False

        completed_tool_ids = set()
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and msg.tool_call_id:
                completed_tool_ids.add(msg.tool_call_id)

        return tool_call_ids.issubset(completed_tool_ids)

    def _extract_images_from_tool_messages(self, messages: list, assistant_msg: AIMessage) -> dict[str, ViewedImageData]:
        """Extract image data from ToolMessage content that contains __view_image__ JSON payloads.

        Args:
            messages: List of all messages
            assistant_msg: The assistant message containing view_image tool calls

        Returns:
            Dict of image_path -> {base64, mime_type}
        """
        images: dict[str, ViewedImageData] = {}
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return images

        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and data.get("__view_image__"):
                        image_path = data.get("image_path", "")
                        images[image_path] = {
                            "base64": data.get("base64", ""),
                            "mime_type": data.get("mime_type", "application/octet-stream"),
                        }
                except (json.JSONDecodeError, TypeError):
                    pass
        return images

    def _should_inject_image_message(self, state: ViewImageMiddlewareState) -> bool:
        """Determine if we should inject an image details message."""
        messages = state.get("messages", [])
        if not messages:
            return False

        last_assistant_msg = self._get_last_assistant_message(messages)
        if not last_assistant_msg:
            return False

        if not self._has_view_image_tool(last_assistant_msg):
            return False

        if not self._all_tools_completed(messages, last_assistant_msg):
            return False

        # Check if we've already added an image details message for this turn
        assistant_idx = messages.index(last_assistant_msg)
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                content_str = str(msg.content)
                if "Here are the images you've viewed" in content_str or "Here are the details of the images you've viewed" in content_str:
                    return False
        return True

    def _create_image_details_message(self, images: dict[str, ViewedImageData]) -> list[str | dict]:
        """Create a formatted message with viewed image details."""
        if not images:
            return ["No images have been viewed."]

        content_blocks: list[str | dict] = [{"type": "text", "text": "Here are the images you've viewed:"}]

        for image_path, image_data in images.items():
            mime_type = image_data.get("mime_type", "unknown")
            base64_data = image_data.get("base64", "")

            content_blocks.append({"type": "text", "text": f"\n- **{image_path}** ({mime_type})"})

            if base64_data:
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
                    }
                )

        return content_blocks

    def _strip_old_image_injections(self, messages: list) -> None:
        """Remove base64 image data from previously injected HumanMessages.

        After the LLM has seen the images once, the base64 data is no longer needed.
        Replace image_url blocks with text placeholders to free memory.
        """
        for msg in messages:
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                has_image_marker = any(
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and "Here are the images you've viewed" in block.get("text", "")
                    for block in msg.content
                )
                if has_image_marker:
                    # Replace content: keep text blocks, drop image_url blocks
                    cleaned = []
                    for block in msg.content:
                        if isinstance(block, dict) and block.get("type") == "image_url":
                            cleaned.append({"type": "text", "text": "[image data removed — already processed]"})
                        else:
                            cleaned.append(block)
                    msg.content = cleaned

    def _strip_base64_from_tool_messages(self, messages: list, assistant_msg: AIMessage) -> None:
        """Replace ToolMessage content containing __view_image__ JSON with a short summary.

        This prevents base64 image data from accumulating in the conversation history,
        since the data is only needed for the single LLM turn where the image is injected.
        """
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return

        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and data.get("__view_image__"):
                        image_path = data.get("image_path", "unknown")
                        msg.content = f"Image loaded: {image_path}"
                except (json.JSONDecodeError, TypeError):
                    pass

    def _inject_image_message(self, state: ViewImageMiddlewareState) -> dict | None:
        """Inject image details and clear viewed_images to prevent re-injection."""
        if not self._should_inject_image_message(state):
            return None

        messages = state.get("messages", [])
        last_assistant_msg = self._get_last_assistant_message(messages)
        if not last_assistant_msg:
            return None

        # Extract images from tool messages (new approach — avoids Command state conflicts)
        images = self._extract_images_from_tool_messages(messages, last_assistant_msg)

        # Also merge with any existing viewed_images from state (backwards compat)
        existing_images = state.get("viewed_images") or {}
        all_images = {**existing_images, **images}

        if not all_images:
            return None

        # Strip base64 data from ToolMessages now that we have extracted it.
        # This prevents the base64 from living in conversation history forever.
        self._strip_base64_from_tool_messages(messages, last_assistant_msg)

        # Also strip base64 from any previously injected image HumanMessages
        # so old images don't keep eating context window across turns.
        self._strip_old_image_injections(messages)

        image_content = self._create_image_details_message(all_images)
        human_msg = HumanMessage(content=image_content)

        print("[ViewImageMiddleware] Injecting image details message with images before LLM call")

        # Clear viewed_images after injection to prevent base64 data from
        # accumulating in state across turns. The empty dict triggers the
        # merge_viewed_images reducer's clear logic.
        return {"messages": [human_msg], "viewed_images": {}}

    def _cleanup_stale_images(self, state: ViewImageMiddlewareState) -> None:
        """Strip base64 from old image messages on every LLM call, not just view_image turns.

        This ensures that even if no new view_image is called, previously injected
        image data is cleaned up before the next model invocation.
        """
        messages = state.get("messages", [])
        if not messages:
            return
        self._strip_old_image_injections(messages)

        # Also strip any leftover __view_image__ JSON in ToolMessages from prior turns
        for msg in messages:
            if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and data.get("__view_image__"):
                        image_path = data.get("image_path", "unknown")
                        msg.content = f"Image loaded: {image_path}"
                except (json.JSONDecodeError, TypeError):
                    pass

    @override
    def before_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject image details before LLM call, then clear them (sync version)."""
        self._cleanup_stale_images(state)
        return self._inject_image_message(state)

    @override
    async def abefore_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject image details before LLM call, then clear them (async version)."""
        self._cleanup_stale_images(state)
        return self._inject_image_message(state)

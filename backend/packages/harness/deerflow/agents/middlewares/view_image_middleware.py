"""Middleware for injecting image details into the model request."""

import base64
import hashlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import override
from uuid import uuid4

from deerflow_extension_api import ContentKind, provenance_kwargs
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from deerflow.agents.thread_state import ThreadState
from deerflow.sandbox.lease import run_sync_lifecycle_operation

logger = logging.getLogger(__name__)

# Mirror the tool-side size cap as a defense-in-depth check. The tool
# enforces this at write time; the middleware re-checks at read time in
# case the file grew between view and injection.
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_IMAGE_CONTEXT_MESSAGE_ID_PREFIX = "view-image-context:"
_IMAGE_CONTEXT_MESSAGE_MARKER_KEY = "deerflow_view_image_context"


class ViewImageMiddlewareState(ThreadState):
    """Reuse the thread state so reducer-backed keys keep their annotations."""


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    """Injects image details into the model request when view_image tool calls have completed.

    This middleware:
    1. Wraps each LLM call
    2. Checks if the last assistant message contains view_image tool calls
    3. Verifies all tool calls in that message have been completed (have corresponding ToolMessages)
    4. If conditions are met, appends a human message with all viewed image details (including base64 data)
    5. Hands the augmented request to the model so it can see and analyze the images

    This enables the LLM to automatically receive and analyze images that were loaded via view_image tool,
    without requiring explicit user prompts to describe the images.

    Injection happens in ``wrap_model_call`` on purpose: the message exists only
    in ``ModelRequest.messages`` and is never returned as a state update, so no
    checkpoint carries the base64 payload and an interrupted run cannot strand it
    in history. Do not move this back to a ``before_model``/``after_model`` pair
    -- that writes the payload into state and can only take it out again
    afterwards (see #4267).
    """

    state_schema = ViewImageMiddlewareState

    @staticmethod
    def _is_image_context_message(message: object) -> bool:
        """Return whether a message is trusted transient image context."""
        return isinstance(message, HumanMessage) and bool(message.id) and message.id.startswith(_IMAGE_CONTEXT_MESSAGE_ID_PREFIX) and message.additional_kwargs.get(_IMAGE_CONTEXT_MESSAGE_MARKER_KEY) is True

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

    @staticmethod
    def _encode_image_bytes(
        image_bytes: bytes,
        mime_type: str,
        expected_size: int,
        expected_sha256: str | None = None,
    ) -> str | None:
        """Validate image bytes against recorded metadata and return a data URL."""
        current_size = len(image_bytes)
        if current_size != expected_size or current_size > _MAX_IMAGE_BYTES:
            return None
        if expected_sha256 is not None and hashlib.sha256(image_bytes).hexdigest() != expected_sha256:
            return None
        base64_data = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{base64_data}"

    @classmethod
    def _read_host_image_as_data_url(
        cls,
        actual_path: str,
        mime_type: str,
        expected_size: int,
        expected_sha256: str | None = None,
    ) -> str | None:
        """Read a validated host mirror and return a data URL, or None on failure.

        ``actual_path`` is server-set by ``view_image_tool`` and held in
        LangGraph-controlled state. The host path remains the compatibility path
        for local execution and older checkpoints. Provenance-aware checkpoints
        additionally verify the exact SHA-256 before a synchronized host copy can
        stand in for bytes from an earlier sandbox generation.
        """
        try:
            file_path = Path(actual_path)
            if not file_path.exists() or not file_path.is_file():
                return None
            current_size = file_path.stat().st_size
            if current_size != expected_size or current_size > _MAX_IMAGE_BYTES:
                return None
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            return cls._encode_image_bytes(
                image_bytes,
                mime_type,
                expected_size,
                expected_sha256,
            )
        except OSError:
            return None

    @classmethod
    def _read_image_as_data_url(
        cls,
        state: ViewImageMiddlewareState,
        image_path: str,
        actual_path: str,
        mime_type: str,
        expected_size: int,
        expected_sha256: str | None,
        source_sandbox_id: str | None,
    ) -> str | None:
        """Read the exact image bytes represented by ``viewed_images`` metadata.

        A live sandbox is authoritative only for metadata recorded from that same
        sandbox generation. If the thread now points at a replacement sandbox,
        the previous image can be reconstructed from the synchronized host mirror
        only when its SHA-256 exactly matches the bytes that ``view_image`` saw.
        Legacy metadata without a digest never authorizes this cross-generation
        fallback. When no live sandbox exists, the historical host compatibility
        path remains available (digest-checked when present).
        """
        from deerflow.sandbox.overwrite import unwrap_sandbox
        from deerflow.sandbox.sandbox_provider import get_sandbox_provider

        sandbox_state, _ = unwrap_sandbox(state.get("sandbox"))
        sandbox_id = sandbox_state.get("sandbox_id") if isinstance(sandbox_state, dict) else None
        sandbox = get_sandbox_provider().get(sandbox_id) if sandbox_id else None

        if sandbox is not None:
            provenance_matches_live = source_sandbox_id == sandbox_id
            provenance_identifies_other_source = expected_sha256 is not None and source_sandbox_id != sandbox_id

            if provenance_identifies_other_source:
                # The current client belongs to a different generation (or the
                # image was originally read from the host). Reproduce the exact
                # historical bytes rather than letting an unrelated same-path
                # file in the replacement sandbox win.
                if actual_path:
                    host_data_url = cls._read_host_image_as_data_url(
                        actual_path,
                        mime_type,
                        expected_size,
                        expected_sha256,
                    )
                    if host_data_url is not None:
                        return host_data_url
                try:
                    image_bytes = sandbox.download_file(image_path)
                except Exception:
                    logger.warning(
                        "Failed to recover viewed image %s from replacement sandbox %s",
                        image_path,
                        sandbox_id,
                        exc_info=True,
                    )
                    return None
                return cls._encode_image_bytes(
                    image_bytes,
                    mime_type,
                    expected_size,
                    expected_sha256,
                )

            if not provenance_matches_live and expected_sha256 is None:
                # A legacy checkpoint cannot prove which sandbox generation
                # supplied these bytes. Do not silently reinterpret historical
                # image context through a newly active remote filesystem.
                return None

            try:
                image_bytes = sandbox.download_file(image_path)
            except Exception:
                logger.warning("Failed to read viewed image %s from sandbox %s", image_path, sandbox_id, exc_info=True)
                return None
            return cls._encode_image_bytes(
                image_bytes,
                mime_type,
                expected_size,
                expected_sha256,
            )

        if not actual_path:
            return None
        return cls._read_host_image_as_data_url(
            actual_path,
            mime_type,
            expected_size,
            expected_sha256,
        )

    def _create_image_details_message(self, state: ViewImageMiddlewareState) -> list[str | dict]:
        """Create a formatted message with all viewed image details.

        Reads image files on-demand from the active sandbox when available and
        encodes them as base64 for the model. The base64 data is NOT persisted in
        state -- only lightweight metadata (path, mime_type, size, digest, and
        source sandbox id when applicable) is stored in ``viewed_images``,
        avoiding large duplicate payloads across every checkpoint (see #4138).

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
            actual_path = image_data.get("actual_path", "")
            expected_size = image_data.get("size", 0)
            expected_sha256 = image_data.get("sha256")
            source_sandbox_id = image_data.get("source_sandbox_id")

            # Add text description
            content_blocks.append({"type": "text", "text": f"\n- **{image_path}** ({mime_type})"})

            # Read the image file on-demand and encode as base64 for the model
            data_url = self._read_image_as_data_url(
                state,
                image_path,
                actual_path,
                mime_type,
                expected_size,
                expected_sha256 if isinstance(expected_sha256, str) else None,
                source_sandbox_id if isinstance(source_sandbox_id, str) else None,
            )
            if data_url:
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    }
                )
            else:
                content_blocks.append({"type": "text", "text": f"  (file unavailable or changed: {image_path})"})

        return content_blocks

    def _should_inject_image_message(self, messages: list[AnyMessage]) -> bool:
        """Determine if we should append an image details message.

        Args:
            messages: Messages about to be sent to the model

        Returns:
            True if we should append the message
        """
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

        # Skip when image details are already present. ``_inject`` has stripped
        # this middleware's own messages by now, so what remains are unmarked
        # ones from checkpoints written before the marker existed -- those cannot
        # be told apart from user-authored text with certainty, so they are left
        # in place and simply not duplicated.
        assistant_idx = messages.index(last_assistant_msg)
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                content_str = str(msg.content)
                if "Here are the images you've viewed" in content_str or "Here are the details of the images you've viewed" in content_str:
                    # Already added, don't add again
                    return False

        return True

    @staticmethod
    def _create_image_context_message(content: list[str | dict]) -> HumanMessage:
        """Create an identifiable, model-only image context message."""
        return HumanMessage(
            id=f"{_IMAGE_CONTEXT_MESSAGE_ID_PREFIX}{uuid4().hex}",
            content=content,
            additional_kwargs={
                "hide_from_ui": True,
                _IMAGE_CONTEXT_MESSAGE_MARKER_KEY: True,
                **provenance_kwargs(ContentKind.IMAGE_PAYLOAD, "view_image"),
            },
        )

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Rebuild the request's image context from ``viewed_images``.

        Args:
            request: The pending model request

        Returns:
            A request whose messages carry exactly the image context this call
            warrants -- one freshly built message, or none -- leaving the
            original request untouched when there is nothing to change
        """
        # This middleware owns the image context and rebuilds it from
        # ``viewed_images`` on every call, so drop any copy already in the list.
        # A thread checkpointed by the earlier before_model/after_model pair can
        # carry one that reached state but was never removed (the run died during
        # the model call); left in place it would ride along in every later
        # request for the life of the thread. Matching requires both the reserved
        # ID prefix and the server-owned marker, and Gateway strips that marker
        # from client input, so this can never drop a user-authored message.
        messages = [message for message in request.messages if not self._is_image_context_message(message)]
        dropped_stranded = len(messages) != len(request.messages)
        if dropped_stranded:
            logger.debug("Dropping %d stranded image context message(s) from the model request", len(request.messages) - len(messages))

        if not self._should_inject_image_message(messages):
            return request.override(messages=messages) if dropped_stranded else request

        # Mixed content (text + images) for the model only, so hide it from the
        # chat UI and IM channels (matches the other middleware-injected context
        # messages) even though it never leaves this request.
        image_content = self._create_image_details_message(request.state or {})
        logger.debug("Injecting image details message with images into the model request")

        return request.override(messages=[*messages, self._create_image_context_message(image_content)])

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        # Sync injection executes inline on this call stack. There is no detached
        # worker to drain: an outer sandbox lease cannot reach its finally/release
        # boundary until this blocking read returns or raises.
        return handler(self._inject(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        # Image reads + base64 encoding can be slow (up to 20MB), so offload the
        # blocking work without allowing cancellation to outlive a sandbox
        # client operation. The outer run lease may release the client as soon as
        # cancellation propagates.
        injected_request = await run_sync_lifecycle_operation(self._inject, request)
        return await handler(injected_request)

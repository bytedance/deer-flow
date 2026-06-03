"""Middleware to fix dangling tool calls in message history.

A dangling tool call occurs when an AIMessage contains tool_calls but there are
no corresponding ToolMessages in the history (e.g., due to user interruption or
request cancellation). This causes LLM errors due to incomplete message format.

This middleware intercepts the model call to detect and patch such gaps by
inserting synthetic ToolMessages with an error indicator immediately after the
AIMessage that made the tool calls, ensuring correct message ordering.

Note: Uses wrap_model_call instead of before_model to ensure patches are inserted
at the correct positions (immediately after each dangling AIMessage), not appended
to the end of the message list as before_model + add_messages reducer would do.
"""

import json
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

# Workaround for issue #2894: malformed write_file calls can carry huge Markdown
# payloads in invalid tool-call args. Keep recovery error details short so the
# synthetic ToolMessage does not echo large or malformed content back to the model.
_MAX_RECOVERY_ERROR_DETAIL_LEN = 500


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Inserts placeholder ToolMessages for dangling tool calls before model invocation.

    Scans the message history for AIMessages whose tool_calls lack corresponding
    ToolMessages, and injects synthetic error responses immediately after the
    offending AIMessage so the LLM receives a well-formed conversation.
    """

    @staticmethod
    def _message_tool_calls(msg) -> list[dict]:
        """Return normalized tool calls from structured fields or raw provider payloads.

        LangChain stores malformed provider function calls in ``invalid_tool_calls``.
        They do not execute, but provider adapters may still serialize enough of
        the call id/name back into the next request that strict OpenAI-compatible
        validators expect a matching ToolMessage. Treat them as dangling calls so
        the next model request stays well-formed and the model sees a recoverable
        tool error instead of another provider 400.
        """
        normalized: list[dict] = []

        tool_calls = getattr(msg, "tool_calls", None) or []
        normalized.extend(list(tool_calls))

        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        if not tool_calls:
            for raw_tc in raw_tool_calls:
                if not isinstance(raw_tc, dict):
                    continue

                function = raw_tc.get("function")
                name = raw_tc.get("name")
                if not name and isinstance(function, dict):
                    name = function.get("name")

                args = raw_tc.get("args", {})
                if not args and isinstance(function, dict):
                    raw_args = function.get("arguments")
                    if isinstance(raw_args, str):
                        try:
                            parsed_args = json.loads(raw_args)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            parsed_args = {}
                        args = parsed_args if isinstance(parsed_args, dict) else {}

                normalized.append(
                    {
                        "id": raw_tc.get("id"),
                        "name": name or "unknown",
                        "args": args if isinstance(args, dict) else {},
                    }
                )

        for invalid_tc in getattr(msg, "invalid_tool_calls", None) or []:
            if not isinstance(invalid_tc, dict):
                continue
            normalized.append(
                {
                    "id": invalid_tc.get("id"),
                    "name": invalid_tc.get("name") or "unknown",
                    "args": {},
                    "invalid": True,
                    "error": invalid_tc.get("error"),
                }
            )

        return normalized

    @staticmethod
    def _synthetic_tool_message_content(tool_call: dict) -> str:
        if tool_call.get("invalid"):
            name = tool_call.get("name")
            error = tool_call.get("error")
            error_text = error[:_MAX_RECOVERY_ERROR_DETAIL_LEN] if isinstance(error, str) and error else ""
            # Workaround for issue #2894: malformed write_file calls can carry huge Markdown
            # payloads in invalid tool-call args. Keep recovery guidance actionable without
            # echoing large or malformed content back to the model.
            if name == "write_file":
                details = f" Parser error: {error_text}" if error_text else ""
                return (
                    "[write_file failed before execution: the tool-call arguments were not valid JSON, "
                    "so no file was written. This often happens when the model tries to write a very "
                    "large Markdown file in a single tool call, especially when `content` contains "
                    "unescaped quotes, inline JSON, backslashes, or code fences. Do not retry the same "
                    "large `write_file` payload for this artifact; provide the report/content directly "
                    "as normal assistant text in your next response. If a file write is still needed "
                    f"later, split the file into smaller sections instead of one large payload.{details}]"
                )
            if error_text:
                return f"[Tool call could not be executed because its arguments were invalid: {error_text}]"
            return "[Tool call could not be executed because its arguments were invalid.]"
        return "[Tool call was interrupted and did not return a result.]"

    def _build_patched_messages(self, messages: list) -> list | None:
        """Return messages with tool results grouped after their tool-call AIMessage.

        This normalizes model-bound causal order before provider serialization while
        preserving already-valid transcripts unchanged.
        """
        tool_messages_by_id: dict[str, deque[ToolMessage]] = defaultdict(deque)
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_messages_by_id[msg.tool_call_id].append(msg)

        tool_call_ids: set[str] = set()
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id:
                    tool_call_ids.add(tc_id)

        patched: list = []
        patch_count = 0
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.tool_call_id in tool_call_ids:
                continue

            patched.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue

            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if not tc_id:
                    continue

                tool_msg_queue = tool_messages_by_id.get(tc_id)
                existing_tool_msg = tool_msg_queue.popleft() if tool_msg_queue else None
                if existing_tool_msg is not None:
                    patched.append(existing_tool_msg)
                else:
                    patched.append(
                        ToolMessage(
                            content=self._synthetic_tool_message_content(tc),
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patch_count += 1

        if patched == messages:
            return None

        if patch_count:
            logger.warning(f"Injecting {patch_count} placeholder ToolMessage(s) for dangling tool calls")
        return patched

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)

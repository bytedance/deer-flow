"""OpenAI-compatible Gemini model with thought-signature replay support.

Gemini's OpenAI-compatible API returns a thought signature alongside function
calls and requires clients to submit that signature unchanged in subsequent
requests. LangChain normalizes tool calls for execution, which can omit this
provider-specific metadata when the assistant message is serialized again.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

_GEMINI_TOOL_CALL_METADATA = ("extra_content", "thought_signature")


class PatchedChatOpenAI(ChatOpenAI):
    """ChatOpenAI variant that replays Gemini function-call signatures."""

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        source_messages = _get_messages(input_)
        assistant_messages = [
            message for message in source_messages if isinstance(message, AIMessage)
        ]
        outgoing_messages = [
            message
            for message in payload.get("messages", [])
            if message.get("role") == "assistant"
        ]

        for source, outgoing in zip(
            assistant_messages, outgoing_messages, strict=False
        ):
            _restore_tool_call_metadata(source, outgoing)

        return payload


def _get_messages(input_: Any) -> list[Any]:
    if isinstance(input_, (list, tuple)):
        return list(input_)

    to_messages = getattr(input_, "to_messages", None)
    if callable(to_messages):
        return list(to_messages())

    return []


def _restore_tool_call_metadata(
    source: AIMessage, outgoing: dict[str, Any]
) -> None:
    raw_calls = source.additional_kwargs.get("tool_calls")
    outgoing_calls = outgoing.get("tool_calls")
    if not isinstance(raw_calls, list) or not isinstance(outgoing_calls, list):
        return

    raw_calls_by_id = {
        call.get("id"): call
        for call in raw_calls
        if isinstance(call, dict) and call.get("id") is not None
    }

    for index, outgoing_call in enumerate(outgoing_calls):
        if not isinstance(outgoing_call, dict):
            continue

        raw_call = raw_calls_by_id.get(outgoing_call.get("id"))
        if raw_call is None and index < len(raw_calls):
            raw_call = raw_calls[index]
        if not isinstance(raw_call, dict):
            continue

        for key in _GEMINI_TOOL_CALL_METADATA:
            if key in raw_call:
                outgoing_call[key] = deepcopy(raw_call[key])

"""Invalidate provider continuation after rewriting local conversation history."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage


def without_response_chain_id(message: Any) -> Any:
    """Copy an AI message without its OpenAI ``resp_`` continuation ID.

    Callers must apply this to every retained message after changing history:
    the adapter searches backward for any response ID, not just the latest one.
    Message IDs, content and other metadata remain intact; unrelated messages
    pass through by identity.
    """
    if not isinstance(message, AIMessage):
        return message
    response_metadata = message.response_metadata or {}
    response_id = response_metadata.get("id")
    if not (isinstance(response_id, str) and response_id.startswith("resp_")):
        return message
    return message.model_copy(update={"response_metadata": {key: value for key, value in response_metadata.items() if key != "id"}})

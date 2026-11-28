"""The text-only message contract for a Chat run, shared by Gateway and harness."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from deerflow.agents.interaction_policy import ASK_CLARIFICATION_TOOL_NAME

CHAT_MODE_KEY = "deerflow_mode"
_FILE_FIELDS = ("files", "attachments", "artifacts", "audio", "images", "resource_links")
_TEXT_TYPES = ("text", "input_text", "output_text")
_AI_PROTOCOL_TYPES = ("reasoning", "thinking", "redacted_thinking", "tool_call", "tool_call_chunk", "tool_use", "function_call")


def _is_chat_block(message: BaseMessage, block: Any) -> bool:
    if isinstance(block, str):
        return True
    if not isinstance(block, dict):
        return False
    kind = block.get("type", "text")
    if kind in _TEXT_TYPES:
        return isinstance(block.get("text"), str)
    if isinstance(message, AIMessage):
        return kind in _AI_PROTOCOL_TYPES
    return isinstance(message, ToolMessage) and kind == "json"


def has_attachment_fields(value: object) -> bool:
    return isinstance(value, Mapping) and any(value.get(key) for key in _FILE_FIELDS)


def has_chat_attachment(message: BaseMessage) -> bool:
    if has_attachment_fields(message.additional_kwargs) or (isinstance(message, ToolMessage) and has_attachment_fields(message.artifact)):
        return True
    return isinstance(message.content, list) and any(not _is_chat_block(message, block) for block in message.content)


def chat_message[MessageT: BaseMessage](message: MessageT, *, mark_mode: bool | None = None) -> MessageT:
    """Project a message without changing the checkpoint or cached tool result."""
    updates: dict[str, Any] = {}
    if isinstance(message.content, list):
        blocks = [block for block in message.content if _is_chat_block(message, block)]
        if len(blocks) != len(message.content):
            updates["content"] = blocks or "Attachment omitted in Chat mode."

    kwargs = {key: value for key, value in message.additional_kwargs.items() if key not in _FILE_FIELDS}
    if mark_mode is not None:
        if mark_mode:
            kwargs[CHAT_MODE_KEY] = "chat"
        else:
            kwargs.pop(CHAT_MODE_KEY, None)
    if kwargs != message.additional_kwargs:
        updates["additional_kwargs"] = kwargs
    if isinstance(message, ToolMessage) and message.artifact is not None:
        artifact = message.artifact if isinstance(message.artifact, Mapping) else {}
        if not message.content and artifact.get("structured_content") is not None:
            updates["content"] = json.dumps(artifact["structured_content"], ensure_ascii=False)
        # Citations and interactive clarification cards carry text metadata.
        # Only the host clarification tool produces a pending question.
        retained = {key: value for key, value in artifact.items() if key in ("knowledge_sources", "knowledge_sources_version", "retrieval_sources")}
        question = artifact.get("human_input")
        if message.name == ASK_CLARIFICATION_TOOL_NAME and isinstance(question, Mapping) and question.get("kind") == "human_input_request" and question.get("source") == ASK_CLARIFICATION_TOOL_NAME:
            retained["human_input"] = question
        if not retained or retained != artifact:
            updates["artifact"] = retained or None
    return message.model_copy(update=updates) if updates else message


def chat_stream_chunk(chunk: Any, marked_message_ids: set[str]) -> Any:
    """Drop provider media and send the mode once per message, before SDK concatenation."""
    if not (isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], BaseMessage)):
        return chunk
    message, metadata = chunk
    mark_mode = None
    if isinstance(message, (AIMessage, ToolMessage)) or message.additional_kwargs.get(CHAT_MODE_KEY) == "chat":
        mark_mode = message.id is not None and message.id not in marked_message_ids
        if mark_mode:
            marked_message_ids.add(message.id)
    return chat_message(message, mark_mode=mark_mode), metadata

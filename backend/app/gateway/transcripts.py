"""Canonical chat transcript storage.

The LangGraph checkpoint state is model context.  It can be summarized,
trimmed, or otherwise rewritten by middlewares.  The UI transcript needs a
separate durable record so conversation history survives context compression.
"""

from __future__ import annotations

import json
import time
from typing import Any

from deerflow.runtime import serialize_lc_object

TRANSCRIPTS_NS: tuple[str, ...] = ("thread_transcripts",)

_SUMMARY_MARKER_KEY = "deerflow_conversation_summary"
_LEGACY_SUMMARY_PREFIX = "Here is a summary of the conversation to date:"


def _message_fingerprint(message: dict[str, Any]) -> str:
    """Return a stable identity for messages that do not have ids yet."""

    identity_payload = {
        "type": message.get("type"),
        "name": message.get("name"),
        "tool_call_id": message.get("tool_call_id"),
        "content": message.get("content"),
    }
    return json.dumps(identity_payload, sort_keys=True, default=str, ensure_ascii=False)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _is_visible_transcript_message(message: dict[str, Any]) -> bool:
    additional_kwargs = message.get("additional_kwargs")
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}

    if additional_kwargs.get("hide_from_ui") is True:
        return False
    if additional_kwargs.get(_SUMMARY_MARKER_KEY) is True:
        return False

    # Backward compatibility for summary messages created before they were
    # explicitly tagged by DeerFlowSummarizationMiddleware.
    if message.get("type") == "human" and _message_text(message).startswith(_LEGACY_SUMMARY_PREFIX):
        return False

    return message.get("type") in {"human", "ai", "tool"}


def normalize_transcript_messages(messages: list[Any] | tuple[Any, ...] | None) -> list[dict[str, Any]]:
    """Serialize and filter messages before writing them to the transcript."""
    normalized: list[dict[str, Any]] = []
    for raw_message in messages or []:
        message = serialize_lc_object(raw_message)
        if isinstance(message, dict) and _is_visible_transcript_message(message):
            normalized.append(message)
    return normalized


async def get_thread_transcript(store: Any, thread_id: str) -> list[dict[str, Any]]:
    """Read the canonical transcript for *thread_id* from the Store."""
    item = await store.aget(TRANSCRIPTS_NS, thread_id)
    if item is None:
        return []
    value = item.value if isinstance(item.value, dict) else {}
    messages = value.get("messages", [])
    return messages if isinstance(messages, list) else []


async def append_thread_transcript_messages(
    store: Any,
    thread_id: str,
    messages: list[Any] | tuple[Any, ...] | None,
) -> list[dict[str, Any]]:
    """Append visible messages to the canonical transcript, deduplicating by identity."""
    incoming = normalize_transcript_messages(messages)
    if not incoming:
        return await get_thread_transcript(store, thread_id)

    existing = await get_thread_transcript(store, thread_id)
    seen_ids = {str(message["id"]) for message in existing if isinstance(message, dict) and message.get("id")}
    seen_fingerprints = {_message_fingerprint(message) for message in existing if isinstance(message, dict)}
    changed = False

    for message in incoming:
        message_id = message.get("id")
        fingerprint = _message_fingerprint(message)
        if message_id and str(message_id) in seen_ids:
            continue
        if fingerprint in seen_fingerprints:
            continue
        if message_id:
            seen_ids.add(str(message_id))
        seen_fingerprints.add(fingerprint)
        existing.append(message)
        changed = True

    if changed:
        await store.aput(
            TRANSCRIPTS_NS,
            thread_id,
            {
                "thread_id": thread_id,
                "messages": existing,
                "updated_at": time.time(),
            },
        )

    return existing


async def delete_thread_transcript(store: Any, thread_id: str) -> None:
    """Delete a thread transcript if the active Store supports deletion."""
    delete = getattr(store, "adelete", None)
    if delete is None:
        return
    await delete(TRANSCRIPTS_NS, thread_id)

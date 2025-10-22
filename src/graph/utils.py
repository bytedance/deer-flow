# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Any

ASSISTANT_SPEAKER_NAMES = {
    "coordinator",
    "planner",
    "researcher",
    "coder",
    "reporter",
    "background_investigator",
}


def get_message_content(message: Any) -> str:
    """Extract message content from dict or LangChain message."""
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def is_user_message(message: Any) -> bool:
    """Return True if the message originated from the end user."""
    if isinstance(message, dict):
        role = (message.get("role") or "").lower()
        if role in {"user", "human"}:
            return True
        if role in {"assistant", "system"}:
            return False
        name = (message.get("name") or "").lower()
        if name and name in ASSISTANT_SPEAKER_NAMES:
            return False
        return role == "" and name not in ASSISTANT_SPEAKER_NAMES

    message_type = (getattr(message, "type", "") or "").lower()
    name = (getattr(message, "name", "") or "").lower()
    if message_type == "human":
        return not (name and name in ASSISTANT_SPEAKER_NAMES)

    role_attr = getattr(message, "role", None)
    if isinstance(role_attr, str) and role_attr.lower() in {"user", "human"}:
        return True

    additional_role = getattr(message, "additional_kwargs", {}).get("role")
    if isinstance(additional_role, str) and additional_role.lower() in {
        "user",
        "human",
    }:
        return True

    return False


def get_latest_user_message(messages: list[Any]) -> tuple[Any, str]:
    """Return the latest user-authored message and its content."""
    for message in reversed(messages or []):
        if is_user_message(message):
            content = get_message_content(message)
            if content:
                return message, content
    return None, ""


def build_clarified_topic_from_history(
    clarification_history: list[str],
) -> tuple[str, list[str]]:
    """Construct clarified topic string from an ordered clarification history."""
    sequence = [item for item in clarification_history if item]
    if not sequence:
        return "", []
    if len(sequence) == 1:
        return sequence[0], sequence
    head, *tail = sequence
    clarified_string = f"{head} - {', '.join(tail)}"
    return clarified_string, sequence


def reconstruct_clarification_history(
    messages: list[Any],
    fallback_history: list[str] | None = None,
    base_topic: str = "",
) -> list[str]:
    """Rebuild clarification history from user-authored messages, with fallback.

    Args:
        messages: Conversation messages in chronological order.
        fallback_history: Optional existing history to use if no user messages found.
        base_topic: Optional topic to use when no user messages are available.

    Returns:
        A cleaned clarification history containing unique consecutive user contents.
    """
    sequence: list[str] = []
    for message in messages or []:
        if not is_user_message(message):
            continue
        content = get_message_content(message)
        if not content:
            continue
        if sequence and sequence[-1] == content:
            continue
        sequence.append(content)

    if sequence:
        return sequence

    fallback = [item for item in (fallback_history or []) if item]
    if fallback:
        return fallback

    base_topic = (base_topic or "").strip()
    return [base_topic] if base_topic else []

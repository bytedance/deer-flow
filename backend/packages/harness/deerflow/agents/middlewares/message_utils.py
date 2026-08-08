"""Shared message-list helpers for agent middlewares."""

from __future__ import annotations

from langchain_core.messages import SystemMessage


def insert_after_leading_system_messages(messages: list, injected: list) -> list:
    """Insert messages right after the leading run of SystemMessages.

    Context injections belong after the system prompt (instructions first,
    background context second) and before the conversation — never ahead of
    system messages (provider/protocol assumption) and never appended at the
    tail (would displace the latest turn and read as tool output).
    """
    index = 0
    while index < len(messages) and isinstance(messages[index], SystemMessage):
        index += 1
    return [*messages[:index], *injected, *messages[index:]]

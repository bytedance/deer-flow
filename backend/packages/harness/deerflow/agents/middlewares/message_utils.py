"""Shared message-list helpers for agent middlewares."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.agents.human_input import read_human_input_response

_SUMMARY_MESSAGE_NAME = "summary"


def is_genuine_user_message(message: object) -> bool:
    """Return True for real user messages, excluding system-injected HumanMessages.

    ``hide_from_ui`` is also used by hidden UI replies from HumanInputCard, so
    only skip hidden HumanMessages that do not carry a valid user response.
    """
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui") and read_human_input_response(message.additional_kwargs) is None:
        return False
    return True


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

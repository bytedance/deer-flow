from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from langchain_core.messages import HumanMessage

ORIGINAL_USER_CONTENT_KEY = "original_user_content"
SUMMARY_MESSAGE_NAME = "summary"
SUBAGENT_RESULT_MESSAGE_NAME = "subagent-result"

#: Server-owned mark the Gateway stamps on an untrusted caller's message when it
#: carries a framework marker (``hide_from_ui``, a ``summary`` name) that would
#: otherwise make the input guardrail skip it.  The marker keeps doing its
#: presentation job — those messages stay hidden from the transcript — while this
#: tells :func:`requires_input_sanitization` the content still came from outside
#: the trust boundary.  Stripping the marker instead would unhide three
#: legitimate frontend senders (quoted context, sidecar context, agent save).
UNTRUSTED_INPUT_KEY = "untrusted_input"

#: Server-owned mark on history copied in from someone else's conversation; the
#: value names the source (``"share"``).  The model still sees the copied turns,
#: but memory capture skips them: the importer did not say them, and extraction
#: would otherwise record the other person's statements as the importer's facts.
IMPORTED_HISTORY_KEY = "deerflow_imported_history"

#: Server-owned thread-state channel set on a thread whose history was copied
#: from someone else's conversation; the value names the source (``"share"``).
#: It lives in state rather than thread metadata so that every checkpoint, a
#: compacted head and a branch carry it: compaction removes the copied messages
#: and their marks, and memory capture must still know the thread is a copy.
IMPORTED_HISTORY_CHANNEL = "imported_history"

#: :data:`IMPORTED_HISTORY_CHANNEL` value for a copy whose copied turns could
#: not be told apart from the owner's: the history the import wrote is no longer
#: readable. Memory capture skips such a thread rather than guess.
IMPORTED_HISTORY_UNRESOLVED = "unresolved"


def without_imported_history(messages: list[Any]) -> list[Any]:
    """Drop messages carrying :data:`IMPORTED_HISTORY_KEY`; any truthy value counts."""
    kept = []
    for message in messages:
        kwargs = getattr(message, "additional_kwargs", None)
        if isinstance(kwargs, Mapping) and kwargs.get(IMPORTED_HISTORY_KEY):
            continue
        kept.append(message)
    return kept


#: Mark on queued memory copies, never on graph state: the conversation they
#: come from continues history copied from someone else. An assistant reply can
#: restate that person's details, so extraction must not read them as the user's.
FOLLOWS_IMPORTED_HISTORY_KEY = "deerflow_follows_imported_history"


def own_messages_for_memory(messages: list[Any], imported_history: object = None) -> list[Any]:
    """Drop imported history and mark the remaining copies when the thread is a copy.

    *imported_history* is the thread's :data:`IMPORTED_HISTORY_CHANNEL` value.
    The thread also counts as a copy when a message carries the import mark,
    which covers state written before the channel existed. Nothing is
    returned for :data:`IMPORTED_HISTORY_UNRESOLVED`.
    """
    if imported_history == IMPORTED_HISTORY_UNRESOLVED:
        return []
    own = without_imported_history(messages)
    is_copy = len(own) != len(messages) or bool(imported_history)
    if not is_copy:
        return own
    return [message.model_copy(update={"additional_kwargs": {**message.additional_kwargs, FOLLOWS_IMPORTED_HISTORY_KEY: True}}) for message in own]


#: Suffix ``DynamicContextMiddleware``'s ID-swap gives the real user message; the
#: reminder SystemMessage takes the original id so ``add_messages`` can replace it
#: in place.  It lives here rather than beside the middleware because the message
#: identity rule in ``deerflow.runtime.events.message_identity`` needs it too, and
#: importing the middleware from there closes a cycle
#: (middleware -> deerflow.runtime -> worker -> events -> middleware).
INJECTED_USER_MESSAGE_ID_SUFFIX = "__user"


def strip_injected_user_message_id_suffix(message_id: str | None) -> str | None:
    """Return the id *message_id* had before the reminder ID-swap.

    Replaying a persisted user turn must feed the graph the id the client
    originally sent: a ``{id}__user`` message is skipped as an injection target,
    so replaying one into a state that has no reminder yet silently drops the
    date and memory block for that turn.
    """

    if isinstance(message_id, str) and message_id.endswith(INJECTED_USER_MESSAGE_ID_SUFFIX):
        return message_id[: -len(INJECTED_USER_MESSAGE_ID_SUFFIX)] or message_id
    return message_id


def message_content_to_text(content: Any) -> str:
    """Extract text from LangChain message content shapes."""
    if content is None:
        # ``str(None)`` is the truthy literal ``"None"``, so a content-less message
        # would survive every downstream ``text if text else ...`` fallback and be
        # reported as a real answer.
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def message_to_text(message: Any, *, text_attribute_fallback: bool = False) -> str:
    """Extract display text from a whole message (``BaseMessage`` or dict-shaped).

    Reads ``content`` from either an attribute (``BaseMessage``) or a mapping key
    (``run_events`` rows are dicts), then walks the mixed ``content`` shapes:
    plain string; a list of string / ``{"text": ...}`` / nested ``{"content": ...}``
    blocks joined without a separator; or a mapping with a ``text``/``content`` key.
    Set ``text_attribute_fallback=True`` to fall back to ``message.text`` when
    content yields nothing (matches ``RunJournal._message_text``).

    Unlike :func:`message_content_to_text` (which takes raw ``content`` and joins
    list blocks with newlines), this keeps the no-separator join and the broader
    shape handling that several call sites had each reimplemented.
    """
    content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    nested = block.get("content")
                    if isinstance(nested, str):
                        parts.append(nested)
        return "".join(parts)
    if isinstance(content, Mapping):
        for key in ("text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    if text_attribute_fallback:
        text = getattr(message, "text", None)
        if isinstance(text, str):
            return text
    return ""


def get_original_user_content_text(content: Any, additional_kwargs: Mapping[str, Any] | None) -> str:
    """Return pre-middleware user text when available, otherwise content text."""
    original_content = (additional_kwargs or {}).get(ORIGINAL_USER_CONTENT_KEY)
    if isinstance(original_content, str):
        return original_content
    return message_content_to_text(content)


def restore_original_human_message(message: HumanMessage) -> HumanMessage:
    """Build the UI-facing copy of a model-sanitized human message.

    Input middleware intentionally keeps the original user text in
    ``additional_kwargs`` while replacing the model-facing text with transport
    wrappers and other context.  Run-event history must persist the original
    text without mutating the message that is actually sent to the model.

    Mixed content is already normalized by the sanitization middleware to a
    single text block.  For defensive compatibility, multiple current text
    blocks are collapsed at the first text position while every non-text block
    retains its value and relative order.
    """
    original_content = message.additional_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
    if not isinstance(original_content, str):
        return message

    additional_kwargs = dict(message.additional_kwargs)
    additional_kwargs.pop(ORIGINAL_USER_CONTENT_KEY, None)

    content = message.content
    if isinstance(content, str):
        restored_content: str | list = original_content
    elif isinstance(content, list):
        restored_content = []
        restored_text = False
        for block in content:
            is_string_text = isinstance(block, str)
            is_mapping_text = isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)
            if not is_string_text and not is_mapping_text:
                restored_content.append(block)
                continue
            if restored_text:
                continue
            if is_mapping_text:
                restored_content.append({**block, "text": original_content})
            else:
                restored_content.append(original_content)
            restored_text = True
        if not restored_text:
            restored_content.insert(0, {"type": "text", "text": original_content})
    else:
        restored_content = original_content

    return message.model_copy(
        update={
            # Pydantic deep-copies the original model for ``deep=True``, but
            # applies values supplied through ``update`` without copying them.
            # Keep the persisted/UI copy fully isolated from the model-facing
            # message, including nested image/file blocks and metadata.
            "content": deepcopy(restored_content),
            "additional_kwargs": deepcopy(additional_kwargs),
        },
        deep=True,
    )


def is_real_user_message(message: object) -> bool:
    """Return whether ``message`` is a real user-authored HumanMessage.

    Middleware-injected hidden HumanMessages and summarization markers should not
    drive user-intent features such as slash-skill activation or MCP routing.
    """
    if not isinstance(message, HumanMessage):
        return False
    if message.name == SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui"):
        return False
    return True

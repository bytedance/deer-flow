"""Structured human-input message metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

HUMAN_INPUT_RESPONSE_KEY = "human_input_response"


class HumanInputTextResponse(TypedDict):
    version: Literal[1]
    kind: Literal["human_input_response"]
    source: str
    request_id: str
    response_kind: Literal["text"]
    value: str


class HumanInputOptionResponse(TypedDict):
    version: Literal[1]
    kind: Literal["human_input_response"]
    source: str
    request_id: str
    response_kind: Literal["option"]
    option_id: str
    value: str


HumanInputResponse = HumanInputTextResponse | HumanInputOptionResponse


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def read_human_input_response(additional_kwargs: Mapping[str, object] | None) -> HumanInputResponse | None:
    """Read a valid human-input response payload from message metadata."""
    if not additional_kwargs:
        return None
    raw = additional_kwargs.get(HUMAN_INPUT_RESPONSE_KEY)
    if not isinstance(raw, Mapping):
        return None
    if raw.get("version") != 1 or raw.get("kind") != "human_input_response":
        return None

    source = _non_empty_string(raw.get("source"))
    request_id = _non_empty_string(raw.get("request_id"))
    value = _non_empty_string(raw.get("value"))
    if source is None or request_id is None or value is None:
        return None

    response_kind = raw.get("response_kind")
    if response_kind == "text":
        return {
            "version": 1,
            "kind": "human_input_response",
            "source": source,
            "request_id": request_id,
            "response_kind": "text",
            "value": value,
        }
    if response_kind == "option":
        option_id = _non_empty_string(raw.get("option_id"))
        if option_id is None:
            return None
        return {
            "version": 1,
            "kind": "human_input_response",
            "source": source,
            "request_id": request_id,
            "response_kind": "option",
            "option_id": option_id,
            "value": value,
        }
    return None


def _message_type(message: Any) -> str | None:
    if isinstance(message, Mapping):
        msg_type = message.get("type") or message.get("role")
    else:
        msg_type = getattr(message, "type", None) or getattr(message, "role", None)
    return msg_type if isinstance(msg_type, str) else None


def extract_unanswered_human_input_request(messages: Sequence[Any] | None) -> dict[str, str] | None:
    """Return the trailing unanswered ``human_input_request`` from *messages*, or ``None``.

    ``ask_clarification`` and structured human-input tool interrupts place the
    request in a ``ToolMessage`` artifact and route the graph to ``END``, so an
    active prompt sits in the trailing run of tool messages. Once the user
    replies (with a structured ``human_input_response`` or any later non-tool
    turn), the request is no longer pending.
    """
    if not messages:
        return None

    answered_request_ids: set[str] = set()
    for message in messages:
        additional_kwargs = message.get("additional_kwargs") if isinstance(message, Mapping) else getattr(message, "additional_kwargs", None)
        response = read_human_input_response(additional_kwargs if isinstance(additional_kwargs, Mapping) else None)
        if response is not None:
            answered_request_ids.add(response["request_id"])

    for message in reversed(messages):
        if _message_type(message) != "tool":
            return None
        artifact = message.get("artifact") if isinstance(message, Mapping) else getattr(message, "artifact", None)
        human_input = artifact.get("human_input") if isinstance(artifact, Mapping) else None
        if not isinstance(human_input, Mapping) or human_input.get("kind") != "human_input_request":
            continue
        msg_id = message.get("id") if isinstance(message, Mapping) else getattr(message, "id", None)
        request_id = _non_empty_string(human_input.get("request_id")) or _non_empty_string(msg_id)
        if request_id is not None and request_id in answered_request_ids:
            return None
        question = _non_empty_string(human_input.get("question")) or ""
        source = _non_empty_string(human_input.get("source")) or "ask_clarification"
        return {
            "kind": "human_input_request",
            "request_id": request_id or "human_input_request",
            "question": question,
            "source": source,
        }
    return None

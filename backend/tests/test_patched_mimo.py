"""Tests for deerflow.models.patched_mimo.PatchedMimoChatModel.

Covers:
- response parsing for ``reasoning_content``
- streaming delta preservation
- history replay with ``reasoning_content`` restoration
- legacy-thread compatibility when old assistant turns are incomplete
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


def _make_model(**kwargs):
    from deerflow.models.patched_mimo import PatchedMimoChatModel

    return PatchedMimoChatModel(
        model="mimo-v2.5-pro",
        api_key="test-key",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        **kwargs,
    )


def _make_payload_message(role: str, content: str | None = None) -> dict:
    return {"role": role, "content": content}


def test_reasoning_content_injected_into_assistant_message():
    model = _make_model()

    human = HumanMessage(content="hi")
    ai = AIMessage(
        content="hello",
        additional_kwargs={"reasoning_content": "internal reasoning"},
    )

    base_payload = {
        "messages": [
            _make_payload_message("user", "hi"),
            _make_payload_message("assistant", "hello"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "internal reasoning"


def test_no_reasoning_content_plain_assistant_is_dropped_when_thinking_enabled():
    model = _make_model()

    human = HumanMessage(content="hi")
    ai = AIMessage(content="hello", additional_kwargs={})
    followup = HumanMessage(content="continue")

    base_payload = {
        "messages": [
            _make_payload_message("user", "hi"),
            _make_payload_message("assistant", "hello"),
            _make_payload_message("user", "continue"),
        ],
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai, followup])
            payload = model._get_request_payload([human, ai, followup])

    assert payload["messages"] == [
        _make_payload_message("user", "hi"),
        _make_payload_message("user", "continue"),
    ]


def test_no_reasoning_content_plain_assistant_is_preserved_when_thinking_disabled():
    model = _make_model()

    human = HumanMessage(content="hi")
    ai = AIMessage(content="hello", additional_kwargs={})
    followup = HumanMessage(content="continue")

    base_payload = {
        "messages": [
            _make_payload_message("user", "hi"),
            _make_payload_message("assistant", "hello"),
            _make_payload_message("user", "continue"),
        ],
        "extra_body": {"thinking": {"type": "disabled"}},
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai, followup])
            payload = model._get_request_payload([human, ai, followup])

    assert payload["messages"] == base_payload["messages"]


def test_positional_fallback_when_count_differs():
    model = _make_model()

    human = HumanMessage(content="hi")
    ai = AIMessage(
        content="hello",
        additional_kwargs={"reasoning_content": "carry me forward"},
    )

    base_payload = {
        "messages": [
            _make_payload_message("system", "You are helpful."),
            _make_payload_message("user", "hi"),
            _make_payload_message("assistant", "hello"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "carry me forward"


def test_legacy_assistant_without_reasoning_is_dropped_with_tool_result_when_thinking_enabled():
    model = _make_model()

    human = HumanMessage(content="hi")
    legacy_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_weather",
                "args": {"city": "Beijing"},
                "id": "call_legacy",
                "type": "tool_call",
            }
        ],
        additional_kwargs={},
    )
    followup = HumanMessage(content="continue")

    base_payload = {
        "messages": [
            _make_payload_message("user", "hi"),
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_legacy",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Beijing"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_legacy", "content": '{"temp": 20}'},
            _make_payload_message("user", "continue"),
        ],
        "extra_body": {"thinking": {"type": "enabled"}},
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, legacy_ai, followup])
            payload = model._get_request_payload([human, legacy_ai, followup])

    assert payload["messages"] == [
        _make_payload_message("user", "hi"),
        _make_payload_message("user", "continue"),
    ]


def test_legacy_assistant_without_reasoning_is_preserved_when_thinking_disabled():
    model = _make_model()

    human = HumanMessage(content="hi")
    legacy_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_weather",
                "args": {"city": "Beijing"},
                "id": "call_legacy",
                "type": "tool_call",
            }
        ],
        additional_kwargs={},
    )
    followup = HumanMessage(content="continue")

    base_payload = {
        "messages": [
            _make_payload_message("user", "hi"),
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_legacy",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Beijing"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_legacy", "content": '{"temp": 20}'},
            _make_payload_message("user", "continue"),
        ],
        "extra_body": {"thinking": {"type": "disabled"}},
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, legacy_ai, followup])
            payload = model._get_request_payload([human, legacy_ai, followup])

    assert payload["messages"] == base_payload["messages"]


def test_create_chat_result_maps_reasoning_content_to_additional_kwargs():
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "final answer",
                    "reasoning_content": "step by step reasoning",
                },
                "finish_reason": "stop",
            }
        ],
        "model": "mimo-v2.5-pro",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "final answer"
    assert message.additional_kwargs["reasoning_content"] == "step by step reasoning"
    assert result.generations[0].text == "final answer"


def test_convert_chunk_to_generation_chunk_preserves_reasoning_deltas():
    model = _make_model()

    first = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "First, ",
                    }
                }
            ]
        },
        AIMessageChunk,
        {},
    )
    second = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "content": "",
                        "reasoning_content": "think carefully.",
                    }
                }
            ]
        },
        AIMessageChunk,
        {},
    )
    answer = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "content": "final answer",
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": "mimo-v2.5-pro",
        },
        AIMessageChunk,
        {},
    )

    assert first is not None
    assert second is not None
    assert answer is not None

    combined = first.message + second.message + answer.message
    assert combined.additional_kwargs["reasoning_content"] == "First, think carefully."
    assert combined.content == "final answer"

from __future__ import annotations

import copy
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from deerflow.models.vllm_provider import VllmChatModel


def _make_model(*, cumulative_stream_usage: bool = False) -> VllmChatModel:
    return VllmChatModel(
        model="Qwen/QwQ-32B",
        api_key="dummy",
        base_url="http://localhost:8000/v1",
        cumulative_stream_usage=cumulative_stream_usage,
    )


def _stream_chunk(
    *,
    completion_id: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    content: str = "",
    reasoning: str | None = None,
    finish_reason: str | None = None,
) -> dict:
    delta = {"role": "assistant", "content": content}
    if reasoning is not None:
        delta["reasoning"] = reasoning

    chunk = {
        "model": "Qwen/QwQ-32B",
        "choices": [
            {
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    if completion_id is not None:
        chunk["id"] = completion_id
    return chunk


def _convert_stream_chunk(model: VllmChatModel, chunk: dict):
    return model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})


def _assert_usage(message, *, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
    assert message.usage_metadata is not None
    assert message.usage_metadata["input_tokens"] == input_tokens
    assert message.usage_metadata["output_tokens"] == output_tokens
    assert message.usage_metadata["total_tokens"] == total_tokens


def test_vllm_provider_restores_reasoning_in_request_payload():
    model = _make_model()
    payload = model._get_request_payload(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "bash", "args": {"cmd": "pwd"}, "id": "tool-1", "type": "tool_call"}],
                additional_kwargs={"reasoning": "Need to inspect the workspace first."},
            ),
            HumanMessage(content="Continue"),
        ]
    )

    assistant_message = payload["messages"][0]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["reasoning"] == "Need to inspect the workspace first."
    assert assistant_message["tool_calls"][0]["function"]["name"] == "bash"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param({"reasoning_content": "legacy"}, "legacy", id="legacy-only"),
        pytest.param({"reasoning": None, "reasoning_content": "legacy"}, "legacy", id="null-canonical"),
        pytest.param({"reasoning": "new", "reasoning_content": "legacy"}, "new", id="both-fields"),
        pytest.param({"reasoning": "", "reasoning_content": "legacy"}, "", id="empty-canonical"),
        pytest.param({"reasoning_content": ""}, "", id="empty-legacy"),
        pytest.param({}, None, id="no-reasoning"),
    ],
)
def test_vllm_provider_restores_reasoning_field_precedence_in_request_payload(fields, expected):
    model = _make_model()
    payload = model._get_request_payload(
        [
            HumanMessage(content="Inspect the workspace."),
            AIMessage(
                content="",
                tool_calls=[{"name": "bash", "args": {"cmd": "pwd"}, "id": "tool-1", "type": "tool_call"}],
                additional_kwargs=fields,
            ),
            ToolMessage(content="/workspace", tool_call_id="tool-1"),
        ]
    )

    assistant_message = payload["messages"][1]
    if expected is None:
        assert "reasoning" not in assistant_message
    else:
        assert assistant_message["reasoning"] == expected
    assert assistant_message["tool_calls"][0]["function"]["name"] == "bash"
    assert payload["messages"][2]["tool_call_id"] == "tool-1"


def test_vllm_provider_normalizes_legacy_thinking_kwarg_to_enable_thinking():
    model = VllmChatModel(
        model="qwen3",
        api_key="dummy",
        base_url="http://localhost:8000/v1",
        extra_body={"chat_template_kwargs": {"thinking": True}},
    )

    payload = model._get_request_payload([HumanMessage(content="Hello")])

    assert payload["extra_body"]["chat_template_kwargs"] == {"enable_thinking": True}


def test_vllm_provider_preserves_explicit_enable_thinking_kwarg():
    model = VllmChatModel(
        model="qwen3",
        api_key="dummy",
        base_url="http://localhost:8000/v1",
        extra_body={"chat_template_kwargs": {"enable_thinking": False, "foo": "bar"}},
    )

    payload = model._get_request_payload([HumanMessage(content="Hello")])

    assert payload["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False,
        "foo": "bar",
    }


def test_vllm_provider_keeps_legacy_model_defaults_unmodified():
    extra_body = {"chat_template_kwargs": {"thinking": True}, "tool_stream": True}
    original = copy.deepcopy(extra_body)
    model = VllmChatModel(model="qwen3", api_key="dummy", extra_body=extra_body)

    payload = model._get_request_payload([HumanMessage(content="Hello")])

    assert payload["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}, "tool_stream": True}
    assert model.extra_body == original
    assert extra_body == original


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
async def test_vllm_provider_reused_request_body_can_disable_thinking(async_mode):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "completion", "model": "qwen3", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

    extra_body = {"chat_template_kwargs": {"thinking": True, "foo": "bar"}, "tool_stream": True}
    original = copy.deepcopy(extra_body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as sync_client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as async_client:
            model = VllmChatModel(model="qwen3", api_key="dummy", base_url="https://offline.invalid/v1", http_client=sync_client, http_async_client=async_client, max_retries=0)
            if async_mode:
                await model.ainvoke("first", extra_body=extra_body)
            else:
                model.invoke("first", extra_body=extra_body)
            after_first = copy.deepcopy(extra_body)
            extra_body["chat_template_kwargs"]["thinking"] = False
            if async_mode:
                await model.ainvoke("second", extra_body=extra_body)
            else:
                model.invoke("second", extra_body=extra_body)

    assert [request["chat_template_kwargs"]["enable_thinking"] for request in requests] == [True, False]
    assert all(request["chat_template_kwargs"]["foo"] == "bar" and request["tool_stream"] is True for request in requests)
    assert after_first == original
    assert extra_body == {"chat_template_kwargs": {"thinking": False, "foo": "bar"}, "tool_stream": True}


@pytest.mark.parametrize("enabled", [False, True])
def test_vllm_provider_explicit_switch_wins_without_mutating_request(enabled):
    extra_body = {"chat_template_kwargs": {"thinking": not enabled, "enable_thinking": enabled}, "tool_stream": True}
    original = copy.deepcopy(extra_body)

    payload = _make_model()._get_request_payload([HumanMessage(content="Hello")], extra_body=extra_body)

    assert payload["extra_body"] == {"chat_template_kwargs": {"enable_thinking": enabled}, "tool_stream": True}
    assert extra_body == original


def test_vllm_provider_preserves_reasoning_in_chat_result():
    model = _make_model()
    result = model._create_chat_result(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "42",
                        "reasoning": "I compared the two numbers directly.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    message = result.generations[0].message
    assert message.additional_kwargs["reasoning"] == "I compared the two numbers directly."
    assert message.additional_kwargs["reasoning_content"] == "I compared the two numbers directly."


def test_vllm_provider_preserves_reasoning_in_streaming_chunks():
    model = _make_model()
    chunk = model._convert_chunk_to_generation_chunk(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "reasoning": "First, call the weather tool.",
                        "content": "Calling tool...",
                    },
                    "finish_reason": None,
                }
            ],
        },
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning"] == "First, call the weather tool."
    assert chunk.message.additional_kwargs["reasoning_content"] == "First, call the weather tool."
    assert chunk.message.content == "Calling tool..."


def test_vllm_provider_preserves_empty_reasoning_values_in_streaming_chunks():
    model = _make_model()
    chunk = model._convert_chunk_to_generation_chunk(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "reasoning": "",
                        "content": "Still replying...",
                    },
                    "finish_reason": None,
                }
            ],
        },
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert "reasoning" in chunk.message.additional_kwargs
    assert chunk.message.additional_kwargs["reasoning"] == ""
    assert "reasoning_content" not in chunk.message.additional_kwargs
    assert chunk.message.content == "Still replying..."


def test_vllm_provider_converts_cumulative_stream_usage_to_deltas():
    model = _make_model(cumulative_stream_usage=True)

    first = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-1",
            prompt_tokens=10,
            completion_tokens=1,
            content="A",
            reasoning="Inspect the evidence.",
        ),
    )
    second = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-1",
            prompt_tokens=10,
            completion_tokens=3,
            content="B",
            finish_reason="stop",
        ),
    )
    terminal = _convert_stream_chunk(
        model,
        {
            "id": "chatcmpl-1",
            "model": "Qwen/QwQ-32B",
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 3,
                "total_tokens": 13,
            },
        },
    )

    assert first is not None
    _assert_usage(first.message, input_tokens=10, output_tokens=1, total_tokens=11)
    assert second is not None
    _assert_usage(second.message, input_tokens=0, output_tokens=2, total_tokens=2)
    assert terminal is not None
    _assert_usage(terminal.message, input_tokens=0, output_tokens=0, total_tokens=0)
    combined = first + second + terminal
    _assert_usage(combined.message, input_tokens=10, output_tokens=3, total_tokens=13)
    assert combined.message.content == "AB"
    assert combined.message.additional_kwargs["reasoning"] == "Inspect the evidence."
    assert not model._cumulative_usage_by_completion


def test_vllm_provider_leaves_standard_usage_only_terminal_frame_unchanged():
    model = _make_model(cumulative_stream_usage=True)

    terminal = _convert_stream_chunk(
        model,
        {
            "id": "chatcmpl-terminal",
            "model": "Qwen/QwQ-32B",
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
            },
        },
    )

    assert terminal is not None
    _assert_usage(terminal.message, input_tokens=10, output_tokens=4, total_tokens=14)
    assert not model._cumulative_usage_by_completion


def test_vllm_provider_clears_snapshot_on_terminal_frame_without_usage():
    model = _make_model(cumulative_stream_usage=True)

    _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-no-terminal-usage",
            prompt_tokens=10,
            completion_tokens=2,
        ),
    )
    terminal = _convert_stream_chunk(
        model,
        {
            "id": "chatcmpl-no-terminal-usage",
            "model": "Qwen/QwQ-32B",
            "choices": [],
        },
    )

    assert terminal is not None
    assert terminal.message.usage_metadata is None
    assert not model._cumulative_usage_by_completion


def test_vllm_provider_does_not_advance_usage_for_discarded_null_delta():
    model = _make_model(cumulative_stream_usage=True)

    first = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-null-delta",
            prompt_tokens=10,
            completion_tokens=1,
        ),
    )
    discarded = _convert_stream_chunk(
        model,
        {
            "id": "chatcmpl-null-delta",
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "delta": None,
                    "finish_reason": None,
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        },
    )
    next_chunk = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-null-delta",
            prompt_tokens=10,
            completion_tokens=3,
        ),
    )

    assert first is not None
    assert discarded is None
    assert next_chunk is not None
    _assert_usage(next_chunk.message, input_tokens=0, output_tokens=2, total_tokens=2)


def test_vllm_provider_tracks_concurrent_streams_by_completion_id():
    model = _make_model(cumulative_stream_usage=True)

    stream_a_first = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-a",
            prompt_tokens=10,
            completion_tokens=1,
        ),
    )
    stream_b_first = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-b",
            prompt_tokens=20,
            completion_tokens=2,
        ),
    )
    stream_a_second = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-a",
            prompt_tokens=10,
            completion_tokens=5,
        ),
    )

    assert stream_a_first is not None
    assert stream_a_first.message.usage_metadata["total_tokens"] == 11
    assert stream_b_first is not None
    assert stream_b_first.message.usage_metadata["total_tokens"] == 22
    assert stream_a_second is not None
    _assert_usage(stream_a_second.message, input_tokens=0, output_tokens=4, total_tokens=4)


def test_vllm_provider_preserves_reasoning_when_converting_cumulative_usage():
    model = _make_model(cumulative_stream_usage=True)

    chunk = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-reasoning",
            prompt_tokens=12,
            completion_tokens=2,
            content="Answer",
            reasoning="Check the evidence first.",
        ),
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning"] == "Check the evidence first."
    assert chunk.message.additional_kwargs["reasoning_content"] == "Check the evidence first."
    assert chunk.message.content == "Answer"
    _assert_usage(chunk.message, input_tokens=12, output_tokens=2, total_tokens=14)


def test_vllm_provider_leaves_cumulative_usage_unchanged_by_default():
    model = _make_model()

    _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-default",
            prompt_tokens=10,
            completion_tokens=1,
        ),
    )
    second = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-default",
            prompt_tokens=10,
            completion_tokens=3,
        ),
    )

    assert second is not None
    _assert_usage(second.message, input_tokens=10, output_tokens=3, total_tokens=13)
    assert model.cumulative_stream_usage is False
    assert not model._cumulative_usage_by_completion


def test_vllm_provider_leaves_usage_unchanged_without_stable_completion_id():
    model = _make_model(cumulative_stream_usage=True)

    _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id=None,
            prompt_tokens=10,
            completion_tokens=1,
        ),
    )
    second = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id=None,
            prompt_tokens=10,
            completion_tokens=3,
        ),
    )

    assert second is not None
    _assert_usage(second.message, input_tokens=10, output_tokens=3, total_tokens=13)
    assert not model._cumulative_usage_by_completion


def test_vllm_provider_does_not_evict_active_streams_at_soft_capacity(monkeypatch):
    monkeypatch.setattr(
        "deerflow.models.vllm_provider._CUMULATIVE_USAGE_TRACKER_CAPACITY",
        2,
    )
    now = [0.0]
    monkeypatch.setattr("deerflow.models.vllm_provider.time.monotonic", lambda: now[0])
    model = _make_model(cumulative_stream_usage=True)

    for index in range(3):
        _convert_stream_chunk(
            model,
            _stream_chunk(
                completion_id=f"chatcmpl-{index}",
                prompt_tokens=10,
                completion_tokens=1,
            ),
        )

    assert list(model._cumulative_usage_by_completion) == [
        "chatcmpl-0",
        "chatcmpl-1",
        "chatcmpl-2",
    ]

    now[0] = 1.0
    next_chunk = _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-0",
            prompt_tokens=10,
            completion_tokens=5,
        ),
    )

    assert next_chunk is not None
    _assert_usage(next_chunk.message, input_tokens=0, output_tokens=4, total_tokens=4)


def test_vllm_provider_evicts_only_idle_streams_above_soft_capacity(monkeypatch):
    monkeypatch.setattr(
        "deerflow.models.vllm_provider._CUMULATIVE_USAGE_TRACKER_CAPACITY",
        2,
    )
    monkeypatch.setattr(
        "deerflow.models.vllm_provider._CUMULATIVE_USAGE_TRACKER_IDLE_SECONDS",
        10,
    )
    now = [0.0]
    monkeypatch.setattr("deerflow.models.vllm_provider.time.monotonic", lambda: now[0])
    model = _make_model(cumulative_stream_usage=True)

    for index in range(3):
        _convert_stream_chunk(
            model,
            _stream_chunk(
                completion_id=f"chatcmpl-{index}",
                prompt_tokens=10,
                completion_tokens=1,
            ),
        )

    now[0] = 11.0
    _convert_stream_chunk(
        model,
        _stream_chunk(
            completion_id="chatcmpl-3",
            prompt_tokens=10,
            completion_tokens=1,
        ),
    )

    assert list(model._cumulative_usage_by_completion) == [
        "chatcmpl-2",
        "chatcmpl-3",
    ]


def test_vllm_provider_falls_back_to_reasoning_content_in_chat_result():
    model = _make_model()
    result = model._create_chat_result(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "42",
                        "reasoning_content": "I compared the two numbers directly.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    message = result.generations[0].message
    assert message.additional_kwargs["reasoning"] == "I compared the two numbers directly."
    assert message.additional_kwargs["reasoning_content"] == "I compared the two numbers directly."

    payload = model._get_request_payload([HumanMessage(content="Compare the numbers."), message, HumanMessage(content="Continue.")])
    assert payload["messages"][1]["reasoning"] == "I compared the two numbers directly."


def test_vllm_provider_falls_back_to_reasoning_content_in_streaming_chunks():
    model = _make_model()
    chunk = model._convert_chunk_to_generation_chunk(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "reasoning_content": "First, call the weather tool.",
                        "content": "Calling tool...",
                    },
                    "finish_reason": None,
                }
            ],
        },
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning"] == "First, call the weather tool."
    assert chunk.message.additional_kwargs["reasoning_content"] == "First, call the weather tool."
    assert chunk.message.content == "Calling tool..."

    payload = model._get_request_payload([HumanMessage(content="Check the weather."), chunk.message, HumanMessage(content="Continue.")])
    assert payload["messages"][1]["reasoning"] == "First, call the weather tool."


def test_vllm_provider_prefers_reasoning_over_reasoning_content_in_chat_result():
    """A payload carrying both fields keeps `reasoning` (#6047)."""
    model = _make_model()
    result = model._create_chat_result(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "42",
                        "reasoning": "new",
                        "reasoning_content": "legacy",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    message = result.generations[0].message
    assert message.additional_kwargs["reasoning"] == "new"
    assert message.additional_kwargs["reasoning_content"] == "new"


def test_vllm_provider_prefers_reasoning_over_reasoning_content_in_streaming_chunks():
    """Streaming deltas resolve both fields the same way (#6047)."""
    model = _make_model()
    chunk = model._convert_chunk_to_generation_chunk(
        {
            "model": "Qwen/QwQ-32B",
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "reasoning": "new",
                        "reasoning_content": "legacy",
                        "content": "Calling tool...",
                    },
                    "finish_reason": None,
                }
            ],
        },
        AIMessageChunk,
        {},
    )

    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning"] == "new"
    assert chunk.message.additional_kwargs["reasoning_content"] == "new"

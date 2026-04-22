from langchain_core.messages import AIMessageChunk, HumanMessage

from deerflow.models.patched_minimax import PatchedChatMiniMax


def _make_model(**kwargs) -> PatchedChatMiniMax:
    return PatchedChatMiniMax(
        model="MiniMax-M2.5",
        api_key="test-key",
        base_url="https://example.com/v1",
        **kwargs,
    )


def test_get_request_payload_preserves_thinking_and_forces_reasoning_split():
    model = _make_model(extra_body={"thinking": {"type": "disabled"}})

    payload = model._get_request_payload([HumanMessage(content="hello")])

    assert payload["extra_body"]["thinking"]["type"] == "disabled"
    assert payload["extra_body"]["reasoning_split"] is True


def test_create_chat_result_maps_reasoning_details_to_reasoning_content():
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "最终答案",
                    "reasoning_details": [
                        {
                            "type": "reasoning.text",
                            "id": "reasoning-text-1",
                            "format": "MiniMax-response-v1",
                            "index": 0,
                            "text": "先分析问题，再给出答案。",
                        }
                    ],
                },
                "finish_reason": "stop",
            }
        ],
        "model": "MiniMax-M2.5",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "最终答案"
    assert message.additional_kwargs["reasoning_content"] == "先分析问题，再给出答案。"
    assert result.generations[0].text == "最终答案"


def test_create_chat_result_strips_inline_think_tags():
    model = _make_model()
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>\n这是思考过程。\n</think>\n\n真正回答。",
                },
                "finish_reason": "stop",
            }
        ],
        "model": "MiniMax-M2.5",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert message.content == "真正回答。"
    assert message.additional_kwargs["reasoning_content"] == "这是思考过程。"
    assert result.generations[0].text == "真正回答。"


def test_convert_chunk_to_generation_chunk_preserves_reasoning_deltas():
    model = _make_model()
    first = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "id": "reasoning-text-1",
                                "format": "MiniMax-response-v1",
                                "index": 0,
                                "text": "The user",
                            }
                        ],
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
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "id": "reasoning-text-1",
                                "format": "MiniMax-response-v1",
                                "index": 0,
                                "text": " asks.",
                            }
                        ],
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
                        "content": "最终答案",
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": "MiniMax-M2.5",
        },
        AIMessageChunk,
        {},
    )

    assert first is not None
    assert second is not None
    assert answer is not None

    combined = first.message + second.message + answer.message

    assert combined.additional_kwargs["reasoning_content"] == "The user asks."
    assert combined.content == "最终答案"

"""Tests for DeerFlowClient message serialization helpers."""

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.client import DeerFlowClient


def test_serialize_ai_message_preserves_additional_kwargs():
    message = AIMessage(
        content="done",
        additional_kwargs={
            "token_usage_attribution": {
                "version": 1,
                "kind": "final_answer",
                "shared_attribution": False,
                "actions": [],
            }
        },
        usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    )

    serialized = DeerFlowClient._serialize_message(message)

    assert serialized["type"] == "ai"
    assert serialized["usage_metadata"] == {
        "input_tokens": 12,
        "output_tokens": 3,
        "total_tokens": 15,
    }
    assert serialized["additional_kwargs"] == {
        "token_usage_attribution": {
            "version": 1,
            "kind": "final_answer",
            "shared_attribution": False,
            "actions": [],
        }
    }


def test_serialize_human_message_preserves_additional_kwargs():
    message = HumanMessage(
        content="hello",
        additional_kwargs={"files": [{"name": "diagram.png"}]},
    )

    serialized = DeerFlowClient._serialize_message(message)

    assert serialized == {
        "type": "human",
        "content": "hello",
        "id": None,
        "additional_kwargs": {"files": [{"name": "diagram.png"}]},
    }

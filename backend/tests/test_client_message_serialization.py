"""Tests for DeerFlowClient message serialization helpers."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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


def _tool_message_with_artifact() -> ToolMessage:
    return ToolMessage(
        content="clarification requested",
        name="clarify",
        tool_call_id="call-1",
        id="msg-1",
        artifact={"human_input": {"request_id": "req-1", "options": ["a", "b"]}},
    )


def test_tool_message_event_preserves_artifact():
    event = DeerFlowClient._tool_message_event(_tool_message_with_artifact())

    assert event.data["artifact"] == {"human_input": {"request_id": "req-1", "options": ["a", "b"]}}
    assert event.data["tool_call_id"] == "call-1"


def test_tool_message_event_omits_artifact_when_absent():
    msg = ToolMessage(content="plain result", name="bash", tool_call_id="call-2", id="msg-2")

    event = DeerFlowClient._tool_message_event(msg)

    assert "artifact" not in event.data


def test_serialize_tool_message_preserves_artifact():
    data = DeerFlowClient._serialize_message(_tool_message_with_artifact())

    assert data["type"] == "tool"
    assert data["artifact"] == {"human_input": {"request_id": "req-1", "options": ["a", "b"]}}


def test_serialize_tool_message_omits_artifact_when_absent():
    msg = ToolMessage(content="plain result", name="bash", tool_call_id="call-2", id="msg-2")

    data = DeerFlowClient._serialize_message(msg)

    assert "artifact" not in data

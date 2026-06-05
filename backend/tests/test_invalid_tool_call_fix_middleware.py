from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.invalid_tool_call_fix_middleware import (
    InvalidToolCallFixMiddleware,
    _fix_invalid_tool_calls,
)


def test_fix_invalid_tool_calls_parses_string_args_into_tool_calls():
    message = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "type": "invalid_tool_call",
                "name": "bash",
                "id": "tc-1",
                "args": '{"command":"echo hello"}',
                "error": "args came back as a string",
            }
        ],
    )

    fixed = _fix_invalid_tool_calls(message)

    assert fixed is not message
    assert fixed.invalid_tool_calls == []
    assert fixed.tool_calls == [
        {
            "type": "tool_call",
            "name": "bash",
            "id": "tc-1",
            "args": {"command": "echo hello"},
        }
    ]


def test_fix_invalid_tool_calls_normalizes_todo_write_alias_in_tool_calls():
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "todo_write",
                "id": "tc-1",
                "args": {"todos": []},
                "type": "tool_call",
            }
        ],
    )

    fixed = _fix_invalid_tool_calls(message)

    assert fixed is not message
    assert fixed.tool_calls == [
        {
            "name": "write_todos",
            "id": "tc-1",
            "args": {"todos": []},
            "type": "tool_call",
        }
    ]


def test_fix_invalid_tool_calls_normalizes_todo_write_alias_when_repairing_invalid_call():
    message = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "type": "invalid_tool_call",
                "name": "todo_write",
                "id": "tc-1",
                "args": '{"todos":[]}',
                "error": "args came back as a string",
            }
        ],
    )

    fixed = _fix_invalid_tool_calls(message)

    assert fixed is not message
    assert fixed.invalid_tool_calls == []
    assert fixed.tool_calls == [
        {
            "type": "tool_call",
            "name": "write_todos",
            "id": "tc-1",
            "args": {"todos": []},
        }
    ]


def test_after_model_returns_patched_message_when_only_tool_name_changed():
    middleware = InvalidToolCallFixMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "todo_write",
                        "id": "tc-1",
                        "args": {"todos": []},
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }

    result = middleware.after_model(state, MagicMock())

    assert result is not None
    assert result["messages"][-1].tool_calls[0]["name"] == "write_todos"

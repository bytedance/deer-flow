"""Tests for TokenUsageMiddleware attribution annotations."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.token_usage_middleware import (
    TOKEN_USAGE_ATTRIBUTION_KEY,
    TokenUsageMiddleware,
)


def _make_runtime():
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread"}
    return runtime


class TestTokenUsageMiddleware:
    def test_annotates_todo_updates_with_structured_actions(self):
        middleware = TokenUsageMiddleware()
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "write_todos:1",
                    "name": "write_todos",
                    "args": {
                        "todos": [
                            {"content": "Inspect streaming path", "status": "completed"},
                            {"content": "Design token attribution schema", "status": "in_progress"},
                        ]
                    },
                }
            ],
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )

        state = {
            "messages": [message],
            "todos": [
                {"content": "Inspect streaming path", "status": "in_progress"},
                {"content": "Design token attribution schema", "status": "pending"},
            ],
        }

        result = middleware.after_model(state, _make_runtime())

        assert result is not None
        updated_message = result["messages"][0]
        attribution = updated_message.additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY]
        assert attribution["kind"] == "tool_batch"
        assert attribution["shared_attribution"] is True
        assert attribution["tool_call_ids"] == ["write_todos:1"]
        assert attribution["actions"] == [
            {
                "kind": "todo_complete",
                "content": "Inspect streaming path",
                "tool_call_id": "write_todos:1",
            },
            {
                "kind": "todo_start",
                "content": "Design token attribution schema",
                "tool_call_id": "write_todos:1",
            },
        ]

    def test_annotates_subagent_and_search_steps(self):
        middleware = TokenUsageMiddleware()
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "task:1",
                    "name": "task",
                    "args": {
                        "description": "spec-coder patch message grouping",
                        "subagent_type": "general-purpose",
                    },
                },
                {
                    "id": "web_search:1",
                    "name": "web_search",
                    "args": {"query": "LangGraph useStream messages tuple"},
                },
            ],
        )

        result = middleware.after_model({"messages": [message]}, _make_runtime())

        assert result is not None
        attribution = result["messages"][0].additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY]
        assert attribution["kind"] == "tool_batch"
        assert attribution["shared_attribution"] is True
        assert attribution["actions"] == [
            {
                "kind": "subagent",
                "description": "spec-coder patch message grouping",
                "subagent_type": "general-purpose",
                "tool_call_id": "task:1",
            },
            {
                "kind": "search",
                "tool_name": "web_search",
                "query": "LangGraph useStream messages tuple",
                "tool_call_id": "web_search:1",
            },
        ]

    def test_marks_final_answer_when_no_tools(self):
        middleware = TokenUsageMiddleware()
        message = AIMessage(content="Here is the final answer.")

        result = middleware.after_model({"messages": [message]}, _make_runtime())

        assert result is not None
        attribution = result["messages"][0].additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY]
        assert attribution["kind"] == "final_answer"
        assert attribution["shared_attribution"] is False
        assert attribution["actions"] == []

    def test_annotates_removed_todos(self):
        middleware = TokenUsageMiddleware()
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "write_todos:remove",
                    "name": "write_todos",
                    "args": {
                        "todos": [],
                    },
                }
            ],
        )

        result = middleware.after_model(
            {
                "messages": [message],
                "todos": [
                    {"content": "Archive obsolete plan", "status": "pending"},
                ],
            },
            _make_runtime(),
        )

        assert result is not None
        attribution = result["messages"][0].additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY]
        assert attribution["kind"] == "todo_update"
        assert attribution["shared_attribution"] is False
        assert attribution["actions"] == [
            {
                "kind": "todo_remove",
                "content": "Archive obsolete plan",
                "tool_call_id": "write_todos:remove",
            }
        ]

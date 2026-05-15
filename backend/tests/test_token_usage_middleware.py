"""Tests for TokenUsageMiddleware attribution annotations."""

import importlib
import logging
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.token_usage_middleware import (
    TOKEN_USAGE_ATTRIBUTION_KEY,
    TokenUsageMiddleware,
)


def _make_runtime():
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread"}
    return runtime


class TestTokenUsageMiddleware:
    def test_logs_cache_token_details(self, caplog):
        middleware = TokenUsageMiddleware()
        message = AIMessage(
            content="Here is the final answer.",
            usage_metadata={
                "input_tokens": 350,
                "output_tokens": 240,
                "total_tokens": 590,
                "input_token_details": {
                    "audio": 10,
                    "cache_creation": 200,
                    "cache_read": 100,
                },
                "output_token_details": {
                    "audio": 10,
                    "reasoning": 200,
                },
            },
        )

        with caplog.at_level(
            logging.INFO,
            logger="deerflow.agents.middlewares.token_usage_middleware",
        ):
            result = middleware.after_model({"messages": [message]}, _make_runtime())

        assert result is not None
        assert "LLM token usage: input=350 output=240 total=590" in caplog.text
        assert "input_token_details={'audio': 10, 'cache_creation': 200, 'cache_read': 100}" in caplog.text
        assert "output_token_details={'audio': 10, 'reasoning': 200}" in caplog.text

    def test_logs_basic_tokens_when_no_detail_fields_in_usage_metadata(self, caplog):
        """When usage_metadata has only totals (no input_token_details), log just the counts."""
        middleware = TokenUsageMiddleware()
        message = AIMessage(
            content="Here is the final answer.",
            usage_metadata={
                "input_tokens": 350,
                "output_tokens": 240,
                "total_tokens": 590,
            },
        )

        with caplog.at_level(
            logging.INFO,
            logger="deerflow.agents.middlewares.token_usage_middleware",
        ):
            result = middleware.after_model({"messages": [message]}, _make_runtime())

        assert result is not None
        assert "LLM token usage: input=350 output=240 total=590" in caplog.text
        assert "input_token_details" not in caplog.text

    def test_no_log_when_usage_metadata_is_missing(self, caplog):
        """When usage_metadata is absent, no token usage line is logged."""
        middleware = TokenUsageMiddleware()
        message = AIMessage(
            content="Here is the final answer.",
            response_metadata={
                "usage": {
                    "input_tokens": 350,
                    "output_tokens": 240,
                    "total_tokens": 590,
                }
            },
        )

        with caplog.at_level(
            logging.INFO,
            logger="deerflow.agents.middlewares.token_usage_middleware",
        ):
            result = middleware.after_model({"messages": [message]}, _make_runtime())

        assert result is not None
        assert "LLM token usage" not in caplog.text

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

    def test_merges_subagent_usage_by_message_position_when_ai_message_ids_are_missing(self, monkeypatch):
        middleware = TokenUsageMiddleware()
        first_dispatch = AIMessage(
            content="",
            tool_calls=[{"id": "task:first", "name": "task", "args": {}}],
        )
        second_dispatch = AIMessage(
            content="",
            tool_calls=[
                {"id": "task:second-a", "name": "task", "args": {}},
                {"id": "task:second-b", "name": "task", "args": {}},
            ],
        )
        messages = [
            first_dispatch,
            ToolMessage(content="first", tool_call_id="task:first"),
            second_dispatch,
            ToolMessage(content="second-a", tool_call_id="task:second-a"),
            ToolMessage(content="second-b", tool_call_id="task:second-b"),
            AIMessage(content="done"),
        ]
        cached_usage = {
            "task:second-a": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "task:second-b": {"input_tokens": 20, "output_tokens": 7, "total_tokens": 27},
        }

        task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")
        monkeypatch.setattr(
            task_tool_module,
            "pop_cached_subagent_usage",
            lambda tool_call_id: cached_usage.pop(tool_call_id, None),
        )

        result = middleware.after_model({"messages": messages}, _make_runtime())

        assert result is not None
        usage_updates = [message for message in result["messages"] if getattr(message, "usage_metadata", None)]
        assert len(usage_updates) == 1
        updated = usage_updates[0]
        assert updated.tool_calls == second_dispatch.tool_calls
        assert updated.usage_metadata == {
            "input_tokens": 30,
            "output_tokens": 12,
            "total_tokens": 42,
        }

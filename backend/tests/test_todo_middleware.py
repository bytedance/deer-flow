"""Tests for TodoMiddleware context-loss detection."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import PrivateAttr

from deerflow.agents.middlewares.todo_middleware import (
    TodoMiddleware,
    _completion_reminder_count,
    _format_todos,
    _has_tool_call_intent_or_error,
    _reminder_in_messages,
    _todos_in_messages,
)


def _ai_with_write_todos():
    return AIMessage(content="", tool_calls=[{"name": "write_todos", "id": "tc_1", "args": {}}])


def _reminder_msg():
    return HumanMessage(name="todo_reminder", content="reminder")


class _CapturingFakeMessagesListChatModel(FakeMessagesListChatModel):
    _seen_messages: list[list[Any]] = PrivateAttr(default_factory=list)

    @property
    def seen_messages(self) -> list[list[Any]]:
        return self._seen_messages

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen_messages.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def _make_runtime():
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread", "run_id": "test-run"}
    return runtime


def _make_runtime_for(thread_id: str, run_id: str):
    runtime = _make_runtime()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _sample_todos():
    return [
        {"status": "completed", "content": "Set up project"},
        {"status": "in_progress", "content": "Write tests"},
        {"status": "pending", "content": "Deploy"},
    ]


class TestTodosInMessages:
    def test_true_when_write_todos_present(self):
        msgs = [HumanMessage(content="hi"), _ai_with_write_todos()]
        assert _todos_in_messages(msgs) is True

    def test_false_when_no_write_todos(self):
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="hello", tool_calls=[{"name": "bash", "id": "tc_1", "args": {}}]),
        ]
        assert _todos_in_messages(msgs) is False

    def test_false_for_empty_list(self):
        assert _todos_in_messages([]) is False

    def test_false_for_ai_without_tool_calls(self):
        msgs = [AIMessage(content="hello")]
        assert _todos_in_messages(msgs) is False


class TestReminderInMessages:
    def test_true_when_reminder_present(self):
        msgs = [HumanMessage(content="hi"), _reminder_msg()]
        assert _reminder_in_messages(msgs) is True

    def test_false_when_no_reminder(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert _reminder_in_messages(msgs) is False

    def test_false_for_empty_list(self):
        assert _reminder_in_messages([]) is False

    def test_false_for_human_without_name(self):
        msgs = [HumanMessage(content="todo_reminder")]
        assert _reminder_in_messages(msgs) is False


class TestFormatTodos:
    def test_formats_multiple_items(self):
        todos = _sample_todos()
        result = _format_todos(todos)
        assert "- [completed] Set up project" in result
        assert "- [in_progress] Write tests" in result
        assert "- [pending] Deploy" in result

    def test_empty_list(self):
        assert _format_todos([]) == ""

    def test_missing_fields_use_defaults(self):
        todos = [{"content": "No status"}, {"status": "done"}]
        result = _format_todos(todos)
        assert "- [pending] No status" in result
        assert "- [done] " in result


class TestBeforeModel:
    def test_returns_none_when_no_todos(self):
        mw = TodoMiddleware()
        state = {"messages": [HumanMessage(content="hi")], "todos": []}
        assert mw.before_model(state, _make_runtime()) is None

    def test_returns_none_when_todos_is_none(self):
        mw = TodoMiddleware()
        state = {"messages": [HumanMessage(content="hi")], "todos": None}
        assert mw.before_model(state, _make_runtime()) is None

    def test_returns_none_when_write_todos_still_visible(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_with_write_todos()],
            "todos": _sample_todos(),
        }
        assert mw.before_model(state, _make_runtime()) is None

    def test_returns_none_when_reminder_already_present(self):
        mw = TodoMiddleware()
        state = {
            "messages": [HumanMessage(content="hi"), _reminder_msg()],
            "todos": _sample_todos(),
        }
        assert mw.before_model(state, _make_runtime()) is None

    def test_injects_reminder_when_todos_exist_but_truncated(self):
        mw = TodoMiddleware()
        state = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="sure")],
            "todos": _sample_todos(),
        }
        result = mw.before_model(state, _make_runtime())
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        assert msgs[0].name == "todo_reminder"

    def test_reminder_contains_formatted_todos(self):
        mw = TodoMiddleware()
        state = {
            "messages": [HumanMessage(content="hi")],
            "todos": _sample_todos(),
        }
        result = mw.before_model(state, _make_runtime())
        content = result["messages"][0].content
        assert "Set up project" in content
        assert "Write tests" in content
        assert "Deploy" in content
        assert "system_reminder" in content


class TestAbeforeModel:
    def test_delegates_to_sync(self):
        mw = TodoMiddleware()
        state = {
            "messages": [HumanMessage(content="hi")],
            "todos": _sample_todos(),
        }
        result = asyncio.run(mw.abefore_model(state, _make_runtime()))
        assert result is not None
        assert result["messages"][0].name == "todo_reminder"


def _completion_reminder_msg():
    return HumanMessage(name="todo_completion_reminder", content="finish your todos")


def _todo_completion_reminders(messages):
    reminders = []
    for message in messages:
        if isinstance(message, HumanMessage) and message.name == "todo_completion_reminder":
            reminders.append(message)
    return reminders


def _ai_no_tool_calls():
    return AIMessage(content="I'm done!")


def _ai_with_invalid_tool_calls():
    return AIMessage(
        content="",
        tool_calls=[],
        invalid_tool_calls=[
            {
                "type": "invalid_tool_call",
                "id": "write_file:36",
                "name": "write_file",
                "args": "{invalid",
                "error": "Failed to parse tool arguments",
            }
        ],
    )


def _ai_with_raw_provider_tool_calls():
    return AIMessage(
        content="",
        tool_calls=[],
        invalid_tool_calls=[],
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "raw-tool-call",
                    "type": "function",
                    "function": {"name": "write_file", "arguments": '{"path":"report.md"}'},
                }
            ]
        },
    )


def _ai_with_legacy_function_call():
    return AIMessage(
        content="",
        additional_kwargs={"function_call": {"name": "write_file", "arguments": '{"path":"report.md"}'}},
    )


def _ai_with_tool_finish_reason():
    return AIMessage(content="", response_metadata={"finish_reason": "tool_calls"})


def _incomplete_todos():
    return [
        {"status": "completed", "content": "Step 1"},
        {"status": "in_progress", "content": "Step 2"},
        {"status": "pending", "content": "Step 3"},
    ]


def _all_completed_todos():
    return [
        {"status": "completed", "content": "Step 1"},
        {"status": "completed", "content": "Step 2"},
    ]


class TestCompletionReminderCount:
    def test_zero_when_no_reminders(self):
        msgs = [HumanMessage(content="hi"), _ai_no_tool_calls()]
        assert _completion_reminder_count(msgs) == 0

    def test_counts_completion_reminders(self):
        msgs = [_completion_reminder_msg(), _completion_reminder_msg()]
        assert _completion_reminder_count(msgs) == 2

    def test_does_not_count_todo_reminders(self):
        msgs = [_reminder_msg(), _completion_reminder_msg()]
        assert _completion_reminder_count(msgs) == 1


class TestToolCallIntentOrError:
    def test_false_for_plain_final_answer(self):
        assert _has_tool_call_intent_or_error(_ai_no_tool_calls()) is False

    def test_true_for_structured_tool_calls(self):
        assert _has_tool_call_intent_or_error(_ai_with_write_todos()) is True

    def test_true_for_invalid_tool_calls(self):
        assert _has_tool_call_intent_or_error(_ai_with_invalid_tool_calls()) is True

    def test_true_for_raw_provider_tool_calls(self):
        assert _has_tool_call_intent_or_error(_ai_with_raw_provider_tool_calls()) is True

    def test_true_for_legacy_function_call(self):
        assert _has_tool_call_intent_or_error(_ai_with_legacy_function_call()) is True

    def test_true_for_tool_finish_reason(self):
        assert _has_tool_call_intent_or_error(_ai_with_tool_finish_reason()) is True

    def test_langchain_ai_message_tool_fields_are_explicitly_handled(self):
        # Sentinel for LangChain compatibility: if future AIMessage versions add
        # new top-level tool/function-call fields, this test should fail. When
        # it does, update `_has_tool_call_intent_or_error()` so the completion
        # reminder guard explicitly decides whether each new field means "not a
        # clean final answer"; the helper has a matching comment pointing back
        # to this sentinel.
        tool_related_fields = {name for name in AIMessage.model_fields if "tool" in name.lower() or ("function" in name.lower() and "call" in name.lower())}
        assert tool_related_fields <= {"tool_calls", "invalid_tool_calls"}


class TestAfterModel:
    def test_returns_none_when_agent_still_using_tools(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_with_write_todos()],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_returns_none_when_no_todos(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": [],
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_returns_none_when_todos_is_none(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": None,
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_returns_none_when_all_completed(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": _all_completed_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_returns_none_when_no_messages(self):
        mw = TodoMiddleware()
        state = {
            "messages": [],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_queues_reminder_and_jumps_to_model_when_incomplete(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [HumanMessage(content="hi"), _ai_no_tool_calls()],
            "todos": _incomplete_todos(),
        }
        result = mw.after_model(state, runtime)
        assert result is not None
        assert result["jump_to"] == "model"
        assert "messages" not in result

        request = MagicMock()
        request.runtime = runtime
        request.messages = state["messages"]
        request.override.return_value = "patched-request"
        handler = MagicMock(return_value="response")

        assert mw.wrap_model_call(request, handler) == "response"
        request.override.assert_called_once()
        reminder = request.override.call_args.kwargs["messages"][-1]
        assert isinstance(reminder, HumanMessage)
        assert reminder.name == "todo_completion_reminder"
        assert reminder.additional_kwargs["hide_from_ui"] is True
        assert "Step 2" in reminder.content
        assert "Step 3" in reminder.content
        handler.assert_called_once_with("patched-request")

    def test_reminder_lists_only_incomplete_items(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": _incomplete_todos(),
        }
        result = mw.after_model(state, runtime)
        assert result is not None

        request = MagicMock()
        request.runtime = runtime
        request.messages = state["messages"]
        request.override.return_value = "patched-request"
        mw.wrap_model_call(request, MagicMock(return_value="response"))
        content = request.override.call_args.kwargs["messages"][-1].content
        assert "Step 1" not in content  # completed — should not appear
        assert "Step 2" in content
        assert "Step 3" in content

    def test_allows_exit_after_max_reminders(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [
                _ai_no_tool_calls(),
            ],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, runtime) is not None
        assert mw.after_model(state, runtime) is not None
        assert mw.after_model(state, runtime) is None

    def test_still_sends_reminder_before_cap(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [
                _ai_no_tool_calls(),
            ],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, runtime) is not None
        result = mw.after_model(state, runtime)
        assert result is not None
        assert result["jump_to"] == "model"

    def test_does_not_trigger_for_invalid_tool_calls(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_with_invalid_tool_calls()],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_does_not_trigger_for_raw_provider_tool_calls(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_with_raw_provider_tool_calls()],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_does_not_trigger_for_legacy_function_call(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_with_legacy_function_call()],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_does_not_trigger_for_tool_finish_reason(self):
        mw = TodoMiddleware()
        state = {
            "messages": [_ai_with_tool_finish_reason()],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None


class TestAafterModel:
    def test_delegates_to_sync(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": _incomplete_todos(),
        }
        result = asyncio.run(mw.aafter_model(state, runtime))
        assert result is not None
        assert result["jump_to"] == "model"
        assert "messages" not in result


class TestWrapModelCall:
    def test_no_pending_reminder_passthrough(self):
        mw = TodoMiddleware()
        request = MagicMock()
        request.runtime = _make_runtime()
        request.messages = [HumanMessage(content="hi")]
        handler = MagicMock(return_value="response")

        assert mw.wrap_model_call(request, handler) == "response"
        request.override.assert_not_called()
        handler.assert_called_once_with(request)

    def test_pending_reminder_is_injected_once(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": _incomplete_todos(),
        }
        mw.after_model(state, runtime)

        request = MagicMock()
        request.runtime = runtime
        request.messages = state["messages"]
        request.override.return_value = "patched-request"
        handler = MagicMock(return_value="response")

        assert mw.wrap_model_call(request, handler) == "response"
        injected_messages = request.override.call_args.kwargs["messages"]
        assert injected_messages[-1].name == "todo_completion_reminder"

        request.override.reset_mock()
        handler.reset_mock()
        handler.return_value = "second-response"
        assert mw.wrap_model_call(request, handler) == "second-response"
        request.override.assert_not_called()
        handler.assert_called_once_with(request)


class TestTodoMiddlewareAgentGraphIntegration:
    def test_completion_reminder_is_transient_in_real_agent_graph(self):
        mw = TodoMiddleware()
        model = _CapturingFakeMessagesListChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_todos",
                            "id": "todos-1",
                            "args": {
                                "todos": [
                                    {"content": "Step 1", "status": "completed"},
                                    {"content": "Step 2", "status": "pending"},
                                ]
                            },
                        }
                    ],
                ),
                AIMessage(content="premature final 1"),
                AIMessage(content="premature final 2"),
                AIMessage(content="premature final 3"),
            ],
        )
        graph = create_agent(model=model, tools=[], middleware=[mw])

        result = graph.invoke(
            {"messages": [("user", "finish all todos")]},
            context={"thread_id": "integration-thread", "run_id": "integration-run"},
        )

        assert len(model.seen_messages) == 4
        reminders_by_call = [_todo_completion_reminders(messages) for messages in model.seen_messages]
        assert reminders_by_call[0] == []
        assert reminders_by_call[1] == []
        assert len(reminders_by_call[2]) == 1
        assert len(reminders_by_call[3]) == 1
        assert "Step 1" not in reminders_by_call[2][0].content
        assert "Step 2" in reminders_by_call[2][0].content

        persisted_reminders = _todo_completion_reminders(result["messages"])
        assert persisted_reminders == []
        assert result["messages"][-1].content == "premature final 3"
        assert result["todos"] == [
            {"content": "Step 1", "status": "completed"},
            {"content": "Step 2", "status": "pending"},
        ]
        assert mw._pending_completion_reminders == {}
        assert mw._completion_reminder_counts == {}


class TestRunScopedReminderCleanup:
    def test_before_agent_clears_stale_count_without_pending_reminder(self):
        mw = TodoMiddleware()
        stale_runtime = _make_runtime()
        stale_runtime.context = {"thread_id": "test-thread", "run_id": "stale-run"}
        current_runtime = _make_runtime()
        current_runtime.context = {"thread_id": "test-thread", "run_id": "current-run"}
        other_thread_runtime = _make_runtime()
        other_thread_runtime.context = {"thread_id": "other-thread", "run_id": "stale-run"}

        state = {"messages": [_ai_no_tool_calls()], "todos": _incomplete_todos()}
        assert mw.after_model(state, stale_runtime) is not None
        assert mw.after_model(state, other_thread_runtime) is not None

        # Simulate a model call that drained the pending message, followed by an
        # abnormal run end where after_agent did not clear the reminder count.
        assert mw._drain_completion_reminders(stale_runtime)
        assert mw._completion_reminder_count_for_runtime(stale_runtime) == 1

        mw.before_agent({}, current_runtime)

        assert mw._completion_reminder_count_for_runtime(stale_runtime) == 0
        assert mw._completion_reminder_count_for_runtime(other_thread_runtime) == 1

    def test_size_guard_prunes_oldest_count_only_reminder_state(self):
        mw = TodoMiddleware()
        mw._MAX_COMPLETION_REMINDER_KEYS = 2
        first_runtime = _make_runtime_for("thread-a", "run-a")
        second_runtime = _make_runtime_for("thread-b", "run-b")
        third_runtime = _make_runtime_for("thread-c", "run-c")

        state = {"messages": [_ai_no_tool_calls()], "todos": _incomplete_todos()}
        assert mw.after_model(state, first_runtime) is not None

        # Simulate the normal model request path: pending reminder is consumed,
        # but the run count remains until after_agent() or stale cleanup.
        assert mw._drain_completion_reminders(first_runtime)
        assert mw._completion_reminder_count_for_runtime(first_runtime) == 1

        assert mw.after_model(state, second_runtime) is not None
        assert mw.after_model(state, third_runtime) is not None

        assert mw._completion_reminder_count_for_runtime(first_runtime) == 0
        assert mw._completion_reminder_count_for_runtime(second_runtime) == 1
        assert mw._completion_reminder_count_for_runtime(third_runtime) == 1
        assert ("thread-a", "run-a") not in mw._completion_reminder_touch_order

    def test_size_guard_prunes_pending_and_count_state_together(self):
        mw = TodoMiddleware()
        mw._MAX_COMPLETION_REMINDER_KEYS = 1
        stale_runtime = _make_runtime_for("thread-a", "run-a")
        current_runtime = _make_runtime_for("thread-b", "run-b")

        state = {"messages": [_ai_no_tool_calls()], "todos": _incomplete_todos()}
        assert mw.after_model(state, stale_runtime) is not None
        assert mw.after_model(state, current_runtime) is not None

        assert mw._drain_completion_reminders(stale_runtime) == []
        assert mw._completion_reminder_count_for_runtime(stale_runtime) == 0
        assert mw._completion_reminder_count_for_runtime(current_runtime) == 1


class TestAwrapModelCall:
    def test_async_pending_reminder_is_injected(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": _incomplete_todos(),
        }
        mw.after_model(state, runtime)

        request = MagicMock()
        request.runtime = runtime
        request.messages = state["messages"]
        request.override.return_value = "patched-request"
        handler = AsyncMock(return_value="response")

        result = asyncio.run(mw.awrap_model_call(request, handler))
        assert result == "response"
        injected_messages = request.override.call_args.kwargs["messages"]
        assert injected_messages[-1].name == "todo_completion_reminder"
        handler.assert_awaited_once_with("patched-request")

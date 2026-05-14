"""Tests for TodoMiddleware context-loss detection."""

import asyncio
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.todo_middleware import (
    TodoMiddleware,
    _completion_reminder_count,
    _format_todos,
    _reminder_in_messages,
    _todos_in_messages,
)


def _ai_with_write_todos():
    return AIMessage(content="", tool_calls=[{"name": "write_todos", "id": "tc_1", "args": {}}])


def _reminder_msg():
    return HumanMessage(name="todo_reminder", content="reminder")


def _make_runtime(thread_id="test-thread"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


class _FakeModelRequest:
    def __init__(self, messages, runtime=None):
        self.messages = messages
        self.runtime = runtime or _make_runtime()

    def override(self, **kwargs):
        request = _FakeModelRequest(
            messages=kwargs.get("messages", self.messages),
            runtime=kwargs.get("runtime", self.runtime),
        )
        return request


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


def _ai_no_tool_calls():
    return AIMessage(content="I'm done!")


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

    def test_injects_reminder_and_jumps_to_model_when_incomplete(self):
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

        captured = {}

        def handler(request):
            captured["messages"] = request.messages
            return "ok"

        assert mw.wrap_model_call(_FakeModelRequest(state["messages"], runtime), handler) == "ok"
        reminder = captured["messages"][-1]
        assert isinstance(reminder, HumanMessage)
        assert reminder.name == "todo_completion_reminder"
        assert "Step 2" in reminder.content
        assert "Step 3" in reminder.content

    def test_reminder_lists_only_incomplete_items(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        state = {
            "messages": [_ai_no_tool_calls()],
            "todos": _incomplete_todos(),
        }
        result = mw.after_model(state, runtime)
        assert result == {"jump_to": "model"}

        captured = {}

        def handler(request):
            captured["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(state["messages"], runtime), handler)
        content = captured["messages"][-1].content
        assert "Step 1" not in content  # completed — should not appear
        assert "Step 2" in content
        assert "Step 3" in content

    def test_allows_exit_after_max_reminders(self):
        mw = TodoMiddleware()
        state = {
            "messages": [
                _completion_reminder_msg(),
                _completion_reminder_msg(),
                _ai_no_tool_calls(),
            ],
            "todos": _incomplete_todos(),
        }
        assert mw.after_model(state, _make_runtime()) is None

    def test_still_sends_reminder_before_cap(self):
        mw = TodoMiddleware()
        state = {
            "messages": [
                _completion_reminder_msg(),  # 1 reminder so far
                _ai_no_tool_calls(),
            ],
            "todos": _incomplete_todos(),
        }
        result = mw.after_model(state, _make_runtime())
        assert result is not None
        assert result["jump_to"] == "model"
        assert "messages" not in result

    def test_wrap_model_call_does_not_persist_transient_reminder(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        messages = [HumanMessage(content="hi"), _ai_no_tool_calls()]
        state = {"messages": messages, "todos": _incomplete_todos()}

        result = mw.after_model(state, runtime)
        assert result == {"jump_to": "model"}

        captured = {}

        def handler(request):
            captured["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(messages, runtime), handler)

        assert captured["messages"][:-1] == messages
        assert captured["messages"][-1].name == "todo_completion_reminder"
        assert messages == state["messages"]

    def test_transient_reminder_cap_does_not_depend_on_persisted_messages(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        messages = [_ai_no_tool_calls()]
        state = {"messages": messages, "todos": _incomplete_todos()}

        def handler(request):
            return request.messages

        assert mw.after_model(state, runtime) == {"jump_to": "model"}
        assert mw.wrap_model_call(_FakeModelRequest(messages, runtime), handler)[-1].name == "todo_completion_reminder"

        assert mw.after_model(state, runtime) == {"jump_to": "model"}
        assert mw.wrap_model_call(_FakeModelRequest(messages, runtime), handler)[-1].name == "todo_completion_reminder"

        assert mw.after_model(state, runtime) is None

    def test_before_agent_clears_pending_completion_reminder(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        messages = [_ai_no_tool_calls()]
        state = {"messages": messages, "todos": _incomplete_todos()}

        assert mw.after_model(state, runtime) == {"jump_to": "model"}
        assert mw.before_agent(state, runtime) is None

        captured = {}

        def handler(request):
            captured["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(messages, runtime), handler)
        assert captured["messages"] == messages

    def test_after_agent_clears_pending_completion_reminder(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        messages = [_ai_no_tool_calls()]
        state = {"messages": messages, "todos": _incomplete_todos()}

        assert mw.after_model(state, runtime) == {"jump_to": "model"}
        assert mw.after_agent(state, runtime) is None

        captured = {}

        def handler(request):
            captured["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(messages, runtime), handler)
        assert captured["messages"] == messages

    def test_pending_completion_reminders_are_thread_scoped(self):
        mw = TodoMiddleware()
        runtime_a = _make_runtime("thread-a")
        runtime_b = _make_runtime("thread-b")
        messages = [_ai_no_tool_calls()]
        state = {"messages": messages, "todos": _incomplete_todos()}

        assert mw.after_model(state, runtime_a) == {"jump_to": "model"}

        captured_b = {}

        def handler_b(request):
            captured_b["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(messages, runtime_b), handler_b)
        assert captured_b["messages"] == messages

        captured_a = {}

        def handler_a(request):
            captured_a["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(messages, runtime_a), handler_a)
        assert captured_a["messages"][-1].name == "todo_completion_reminder"

    def test_invalid_tool_calls_jump_without_completion_reminder(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        ai_message = AIMessage(
            content="",
            invalid_tool_calls=[{"id": "bad-call", "name": "write_todos", "args": "", "error": "bad json"}],
        )
        state = {
            "messages": [ai_message],
            "todos": _incomplete_todos(),
        }

        assert mw.after_model(state, runtime) == {"jump_to": "model"}

        captured = {}

        def handler(request):
            captured["messages"] = request.messages
            return "ok"

        mw.wrap_model_call(_FakeModelRequest(state["messages"], runtime), handler)
        assert captured["messages"] == state["messages"]


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

    def test_awrap_model_call_injects_pending_reminder(self):
        mw = TodoMiddleware()
        runtime = _make_runtime()
        messages = [_ai_no_tool_calls()]
        state = {
            "messages": messages,
            "todos": _incomplete_todos(),
        }
        asyncio.run(mw.aafter_model(state, runtime))

        captured = {}

        async def handler(request):
            captured["messages"] = request.messages
            return "ok"

        result = asyncio.run(mw.awrap_model_call(_FakeModelRequest(messages, runtime), handler))
        assert result == "ok"
        assert captured["messages"][-1].name == "todo_completion_reminder"

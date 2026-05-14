"""Middleware that extends TodoListMiddleware with context-loss detection and premature-exit prevention.

When the message history is truncated (e.g., by SummarizationMiddleware), the
original `write_todos` tool call and its ToolMessage can be scrolled out of the
active context window. This middleware detects that situation and injects a
reminder message so the model still knows about the outstanding todo list.

Additionally, this middleware prevents the agent from exiting the loop while
there are still incomplete todo items. When the model produces a final response
(no tool calls) but todos are not yet complete, the middleware queues a
transient reminder for the next model request and jumps back to the model node
to force continued engagement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from threading import Lock
from typing import Any, override

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.todo import PlanningState, Todo
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime


def _todos_in_messages(messages: list[Any]) -> bool:
    """Return True if any AIMessage in *messages* contains a write_todos tool call."""
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "write_todos":
                    return True
    return False


def _reminder_in_messages(messages: list[Any]) -> bool:
    """Return True if a todo_reminder HumanMessage is already present in *messages*."""
    for msg in messages:
        if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_reminder":
            return True
    return False


def _completion_reminder_count(messages: list[Any]) -> int:
    """Return the number of todo_completion_reminder HumanMessages in *messages*."""
    return sum(1 for msg in messages if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_completion_reminder")


def _format_todos(todos: list[Todo]) -> str:
    """Format a list of Todo items into a human-readable string."""
    lines: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


class TodoMiddleware(TodoListMiddleware):
    """Extends TodoListMiddleware with `write_todos` context-loss detection.

    When the original `write_todos` tool call has been truncated from the message
    history (e.g., after summarization), the model loses awareness of the current
    todo list. This middleware detects that gap in `before_model` / `abefore_model`
    and injects a reminder message so the model can continue tracking progress.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._completion_reminder_lock = Lock()
        self._pending_completion_reminders: dict[str, HumanMessage] = {}
        self._completion_reminder_counts: dict[str, int] = {}

    @staticmethod
    def _thread_id(runtime: Runtime) -> str:
        context = getattr(runtime, "context", None) or {}
        return str(context.get("thread_id") or "__default__")

    def _clear_completion_reminder_state(self, thread_id: str) -> None:
        with self._completion_reminder_lock:
            self._pending_completion_reminders.pop(thread_id, None)
            self._completion_reminder_counts.pop(thread_id, None)

    def _queue_completion_reminder(self, thread_id: str, reminder: HumanMessage) -> None:
        with self._completion_reminder_lock:
            self._pending_completion_reminders[thread_id] = reminder
            self._completion_reminder_counts[thread_id] = self._completion_reminder_counts.get(thread_id, 0) + 1

    def _completion_reminder_count_for_thread(self, thread_id: str) -> int:
        with self._completion_reminder_lock:
            return self._completion_reminder_counts.get(thread_id, 0)

    def _pop_pending_completion_reminder(self, thread_id: str) -> HumanMessage | None:
        with self._completion_reminder_lock:
            return self._pending_completion_reminders.pop(thread_id, None)

    def before_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        """Clear stale completion reminders at run start."""
        self._clear_completion_reminder_state(self._thread_id(runtime))
        return None

    def after_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        """Clear queued completion reminders at run end."""
        self._clear_completion_reminder_state(self._thread_id(runtime))
        return None

    async def abefore_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        """Async version of before_agent."""
        return self.before_agent(state, runtime)

    async def aafter_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        """Async version of after_agent."""
        return self.after_agent(state, runtime)

    @override
    def before_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Inject a todo-list reminder when write_todos has left the context window."""
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos:
            return None

        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            # write_todos is still visible in context — nothing to do.
            return None

        if _reminder_in_messages(messages):
            # A reminder was already injected and hasn't been truncated yet.
            return None

        # The todo list exists in state but the original write_todos call is gone.
        # Inject a reminder as a HumanMessage so the model stays aware.
        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_reminder",
            content=(
                "<system_reminder>\n"
                "Your todo list from earlier is no longer visible in the current context window, "
                "but it is still active. Here is the current state:\n\n"
                f"{formatted}\n\n"
                "Continue tracking and updating this todo list as you work. "
                "Call `write_todos` whenever the status of any item changes.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder]}

    @override
    async def abefore_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Async version of before_model."""
        return self.before_model(state, runtime)

    # Maximum number of completion reminders before allowing the agent to exit.
    # This prevents infinite loops when the agent cannot make further progress.
    _MAX_COMPLETION_REMINDERS = 2

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Prevent premature agent exit when todo items are still incomplete.

        In addition to the base class check for parallel ``write_todos`` calls,
        this override intercepts model responses that have no tool calls while
        there are still incomplete todo items. It queues a transient reminder
        ``HumanMessage`` and jumps back to the model node so the agent
        continues working through the todo list.

        A retry cap of ``_MAX_COMPLETION_REMINDERS`` (default 2) prevents
        infinite loops when the agent cannot make further progress.
        """
        # 1. Preserve base class logic (parallel write_todos detection).
        base_result = super().after_model(state, runtime)
        if base_result is not None:
            return base_result

        thread_id = self._thread_id(runtime)

        # 2. Only intervene when the agent wants to exit (no tool calls).
        messages = state.get("messages") or []
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if not last_ai or last_ai.tool_calls:
            return None
        if getattr(last_ai, "invalid_tool_calls", None):
            return {"jump_to": "model"}

        # 3. Allow exit when all todos are completed or there are no todos.
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos or all(t.get("status") == "completed" for t in todos):
            self._clear_completion_reminder_state(thread_id)
            return None

        # 4. Enforce a reminder cap to prevent infinite re-engagement loops.
        persisted_count = _completion_reminder_count(messages)
        transient_count = self._completion_reminder_count_for_thread(thread_id)
        if max(persisted_count, transient_count) >= self._MAX_COMPLETION_REMINDERS:
            return None

        # 5. Queue a transient reminder and force the agent back to the model.
        # The reminder is injected in wrap_model_call so it is visible to the
        # model but never persisted or streamed as a normal conversation message.
        incomplete = [t for t in todos if t.get("status") != "completed"]
        incomplete_text = "\n".join(f"- [{t.get('status', 'pending')}] {t.get('content', '')}" for t in incomplete)
        reminder = HumanMessage(
            name="todo_completion_reminder",
            content=(
                "<system_reminder>\n"
                "You have incomplete todo items that must be finished before giving your final response:\n\n"
                f"{incomplete_text}\n\n"
                "Please continue working on these tasks. Call `write_todos` to mark items as completed "
                "as you finish them, and only respond when all items are done.\n"
                "</system_reminder>"
            ),
        )
        self._queue_completion_reminder(thread_id, reminder)
        return {"jump_to": "model"}

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        thread_id = self._thread_id(request.runtime)
        reminder = self._pop_pending_completion_reminder(thread_id)
        if reminder is not None:
            request = request.override(messages=[*request.messages, reminder])
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        thread_id = self._thread_id(request.runtime)
        reminder = self._pop_pending_completion_reminder(thread_id)
        if reminder is not None:
            request = request.override(messages=[*request.messages, reminder])
        return await handler(request)

    @override
    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Async version of after_model."""
        return self.after_model(state, runtime)

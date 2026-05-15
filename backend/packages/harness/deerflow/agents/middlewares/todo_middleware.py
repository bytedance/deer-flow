"""Middleware that extends TodoListMiddleware with context-loss detection and premature-exit prevention.

When the message history is truncated (e.g., by SummarizationMiddleware), the
original `write_todos` tool call and its ToolMessage can be scrolled out of the
active context window. This middleware detects that situation and injects a
reminder message so the model still knows about the outstanding todo list.

Additionally, this middleware prevents the agent from exiting the loop while
there are still incomplete todo items. When the model produces a final response
(no tool calls) but todos are not yet complete, the middleware queues a reminder
for the next model request and jumps back to the model node to force continued
engagement. The completion reminder is injected via ``wrap_model_call`` instead
of being persisted into graph state as a normal user-visible message.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
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


def _format_completion_reminder(todos: list[Todo]) -> str:
    """Format a completion reminder for incomplete todo items."""
    incomplete = [t for t in todos if t.get("status") != "completed"]
    incomplete_text = "\n".join(f"- [{t.get('status', 'pending')}] {t.get('content', '')}" for t in incomplete)
    return (
        "<system_reminder>\n"
        "You have incomplete todo items that must be finished before giving your final response:\n\n"
        f"{incomplete_text}\n\n"
        "Please continue working on these tasks. Call `write_todos` to mark items as completed "
        "as you finish them, and only respond when all items are done.\n"
        "</system_reminder>"
    )


_TOOL_CALL_FINISH_REASONS = {"tool_calls", "function_call"}


def _has_tool_call_intent_or_error(message: AIMessage) -> bool:
    """Return True when an AIMessage is not a clean final answer.

    Todo completion reminders should only fire when the model has produced a
    plain final response. Provider/tool parsing details have moved across
    LangChain versions and integrations, so keep all tool-intent/error signals
    behind this helper instead of checking one concrete field at the call site.
    """
    if message.tool_calls:
        return True

    if getattr(message, "invalid_tool_calls", None):
        return True

    # Backward/provider compatibility: some integrations preserve raw or legacy
    # tool-call intent in additional_kwargs even when structured tool_calls is
    # empty. If this helper changes, update the matching sentinel test
    # `TestToolCallIntentOrError.test_langchain_ai_message_tool_fields_are_explicitly_handled`;
    # if that test fails after a LangChain upgrade, review this helper so new
    # tool-call/error fields are not silently treated as clean final answers.
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    if additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"):
        return True

    response_metadata = getattr(message, "response_metadata", {}) or {}
    return response_metadata.get("finish_reason") in _TOOL_CALL_FINISH_REASONS


class TodoMiddleware(TodoListMiddleware):
    """Extends TodoListMiddleware with `write_todos` context-loss detection.

    When the original `write_todos` tool call has been truncated from the message
    history (e.g., after summarization), the model loses awareness of the current
    todo list. This middleware detects that gap in `before_model` / `abefore_model`
    and injects a reminder message so the model can continue tracking progress.
    """

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
            additional_kwargs={"hide_from_ui": True},
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
    # Hard cap for per-run reminder bookkeeping in long-lived middleware instances.
    _MAX_COMPLETION_REMINDER_KEYS = 4096

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        self._pending_completion_reminders: dict[tuple[str, str], list[str]] = {}
        self._completion_reminder_counts: dict[tuple[str, str], int] = {}
        self._completion_reminder_touch_order: dict[tuple[str, str], int] = {}
        self._completion_reminder_next_order = 0

    @staticmethod
    def _get_thread_id(runtime: Runtime) -> str:
        context = getattr(runtime, "context", None)
        thread_id = context.get("thread_id") if context else None
        return str(thread_id) if thread_id else "default"

    @staticmethod
    def _get_run_id(runtime: Runtime) -> str:
        context = getattr(runtime, "context", None)
        run_id = context.get("run_id") if context else None
        return str(run_id) if run_id else "default"

    def _pending_key(self, runtime: Runtime) -> tuple[str, str]:
        return self._get_thread_id(runtime), self._get_run_id(runtime)

    def _touch_completion_reminder_key_locked(self, key: tuple[str, str]) -> None:
        self._completion_reminder_next_order += 1
        self._completion_reminder_touch_order[key] = self._completion_reminder_next_order

    def _completion_reminder_keys_locked(self) -> set[tuple[str, str]]:
        keys = set(self._pending_completion_reminders)
        keys.update(self._completion_reminder_counts)
        keys.update(self._completion_reminder_touch_order)
        return keys

    def _drop_completion_reminder_key_locked(self, key: tuple[str, str]) -> None:
        self._pending_completion_reminders.pop(key, None)
        self._completion_reminder_counts.pop(key, None)
        self._completion_reminder_touch_order.pop(key, None)

    def _prune_completion_reminder_state_locked(self, protected_key: tuple[str, str]) -> None:
        keys = self._completion_reminder_keys_locked()
        overflow = len(keys) - self._MAX_COMPLETION_REMINDER_KEYS
        if overflow <= 0:
            return

        candidates = [key for key in keys if key != protected_key]
        candidates.sort(key=lambda key: self._completion_reminder_touch_order.get(key, 0))
        for key in candidates[:overflow]:
            self._drop_completion_reminder_key_locked(key)

    def _queue_completion_reminder(self, runtime: Runtime, reminder: str) -> None:
        key = self._pending_key(runtime)
        with self._lock:
            self._pending_completion_reminders.setdefault(key, []).append(reminder)
            self._completion_reminder_counts[key] = self._completion_reminder_counts.get(key, 0) + 1
            self._touch_completion_reminder_key_locked(key)
            self._prune_completion_reminder_state_locked(protected_key=key)

    def _completion_reminder_count_for_runtime(self, runtime: Runtime) -> int:
        key = self._pending_key(runtime)
        with self._lock:
            return self._completion_reminder_counts.get(key, 0)

    def _drain_completion_reminders(self, runtime: Runtime) -> list[str]:
        key = self._pending_key(runtime)
        with self._lock:
            reminders = self._pending_completion_reminders.pop(key, [])
            if reminders or key in self._completion_reminder_counts:
                self._touch_completion_reminder_key_locked(key)
            return reminders

    def _clear_other_run_completion_reminders(self, runtime: Runtime) -> None:
        thread_id, current_run_id = self._pending_key(runtime)
        with self._lock:
            for key in self._completion_reminder_keys_locked():
                if key[0] == thread_id and key[1] != current_run_id:
                    self._drop_completion_reminder_key_locked(key)

    def _clear_current_run_completion_reminders(self, runtime: Runtime) -> None:
        key = self._pending_key(runtime)
        with self._lock:
            self._drop_completion_reminder_key_locked(key)

    @override
    def before_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        self._clear_other_run_completion_reminders(runtime)
        return None

    @override
    async def abefore_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        self._clear_other_run_completion_reminders(runtime)
        return None

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
        there are still incomplete todo items. It injects a reminder
        ``HumanMessage`` and jumps back to the model node so the agent
        continues working through the todo list.

        A retry cap of ``_MAX_COMPLETION_REMINDERS`` (default 2) prevents
        infinite loops when the agent cannot make further progress.
        """
        # 1. Preserve base class logic (parallel write_todos detection).
        base_result = super().after_model(state, runtime)
        if base_result is not None:
            return base_result

        # 2. Only intervene when the agent wants to exit cleanly. Tool-call
        # intent or tool-call parse errors should be handled by the tool path
        # instead of being masked by todo reminders.
        messages = state.get("messages") or []
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if not last_ai or _has_tool_call_intent_or_error(last_ai):
            return None

        # 3. Allow exit when all todos are completed or there are no todos.
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos or all(t.get("status") == "completed" for t in todos):
            return None

        # 4. Enforce a reminder cap to prevent infinite re-engagement loops.
        if self._completion_reminder_count_for_runtime(runtime) >= self._MAX_COMPLETION_REMINDERS:
            return None

        # 5. Queue a reminder for the next model request and jump back. We must
        # not persist this control prompt as a normal HumanMessage, otherwise it
        # can leak into user-visible message streams and saved transcripts.
        self._queue_completion_reminder(runtime, _format_completion_reminder(todos))
        return {"jump_to": "model"}

    @override
    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Async version of after_model."""
        return self.after_model(state, runtime)

    @staticmethod
    def _format_pending_completion_reminders(reminders: list[str]) -> str:
        return "\n\n".join(dict.fromkeys(reminders))

    def _augment_request(self, request: ModelRequest) -> ModelRequest:
        reminders = self._drain_completion_reminders(request.runtime)
        if not reminders:
            return request
        new_messages = [
            *request.messages,
            HumanMessage(
                content=self._format_pending_completion_reminders(reminders),
                name="todo_completion_reminder",
                additional_kwargs={"hide_from_ui": True},
            ),
        ]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._augment_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._augment_request(request))

    @override
    def after_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        self._clear_current_run_completion_reminders(runtime)
        return None

    @override
    async def aafter_agent(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        self._clear_current_run_completion_reminders(runtime)
        return None

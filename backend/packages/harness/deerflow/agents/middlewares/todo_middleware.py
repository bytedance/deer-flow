"""中间件 that extends TodoListMiddleware with context-loss detection.

When the 消息 history is truncated (e.g., by SummarizationMiddleware), the
original `write_todos` 工具 call and its ToolMessage can be scrolled out of the
活跃 context window. This 中间件 detects that situation and injects a
reminder 消息 so the 模型 still knows about the outstanding 待办 列表.
"""

from __future__ import annotations

from typing import Any, override

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.todo import PlanningState, Todo
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime


def _todos_in_messages(messages: list[Any]) -> bool:
    """Return True if any AIMessage in *messages* contains a write_todos 工具 call."""
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


def _format_todos(todos: list[Todo]) -> str:
    """Format a 列表 of Todo items into a human-readable 字符串."""
    lines: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


class TodoMiddleware(TodoListMiddleware):
    """Extends TodoListMiddleware with `write_todos` context-loss detection.

    When the original `write_todos` 工具 call has been truncated from the 消息
    history (e.g., after summarization), the 模型 loses awareness of the 当前
    待办 列表. This 中间件 detects that gap in `before_model` / `abefore_model`
    and injects a reminder 消息 so the 模型 can continue tracking progress.
    """

    @override
    def before_model(
        self,
        state: PlanningState,
        runtime: Runtime,  #    noqa: ARG002


    ) -> dict[str, Any] | None:
        """Inject a 待办-列表 reminder when write_todos has 左 the context window."""
        todos: list[Todo] = state.get("todos") or []  #    类型: ignore[assignment]


        if not todos:
            return None

        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            #    write_todos is still 可见 in context — nothing to do.


            return None

        if _reminder_in_messages(messages):
            #    A reminder was already injected and hasn't been truncated yet.


            return None

        #    The 待办 列表 exists in 状态 but the original write_todos call is gone.


        #    Inject a reminder as a HumanMessage so the 模型 stays aware.


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

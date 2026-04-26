"""
TODO中间件 - 扩展TodoListMiddleware以检测上下文丢失

===================
设计思路说明
===================

**核心职责**：
检测并恢复因上下文截断而丢失的TODO列表：
1. **上下文丢失检测**：当消息历史被截断时检测write_todos调用丢失
2. **提醒注入**：注入提醒消息让模型知道当前TODO列表
3. **去重机制**：避免重复注入相同的提醒

**为什么需要这个中间件**：
1. **摘要截断**：SummarizationMiddleware会截断消息历史
2. **工具调用丢失**：write_todos调用可能被截断出上下文窗口
3. **状态保持**：确保模型始终知道当前的TODO状态
4. **任务连续性**：防止因上下文丢失导致任务中断

**设计决策**：
- 继承TodoListMiddleware：复用基础TODO功能
- 在before_model中检测：模型调用前检查上下文
- 使用HumanMessage：与所有模型兼容
- 命名消息：使用name字段去重

**为什么使用HumanMessage**：
- 兼容性：所有模型都支持
- 非侵入：不像SystemMessage有位置限制
- 可识别：使用特殊name便于识别

**工作流程**：
1. 检查state中是否有todos
2. 检查messages中是否有write_todos调用
3. 如果todos存在但write_todos丢失，注入提醒
4. 格式化TODO列表为可读文本
"""

from __future__ import annotations

from typing import Any, override

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.todo import PlanningState, Todo
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


def _format_todos(todos: list[Todo]) -> str:
    """Format a list of Todo items into a human-readable string."""
    lines: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


class TodoMiddleware(TodoListMiddleware):
    """扩展TodoListMiddleware，添加`write_todos`上下文丢失检测

    **为什么需要扩展TodoListMiddleware**：
    - **上下文截断**：摘要等操作会截断消息历史
    - **工具调用丢失**：原始write_todos调用可能被截出上下文窗口
    - **状态恢复**：检测并恢复丢失的TODO列表意识

    **工作原理**：
    当原始`write_todos`工具调用已从消息历史中截断
    （例如在摘要后），模型失去对当前todo列表的意识。
    此中间件在`before_model`/`abefore_model`中检测该缺口
    并注入提醒消息，以便模型可以继续跟踪进度。

    **检测策略**：
    1. 检查state中是否有todos
    2. 检查messages中是否还有write_todos调用
    3. 检查是否已注入提醒
    4. 如果需要，格式化并注入TODO提醒

    **为什么使用name字段**：
    - **去重机制**：避免重复注入相同提醒
    - **可识别性**：便于检测已注入的提醒
    - **隔离性**：不影响其他HumanMessage
    """

    @override
    def before_model(
        self,
        state: PlanningState,
        runtime: Runtime,  # noqa: ARG002
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

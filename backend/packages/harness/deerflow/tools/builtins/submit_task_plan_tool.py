from typing import NotRequired, TypedDict

from langchain_core.tools import tool

from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.task_graph.factory import create_task_graph
from deerflow.task_graph.models import CodingTask
from deerflow.tools.types import Runtime


class CodingTaskInput(TypedDict):
    """主 Agent 提交的一条任务计划。"""

    id: str
    subject: str
    description: str
    blocked_by: NotRequired[list[str]]
    agent_type: NotRequired[str]


@tool("submit_task_plan", parse_docstring=True)
def submit_task_plan(tasks: list[CodingTaskInput], runtime: Runtime) -> str:
    """为当前线程提交一份完整的编码任务计划。

    保存任何任务之前会先校验整份计划。任务 ID 必须保持稳定，
    前置依赖通过 ``blocked_by`` 引用其他任务 ID。

    Args:
        tasks: 完整任务计划。每一项包含 ID、标题、详细描述，
            以及可选的前置依赖任务 ID 列表。
    """
    # thread_id 优先从运行上下文获取，兼容旧调用时再从 configurable 兜底。
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if thread_id is None:
        raise ValueError("thread_id is required")

    user_id = resolve_runtime_user_id(runtime)
    graph = create_task_graph(thread_id, user_id=user_id)
    coding_tasks = [
        CodingTask(
            id=item["id"],
            subject=item["subject"],
            description=item["description"],
            blocked_by=list(item.get("blocked_by", [])),
            agent_type=item.get("agent_type"),
        )
        for item in tasks
    ]
    saved_tasks = graph.add_tasks(coding_tasks)
    task_ids = ", ".join(task.id for task in saved_tasks)
    return f"Saved {len(saved_tasks)} coding tasks: {task_ids}"

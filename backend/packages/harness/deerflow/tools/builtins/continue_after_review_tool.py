"""在审查不通过后，经人工批准追加重新分析、修复和复审任务。"""

from collections.abc import Mapping

from langchain_core.tools import tool

from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.task_graph.factory import create_task_graph
from deerflow.task_graph.models import CodingTask, TaskStatus
from deerflow.tools.builtins.recover_coding_task_tool import (
    _has_matching_approval,
    _runtime_messages,
)
from deerflow.tools.types import Runtime

REANALYZE_AND_FIX_OPTION = "Reanalyze and fix"
REVIEW_FOLLOWUP_CONTEXT_PREFIX = "coding_review_followup:"


def _runtime_thread_id(runtime: Runtime) -> str:
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if thread_id is None:
        raise ValueError("thread_id is required")
    return thread_id


def _is_failed_review(task: CodingTask) -> bool:
    artifact = task.artifact
    return task.status is TaskStatus.completed and isinstance(artifact, Mapping) and artifact.get("report_type") == "review_report" and artifact.get("verdict") == "FAIL"


@tool("continue_after_review", parse_docstring=True)
def continue_after_review(review_task_id: str, runtime: Runtime) -> str:
    """在用户明确批准后，针对 FAIL 的审查追加重新分析、修复和复审任务。

    Args:
        review_task_id: 已完成且 Artifact verdict 为 FAIL 的审查任务 ID。
    """
    thread_id = _runtime_thread_id(runtime)
    expected_context = f"{REVIEW_FOLLOWUP_CONTEXT_PREFIX}{review_task_id}"
    if not _has_matching_approval(
        _runtime_messages(runtime),
        expected_context=expected_context,
        expected_option_value=REANALYZE_AND_FIX_OPTION,
    ):
        raise ValueError("matching review follow-up approval is required")

    user_id = resolve_runtime_user_id(runtime)
    graph = create_task_graph(thread_id, user_id=user_id)
    review_task = graph.store.load(review_task_id)
    if not _is_failed_review(review_task):
        raise ValueError("review task must be completed with review_report verdict FAIL")
    if not review_task.worktree:
        raise ValueError("failed review task must have a bound worktree")

    reanalysis_id = f"{review_task_id}-reanalysis"
    fix_id = f"{review_task_id}-fix"
    rereview_id = f"{review_task_id}-rereview"
    followup_tasks = [
        CodingTask(
            id=reanalysis_id,
            subject="Reanalyze failed review",
            description=("Inspect the current worktree and the failed review report. Reassess the root cause and produce an updated analysis report."),
            blocked_by=[review_task_id],
            agent_type="code-analyzer",
        ),
        CodingTask(
            id=fix_id,
            subject="Fix failed review findings",
            description=("Use the updated analysis and failed review findings to make the smallest complete fix in the existing coding worktree."),
            blocked_by=[reanalysis_id],
            agent_type="code-implementer",
        ),
        CodingTask(
            id=rereview_id,
            subject="Review follow-up fix",
            description=("Independently verify the follow-up fix against the original acceptance criteria and failed review findings."),
            blocked_by=[fix_id],
            agent_type="code-reviewer",
        ),
    ]
    graph.add_tasks(followup_tasks)
    graph.bind_worktree([task.id for task in followup_tasks], review_task.worktree)

    run_plan = graph.get_run_plan()
    graph.save_run_plan(
        run_plan.coding_brief,
        [*run_plan.task_ids, *(task.id for task in followup_tasks)],
    )
    return f"Added review follow-up tasks: {reanalysis_id}, {fix_id}, {rereview_id}; bound to {review_task.worktree}"

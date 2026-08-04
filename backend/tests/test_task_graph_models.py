from deerflow.task_graph.models import CodingTask, TaskStatus


def test_coding_task_has_safe_defaults():
    task = CodingTask(
        id="task-1",
        subject="Implement login validation",
        description="Reject invalid credentials",
    )

    assert task.status is TaskStatus.pending
    assert task.owner is None
    assert task.failure_reason is None
    assert task.blocked_by == []
    assert task.worktree is None


def test_coding_tasks_do_not_share_blocked_by_list():
    first = CodingTask(id="task-1", subject="First", description="First task")
    second = CodingTask(id="task-2", subject="Second", description="Second task")

    first.blocked_by.append("task-0")

    assert second.blocked_by == []


def test_task_status_values_are_stable_for_persistence():
    assert [status.value for status in TaskStatus] == [
        "pending",
        "in_progress",
        "completed",
        "failed",
    ]

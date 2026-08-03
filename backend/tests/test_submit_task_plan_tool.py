from types import SimpleNamespace

import pytest

from deerflow.task_graph.models import CodingTask
from deerflow.tools.builtins.submit_task_plan_tool import submit_task_plan


def _runtime(*, thread_id: str | None = "thread-1") -> SimpleNamespace:
    context = {} if thread_id is None else {"thread_id": thread_id}
    return SimpleNamespace(context=context, config={"configurable": {}})


def test_submit_task_plan_converts_model_input_and_uses_thread_graph(monkeypatch):
    captured: dict = {}

    class FakeGraph:
        def add_tasks(self, tasks):
            captured["tasks"] = tasks
            return tasks

    def fake_create_task_graph(thread_id, *, user_id):
        captured["thread_id"] = thread_id
        captured["user_id"] = user_id
        return FakeGraph()

    monkeypatch.setattr(
        "deerflow.tools.builtins.submit_task_plan_tool.resolve_runtime_user_id",
        lambda runtime: "alice",
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.submit_task_plan_tool.create_task_graph",
        fake_create_task_graph,
    )

    result = submit_task_plan.func(
        tasks=[
            {
                "id": "task-1",
                "subject": "Analyze",
                "description": "Analyze the change",
            },
            {
                "id": "task-2",
                "subject": "Implement",
                "description": "Implement the change",
                "blocked_by": ["task-1"],
            },
        ],
        runtime=_runtime(),
    )

    assert captured == {
        "thread_id": "thread-1",
        "user_id": "alice",
        "tasks": [
            CodingTask(id="task-1", subject="Analyze", description="Analyze the change"),
            CodingTask(
                id="task-2",
                subject="Implement",
                description="Implement the change",
                blocked_by=["task-1"],
            ),
        ],
    }
    assert result == "Saved 2 coding tasks: task-1, task-2"


def test_submit_task_plan_requires_thread_id(monkeypatch):
    monkeypatch.setattr(
        "deerflow.tools.builtins.submit_task_plan_tool.resolve_runtime_user_id",
        lambda runtime: "alice",
    )

    with pytest.raises(ValueError, match="thread_id is required"):
        submit_task_plan.func(
            tasks=[{"id": "task-1", "subject": "Analyze", "description": "Analyze"}],
            runtime=_runtime(thread_id=None),
        )

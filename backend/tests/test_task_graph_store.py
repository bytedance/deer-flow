import json

from deerflow.task_graph.models import CodingTask, TaskStatus
from deerflow.task_graph.store import JsonTaskStore


def test_save_and_load_task_round_trip(tmp_path):
    store = JsonTaskStore(tmp_path / "tasks")
    task = CodingTask(
        id="task-1",
        subject="Implement login validation",
        description="Reject invalid credentials",
        status=TaskStatus.in_progress,
        owner="code-implementer",
        blocked_by=["task-0"],
    )

    store.save(task)
    loaded = store.load(task.id)

    assert loaded == task
    assert loaded.status is TaskStatus.in_progress
    assert (
        json.loads((tmp_path / "tasks" / "task-1.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "in_progress"
    )


def test_stores_with_different_roots_are_isolated(tmp_path):
    first_store = JsonTaskStore(tmp_path / "thread-1" / "tasks")
    second_store = JsonTaskStore(tmp_path / "thread-2" / "tasks")
    first_store.save(
        CodingTask(id="task-1", subject="Thread one", description="First thread task")
    )
    second_store.save(
        CodingTask(id="task-1", subject="Thread two", description="Second thread task")
    )

    assert first_store.load("task-1").subject == "Thread one"
    assert second_store.load("task-1").subject == "Thread two"


def test_list_all_returns_tasks_in_id_order(tmp_path):
    store = JsonTaskStore(tmp_path / "tasks")
    store.save(CodingTask(id="task-2", subject="Second", description="Second task"))
    store.save(CodingTask(id="task-1", subject="First", description="First task"))

    assert [task.id for task in store.list_all()] == ["task-1", "task-2"]

import pytest

from deerflow.task_graph.models import CodingTask, TaskStatus
from deerflow.task_graph.service import TaskGraph
from deerflow.task_graph.store import JsonTaskStore


@pytest.fixture
def task_graph(tmp_path):
    store = JsonTaskStore(tmp_path / "tasks")
    return TaskGraph(store), store


def test_can_start_requires_every_dependency_to_exist_and_be_completed(task_graph):
    graph, store = task_graph
    store.save(
        CodingTask(
            id="task-2",
            subject="Implement",
            description="Implement change",
            blocked_by=["task-1"],
        )
    )

    assert graph.can_start("task-2") is False

    store.save(CodingTask(id="task-1", subject="Analyze", description="Analyze change"))
    assert graph.can_start("task-2") is False

    dependency = store.load("task-1")
    dependency.status = TaskStatus.completed
    store.save(dependency)
    assert graph.can_start("task-2") is True


def test_can_start_allows_task_without_dependencies(task_graph):
    graph, store = task_graph
    store.save(CodingTask(id="task-1", subject="Analyze", description="Analyze change"))

    assert graph.can_start("task-1") is True


def test_claim_persists_owner_and_in_progress_status(task_graph):
    graph, store = task_graph
    store.save(CodingTask(id="task-1", subject="Analyze", description="Analyze change"))

    claimed = graph.claim("task-1", "code-analyzer")

    assert claimed.owner == "code-analyzer"
    assert claimed.status is TaskStatus.in_progress
    assert store.load("task-1") == claimed


def test_claim_rejects_non_pending_or_blocked_task(task_graph):
    graph, store = task_graph
    store.save(
        CodingTask(
            id="task-1",
            subject="Already running",
            description="Cannot claim twice",
            status=TaskStatus.in_progress,
        )
    )
    store.save(
        CodingTask(
            id="task-2",
            subject="Blocked",
            description="Wait for missing dependency",
            blocked_by=["missing-task"],
        )
    )

    with pytest.raises(ValueError, match="pending"):
        graph.claim("task-1", "code-analyzer")
    with pytest.raises(ValueError, match="blocked"):
        graph.claim("task-2", "code-implementer")


def test_complete_persists_status_and_returns_newly_ready_task_ids(task_graph):
    graph, store = task_graph
    store.save(
        CodingTask(
            id="task-1",
            subject="Analyze",
            description="Analyze change",
            status=TaskStatus.in_progress,
            owner="code-analyzer",
        )
    )
    store.save(
        CodingTask(
            id="task-2",
            subject="Implement",
            description="Implement change",
            blocked_by=["task-1"],
        )
    )
    store.save(
        CodingTask(id="task-3", subject="Independent", description="No dependencies")
    )
    store.save(
        CodingTask(
            id="task-4",
            subject="Still blocked",
            description="Missing dependency",
            blocked_by=["missing-task"],
        )
    )

    unblocked = graph.complete("task-1")

    assert store.load("task-1").status is TaskStatus.completed
    assert unblocked == ["task-2"]


def test_complete_rejects_task_that_is_not_in_progress(task_graph):
    graph, store = task_graph
    store.save(CodingTask(id="task-1", subject="Pending", description="Not started"))

    with pytest.raises(ValueError, match="in_progress"):
        graph.complete("task-1")


def test_fail_persists_reason_and_requires_in_progress(task_graph):
    graph, store = task_graph
    store.save(
        CodingTask(
            id="task-1",
            subject="Implement",
            description="Implement change",
            status=TaskStatus.in_progress,
            owner="code-implementer",
        )
    )

    failed = graph.fail("task-1", "tests failed")

    assert failed.status is TaskStatus.failed
    assert failed.owner == "code-implementer"
    assert failed.failure_reason == "tests failed"
    assert store.load("task-1") == failed

    store.save(CodingTask(id="task-2", subject="Pending", description="Not started"))
    with pytest.raises(ValueError, match="in_progress"):
        graph.fail("task-2", "should not fail")


def test_recover_resets_failed_task_for_a_new_claim(task_graph):
    graph, store = task_graph
    store.save(
        CodingTask(
            id="task-1",
            subject="Implement",
            description="Implement change",
            status=TaskStatus.failed,
            owner="code-implementer",
            failure_reason="tests failed",
        )
    )

    recovered = graph.recover("task-1")

    assert recovered.status is TaskStatus.pending
    assert recovered.owner is None
    assert recovered.failure_reason is None
    assert store.load("task-1") == recovered

    store.save(
        CodingTask(
            id="task-2",
            subject="Running",
            description="Still running",
            status=TaskStatus.in_progress,
        )
    )
    with pytest.raises(ValueError, match="failed"):
        graph.recover("task-2")


def test_bind_worktree_persists_one_worktree_for_the_whole_pipeline(task_graph):
    graph, store = task_graph
    tasks = [
        CodingTask(
            id="coding-analysis", subject="Analyze", description="Analyze change"
        ),
        CodingTask(
            id="coding-implementation",
            subject="Implement",
            description="Implement change",
            blocked_by=["coding-analysis"],
        ),
        CodingTask(
            id="coding-review",
            subject="Review",
            description="Review change",
            blocked_by=["coding-implementation"],
        ),
    ]
    graph.add_tasks(tasks)

    bound = graph.bind_worktree([task.id for task in tasks], "coding-run")

    assert [task.worktree for task in bound] == ["coding-run"] * 3
    assert all(task.status is TaskStatus.pending for task in bound)
    assert [store.load(task.id).worktree for task in tasks] == ["coding-run"] * 3


def test_bind_worktree_validates_the_whole_batch_before_persisting(task_graph):
    graph, store = task_graph
    store.save(
        CodingTask(
            id="coding-analysis", subject="Analyze", description="Analyze change"
        )
    )

    with pytest.raises(FileNotFoundError):
        graph.bind_worktree(["coding-analysis", "missing-task"], "coding-run")

    assert store.load("coding-analysis").worktree is None


def test_add_tasks_validates_the_whole_batch_before_persisting(task_graph):
    graph, store = task_graph
    tasks = [
        CodingTask(
            id="task-2",
            subject="Implement",
            description="Implement change",
            blocked_by=["task-1"],
        ),
        CodingTask(id="task-1", subject="Analyze", description="Analyze change"),
    ]

    added = graph.add_tasks(tasks)

    assert added == tasks
    assert store.list_all() == [tasks[1], tasks[0]]


def test_add_tasks_rejects_duplicate_ids_without_persisting(task_graph):
    graph, store = task_graph
    tasks = [
        CodingTask(id="task-1", subject="Analyze", description="Analyze change"),
        CodingTask(id="task-1", subject="Implement", description="Implement change"),
    ]

    with pytest.raises(ValueError, match="duplicate"):
        graph.add_tasks(tasks)

    assert store.list_all() == []


def test_add_tasks_rejects_missing_dependencies_without_persisting(task_graph):
    graph, store = task_graph
    tasks = [
        CodingTask(
            id="task-1",
            subject="Implement",
            description="Implement change",
            blocked_by=["missing-task"],
        )
    ]

    with pytest.raises(ValueError, match="missing"):
        graph.add_tasks(tasks)

    assert store.list_all() == []


@pytest.mark.parametrize(
    "tasks",
    [
        [
            CodingTask(
                id="task-1",
                subject="Analyze",
                description="Analyze change",
                blocked_by=["task-1"],
            )
        ],
        [
            CodingTask(
                id="task-1",
                subject="Analyze",
                description="Analyze change",
                blocked_by=["task-2"],
            ),
            CodingTask(
                id="task-2",
                subject="Implement",
                description="Implement change",
                blocked_by=["task-1"],
            ),
        ],
    ],
    ids=["self-cycle", "multi-task-cycle"],
)
def test_add_tasks_rejects_cycles_without_persisting(task_graph, tasks):
    graph, store = task_graph

    with pytest.raises(ValueError, match="cycle"):
        graph.add_tasks(tasks)

    assert store.list_all() == []

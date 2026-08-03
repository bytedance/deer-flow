from deerflow.config.paths import Paths
from deerflow.task_graph.factory import create_task_graph
from deerflow.task_graph.models import CodingTask, TaskStatus


def test_create_task_graph_uses_thread_scoped_storage_and_recovers_tasks(tmp_path):
    paths = Paths(tmp_path)
    graph = create_task_graph("thread-1", user_id="alice", paths=paths)
    task = CodingTask(id="task-1", subject="Analyze", description="Analyze change")

    graph.add_tasks([task])

    recovered = create_task_graph("thread-1", user_id="alice", paths=paths)
    assert recovered.store.root == paths.thread_dir("thread-1", user_id="alice") / "coding-tasks"
    assert recovered.store.load("task-1") == task


def test_create_task_graph_isolates_users_and_threads(tmp_path):
    paths = Paths(tmp_path)
    alice_first = create_task_graph("thread-1", user_id="alice", paths=paths)
    alice_second = create_task_graph("thread-2", user_id="alice", paths=paths)
    bob_first = create_task_graph("thread-1", user_id="bob", paths=paths)

    alice_first.add_tasks([CodingTask(id="task-1", subject="Alice first", description="First thread")])
    alice_second.add_tasks([CodingTask(id="task-1", subject="Alice second", description="Second thread")])
    bob_first.add_tasks([CodingTask(id="task-1", subject="Bob first", description="Different user")])

    assert alice_first.store.load("task-1").subject == "Alice first"
    assert alice_second.store.load("task-1").subject == "Alice second"
    assert bob_first.store.load("task-1").subject == "Bob first"


def test_task_graph_recovers_failed_dependent_task_across_instances(tmp_path):
    paths = Paths(tmp_path)
    graph = create_task_graph("thread-1", user_id="alice", paths=paths)
    graph.add_tasks(
        [
            CodingTask(id="coding-analysis", subject="Analyze", description="Analyze the code"),
            CodingTask(
                id="coding-implementation",
                subject="Implement",
                description="Implement the change",
                blocked_by=["coding-analysis"],
            ),
        ]
    )

    graph.claim("coding-analysis", owner="code-analyzer")
    assert graph.complete("coding-analysis") == ["coding-implementation"]

    graph.claim("coding-implementation", owner="code-implementer")
    graph.fail("coding-implementation", reason="tests failed")

    restarted = create_task_graph("thread-1", user_id="alice", paths=paths)
    failed = restarted.store.load("coding-implementation")
    assert failed.status is TaskStatus.failed
    assert failed.owner == "code-implementer"
    assert failed.failure_reason == "tests failed"

    recovered = restarted.recover("coding-implementation")
    assert recovered.status is TaskStatus.pending
    assert recovered.owner is None
    assert recovered.failure_reason is None

    reclaimed = restarted.claim("coding-implementation", owner="code-implementer-retry")
    assert reclaimed.status is TaskStatus.in_progress
    assert reclaimed.owner == "code-implementer-retry"

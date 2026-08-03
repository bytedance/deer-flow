from deerflow.config.paths import Paths, get_paths

from .service import TaskGraph
from .store import JsonTaskStore


def create_task_graph(
    thread_id: str,
    *,
    user_id: str,
    paths: Paths | None = None,
) -> TaskGraph:
    """根据 user_id + thread_id 创建本线程的 TaskGraph"""
    if paths is None:
        paths = get_paths()
    task_path = paths.thread_dir(thread_id, user_id=user_id) / "coding-tasks"
    store = JsonTaskStore(task_path)
    return TaskGraph(store)

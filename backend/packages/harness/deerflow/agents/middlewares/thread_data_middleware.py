from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ThreadDataState
from deerflow.config.paths import Paths, get_paths


class ThreadDataMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    thread_data: NotRequired[ThreadDataState | None]


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """Create 线程 数据 directories for each 线程 execution.

    Creates the following 目录 structure:
    - {base_dir}/threads/{thread_id}/用户-数据/工作区
    - {base_dir}/threads/{thread_id}/用户-数据/uploads
    - {base_dir}/threads/{thread_id}/用户-数据/outputs

    Lifecycle Management:
    - With lazy_init=True (默认): Only compute paths, directories created on-demand
    - With lazy_init=False: Eagerly 创建 directories in before_agent()
    """

    state_schema = ThreadDataMiddlewareState

    def __init__(self, base_dir: str | None = None, lazy_init: bool = True):
        """Initialize the 中间件.

        Args:
            base_dir: Base 目录 for 线程 数据. Defaults to Paths resolution.
            lazy_init: If True, defer 目录 creation until needed.
                      If False, 创建 directories eagerly in before_agent().
                      Default is True for optimal performance.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()
        self._lazy_init = lazy_init

    def _get_thread_paths(self, thread_id: str) -> dict[str, str]:
        """Get the paths for a 线程's 数据 directories.

        Args:
            thread_id: The 线程 ID.

        Returns:
            Dictionary with workspace_path, uploads_path, and outputs_path.
        """
        return {
            "workspace_path": str(self._paths.sandbox_work_dir(thread_id)),
            "uploads_path": str(self._paths.sandbox_uploads_dir(thread_id)),
            "outputs_path": str(self._paths.sandbox_outputs_dir(thread_id)),
        }

    def _create_thread_directories(self, thread_id: str) -> dict[str, str]:
        """Create the 线程 数据 directories.

        Args:
            thread_id: The 线程 ID.

        Returns:
            Dictionary with the created 目录 paths.
        """
        self._paths.ensure_thread_dirs(thread_id)
        return self._get_thread_paths(thread_id)

    @override
    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        thread_id = runtime.context.get("thread_id")
        if thread_id is None:
            raise ValueError("Thread ID is required in the context")

        if self._lazy_init:
            #    Lazy initialization: only compute paths, don't 创建 directories


            paths = self._get_thread_paths(thread_id)
        else:
            #    Eager initialization: 创建 directories immediately


            paths = self._create_thread_directories(thread_id)
            print(f"Created thread data directories for thread {thread_id}")

        return {
            "thread_data": {
                **paths,
            }
        }

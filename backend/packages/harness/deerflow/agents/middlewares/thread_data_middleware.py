"""
线程数据中间件 - 为每个线程执行创建线程数据目录

===================
设计思路说明
===================

**核心职责**：
为每个线程执行创建隔离的目录结构：
1. **工作空间**：{base_dir}/threads/{thread_id}/user-data/workspace
2. **上传目录**：{base_dir}/threads/{thread_id}/user-data/uploads
3. **输出目录**：{base_dir}/threads/{thread_id}/user-data/outputs

**为什么需要线程隔离**：
1. **安全隔离**：不同线程的文件互不干扰
2. **资源清理**：便于按线程清理临时文件
3. **并发支持**：多个线程可以同时运行
4. **路径可预测**：标准化的目录结构

**生命周期管理**：
- lazy_init=True（默认）：只计算路径，按需创建目录
- lazy_init=False：在before_agent()中立即创建目录

**为什么默认使用lazy_init**：
- **性能优化**：避免不必要的目录创建
- **按需分配**：只在真正需要时才创建
- **启动速度**：减少代理启动时间
"""

import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ThreadDataState
from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


class ThreadDataMiddlewareState(AgentState):
    """与ThreadState模式兼容

    **为什么需要这个类**：
    - **类型提示**：提供thread_data字段的类型
    - **模式兼容**：确保与ThreadState兼容
    - **可选字段**：使用NotRequired表示可选
    """

    thread_data: NotRequired[ThreadDataState | None]


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """为每次线程执行创建线程数据目录

    **目录结构**：
    - {base_dir}/threads/{thread_id}/user-data/workspace
    - {base_dir}/threads/{thread_id}/user-data/uploads
    - {base_dir}/threads/{thread_id}/user-data/outputs

    **为什么需要这个中间件**：
    - **线程隔离**：每个线程有独立的文件空间
    - **安全隔离**：防止跨线程文件访问
    - **便于清理**：按线程清理临时文件
    - **标准化**：统一的目录结构便于工具使用

    **生命周期管理**：
    - lazy_init=True（默认）：只计算路径，按需创建目录
    - lazy_init=False：在before_agent()中立即创建目录

    **为什么默认lazy_init**：
    - **性能优化**：避免不必要的I/O操作
    - **按需创建**：只在需要时才创建目录
    - **减少开销**：不使用的线程不占用磁盘空间
    """

    state_schema = ThreadDataMiddlewareState

    def __init__(self, base_dir: str | None = None, lazy_init: bool = True):
        """Initialize the middleware.

        Args:
            base_dir: Base directory for thread data. Defaults to Paths resolution.
            lazy_init: If True, defer directory creation until needed.
                      If False, create directories eagerly in before_agent().
                      Default is True for optimal performance.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()
        self._lazy_init = lazy_init

    def _get_thread_paths(self, thread_id: str) -> dict[str, str]:
        """Get the paths for a thread's data directories.

        Args:
            thread_id: The thread ID.

        Returns:
            Dictionary with workspace_path, uploads_path, and outputs_path.
        """
        return {
            "workspace_path": str(self._paths.sandbox_work_dir(thread_id)),
            "uploads_path": str(self._paths.sandbox_uploads_dir(thread_id)),
            "outputs_path": str(self._paths.sandbox_outputs_dir(thread_id)),
        }

    def _create_thread_directories(self, thread_id: str) -> dict[str, str]:
        """Create the thread data directories.

        Args:
            thread_id: The thread ID.

        Returns:
            Dictionary with the created directory paths.
        """
        self._paths.ensure_thread_dirs(thread_id)
        return self._get_thread_paths(thread_id)

    @override
    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        context = runtime.context or {}
        thread_id = context.get("thread_id")
        if thread_id is None:
            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id")

        if thread_id is None:
            raise ValueError("Thread ID is required in runtime context or config.configurable")

        if self._lazy_init:
            # Lazy initialization: only compute paths, don't create directories
            paths = self._get_thread_paths(thread_id)
        else:
            # Eager initialization: create directories immediately
            paths = self._create_thread_directories(thread_id)
            logger.debug("Created thread data directories for thread %s", thread_id)

        return {
            "thread_data": {
                **paths,
            }
        }

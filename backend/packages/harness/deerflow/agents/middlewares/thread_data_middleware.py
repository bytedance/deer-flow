import logging
from typing import NotRequired, override

import json
import time

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ThreadDataState
from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


class ThreadDataMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    thread_data: NotRequired[ThreadDataState | None]


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """Create thread data directories for each thread execution.

    Creates the following directory structure:
    - {base_dir}/threads/{thread_id}/user-data/workspace
    - {base_dir}/threads/{thread_id}/user-data/uploads
    - {base_dir}/threads/{thread_id}/user-data/outputs

    Lifecycle Management:
    - With lazy_init=True (default): Only compute paths, directories created on-demand
    - With lazy_init=False: Eagerly create directories in before_agent()
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

        # Extract user_id from context for thread ownership tracking
        user_id = context.get("user_id")
        if user_id is None:
            try:
                config = get_config()
                user_id = config.get("configurable", {}).get("user_id")
            except RuntimeError:
                user_id = None

        if self._lazy_init:
            paths = self._get_thread_paths(thread_id)
        else:
            paths = self._create_thread_directories(thread_id)
            logger.debug("Created thread data directories for thread %s", thread_id)

        # Record thread ownership if user_id is available
        if user_id:
            self._record_thread_ownership(thread_id, user_id)
            # Ensure user directories exist
            self._paths.ensure_user_dirs(user_id)

        result = {
            "thread_data": {
                **paths,
            }
        }
        if user_id:
            result["user_id"] = user_id

        return result

    def _record_thread_ownership(self, thread_id: str, user_id: str) -> None:
        """Record thread-to-user ownership mapping."""
        ownership_file = self._paths.thread_ownership_file()
        ownership: dict = {}
        if ownership_file.exists():
            try:
                ownership = json.loads(ownership_file.read_text())
            except (json.JSONDecodeError, OSError):
                ownership = {}

        if thread_id not in ownership:
            ownership[thread_id] = {
                "user_id": user_id,
                "created_at": time.time(),
            }
            ownership_file.parent.mkdir(parents=True, exist_ok=True)
            ownership_file.write_text(json.dumps(ownership, indent=2))

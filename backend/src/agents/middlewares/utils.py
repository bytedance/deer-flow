"""Shared utilities for agent middlewares."""

from langgraph.config import get_config
from langgraph.runtime import Runtime


def get_thread_id_from_runtime(runtime: Runtime) -> str | None:
    """Extract thread_id from runtime context or LangGraph config.

    Compatible with LangGraph 1.0+ and older versions.
    LangGraph 1.0+ stores thread_id in config["configurable"]["thread_id"].

    Args:
        runtime: The LangGraph runtime instance.

    Returns:
        The thread_id if found, otherwise None.
    """
    ctx = runtime.context
    if ctx is not None and hasattr(ctx, "get"):
        thread_id = ctx.get("thread_id")
        if thread_id:
            return thread_id
        configurable = ctx.get("configurable")
        if configurable and isinstance(configurable, dict):
            thread_id = configurable.get("thread_id")
            if thread_id:
                return thread_id

    try:
        cfg = get_config()
        return cfg.get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None

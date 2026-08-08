"""Shared host-side loading and formatting for injected memory context."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from deerflow.agents.memory.manager import MemoryManagerError

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.memory_config import MemoryConfig

logger = logging.getLogger(__name__)


def _resolve_config(app_config: AppConfig | None) -> MemoryConfig:
    if app_config is not None:
        return app_config.memory
    from deerflow.config.memory_config import get_memory_config

    return get_memory_config()


def _format_memory_context(memory_content: str) -> str:
    stripped = memory_content.strip()
    if not stripped:
        return ""
    if stripped.startswith("<memory>") and stripped.endswith("</memory>"):
        return f"{stripped}\n"
    return f"""<memory>
{memory_content}
</memory>
"""


def _should_reraise(exc: Exception, config: MemoryConfig | None) -> bool:
    if config is None:
        return False
    failure_policy = getattr(config, "backend_config", {}).get("failure_policy", {})
    return isinstance(exc, MemoryManagerError) and isinstance(failure_policy, dict) and failure_policy.get("read") == "fail_closed"


def load_memory_context(
    agent_name: str | None = None,
    *,
    app_config: AppConfig | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
    query: str | None = None,
) -> str:
    """Load and wrap memory context through the synchronous manager contract."""
    config = None
    try:
        config = _resolve_config(app_config)
        if not config.enabled or not config.injection_enabled:
            return ""

        from deerflow.agents.memory import get_memory_manager
        from deerflow.runtime.user_context import resolve_runtime_user_id

        resolved_user_id = user_id or resolve_runtime_user_id(None)
        manager = get_memory_manager()
        supports_query_aware_context = getattr(manager, "supports_query_aware_context", False)
        if query is not None and not supports_query_aware_context:
            return ""
        kwargs = {
            "agent_name": agent_name,
        }
        if query is not None:
            kwargs["thread_id"] = thread_id
            kwargs["query"] = query
        memory_content = manager.get_context(
            resolved_user_id,
            **kwargs,
        )
        return _format_memory_context(memory_content)
    except Exception as exc:
        logger.exception("Failed to load memory context")
        if _should_reraise(exc, config):
            raise
        return ""


async def aload_memory_context(
    agent_name: str | None = None,
    *,
    app_config: AppConfig | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
    query: str | None = None,
) -> str:
    """Load and wrap memory context through the asynchronous manager contract."""
    config = None
    try:
        config = _resolve_config(app_config)
        if not config.enabled or not config.injection_enabled:
            return ""

        from deerflow.agents.memory import get_memory_manager
        from deerflow.runtime.user_context import resolve_runtime_user_id

        resolved_user_id = user_id or resolve_runtime_user_id(None)
        manager = await asyncio.to_thread(get_memory_manager)
        supports_query_aware_context = getattr(manager, "supports_query_aware_context", False)
        if query is not None and not supports_query_aware_context:
            return ""
        kwargs = {
            "agent_name": agent_name,
        }
        if query is not None:
            kwargs["thread_id"] = thread_id
            kwargs["query"] = query
        memory_content = await manager.aget_context(
            resolved_user_id,
            **kwargs,
        )
        return _format_memory_context(memory_content)
    except Exception as exc:
        logger.exception("Failed to load memory context")
        if _should_reraise(exc, config):
            raise
        return ""

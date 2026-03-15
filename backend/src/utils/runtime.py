"""Utilities for accessing LangGraph runtime context."""

from __future__ import annotations

from typing import Any

from langgraph.config import get_config
from langgraph.runtime import Runtime


def get_thread_id(runtime: Runtime | None = None) -> str | None:
    """Get the thread_id from the LangGraph runtime context.

    Tries runtime.context first (if available), then falls back
    to config.configurable.thread_id from the LangGraph config.
    """
    # Try runtime.context first
    if runtime is not None and runtime.context is not None:
        ctx = runtime.context
        if isinstance(ctx, dict):
            tid = ctx.get("thread_id")
        else:
            tid = getattr(ctx, "thread_id", None)
        if tid is not None:
            return str(tid)

    # Fall back to config.configurable
    try:
        config = get_config()
        return config.get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


def get_context_value(runtime: Runtime | None, key: str, default: Any = None) -> Any:
    """Get a value from the LangGraph runtime context or config configurable.

    Tries runtime.context first (if available), then falls back
    to config.configurable from the LangGraph config.
    """
    # Try runtime.context first
    if runtime is not None and runtime.context is not None:
        ctx = runtime.context
        if isinstance(ctx, dict):
            val = ctx.get(key)
        else:
            val = getattr(ctx, key, None)
        if val is not None:
            return val

    # Fall back to config.configurable
    try:
        config = get_config()
        return config.get("configurable", {}).get(key, default)
    except RuntimeError:
        return default


def get_subscription_tier_context(runtime: Runtime | None) -> tuple[Any, str | None]:
    """Get the subscription tier value from runtime context.

    Only reads the canonical ``context.subscription_tier`` key.
    Transport-level header aliases (x-subscription-tier, x-subscription) are
    intentionally not accepted here — callers must normalise to the canonical
    field before forwarding into the runtime context.

    Returns:
        (value, source_key) — source_key is ``"subscription_tier"`` when found, else ``None``.
    """
    key = "subscription_tier"

    if runtime is not None and runtime.context is not None:
        ctx = runtime.context
        if isinstance(ctx, dict):
            val = ctx.get(key)
        else:
            val = getattr(ctx, key, None)
        if val is not None:
            return val, key

    try:
        config = get_config()
        val = config.get("configurable", {}).get(key)
        if val is not None:
            return val, key
    except RuntimeError:
        pass

    return None, None

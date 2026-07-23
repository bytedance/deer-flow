"""Compute the current message-context usage for a thread."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException, Request

from app.gateway.deps import get_config
from app.gateway.services import build_thread_checkpoint_state_accessor

logger = logging.getLogger(__name__)


def _count_messages_approximately(messages: list[Any]) -> int:
    """Count checkpoint messages with LangChain's network-free heuristic."""
    if not messages:
        return 0
    from langchain_core.messages.utils import count_tokens_approximately

    return int(count_tokens_approximately(messages))


async def _load_checkpoint_messages(accessor: Any, config: dict[str, Any]) -> list[Any]:
    """Read materialized messages so full and delta checkpoints behave alike."""
    snapshot = await accessor.aget(config)
    values = getattr(snapshot, "values", None) or {}
    if not isinstance(values, dict):
        return []
    return list(values.get("messages") or [])


async def _resolve_thread_model_name(run_store: Any, thread_id: str, app_config: Any) -> str | None:
    """Prefer the latest run's model, then fall back to the first configured model."""
    try:
        runs = await run_store.list_by_thread(thread_id, limit=1)
    except Exception:
        runs = []
    if runs:
        latest = runs[0]
        name = latest.get("model_name") if isinstance(latest, dict) else getattr(latest, "model_name", None)
        if isinstance(name, str) and name:
            return name
    models = getattr(app_config, "models", None) or []
    return models[0].name if models else None


def build_context_usage_payload(*, token_count: int, max_context_tokens: int | None) -> dict[str, Any]:
    """Build the stable API payload for a message count and model capacity."""
    percentage: float | None = None
    if max_context_tokens and max_context_tokens > 0:
        percentage = round(token_count / max_context_tokens * 100, 1)
    return {
        "token_count": token_count,
        "max_context_tokens": max_context_tokens,
        "percentage": percentage,
    }


async def build_context_usage(request: Request, thread_id: str, run_store: Any) -> dict[str, Any] | None:
    """Return approximate usage for the latest materialized thread checkpoint."""
    try:
        app_config = get_config()
    except HTTPException:
        return None

    try:
        accessor, checkpoint_config = await build_thread_checkpoint_state_accessor(request, thread_id=thread_id)
        messages = await _load_checkpoint_messages(accessor, checkpoint_config)
    except Exception:
        logger.warning("Failed to load checkpoint for context usage on thread %s", thread_id, exc_info=True)
        return None

    try:
        token_count = await asyncio.to_thread(_count_messages_approximately, messages)
    except Exception:
        logger.warning("Failed to count context messages for thread %s", thread_id, exc_info=True)
        return None

    model_name = await _resolve_thread_model_name(run_store, thread_id, app_config)
    model_config = app_config.get_model_config(model_name) if model_name else None
    configured_window = getattr(model_config, "context_window", None) if model_config is not None else None
    max_context_tokens = int(configured_window) if configured_window else None
    return build_context_usage_payload(token_count=token_count, max_context_tokens=max_context_tokens)

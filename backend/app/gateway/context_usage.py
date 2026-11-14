"""Compute the current message-context usage for a thread."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage

from app.gateway.deps import get_config
from app.gateway.services import build_thread_checkpoint_state_accessor
from deerflow.agents.middlewares.context_usage_middleware import CONTEXT_USAGE_KEY, ContextUsageSnapshot

logger = logging.getLogger(__name__)


def _count_messages_approximately(messages: list[Any]) -> int:
    """Count checkpoint messages with LangChain's network-free heuristic."""
    if not messages:
        return 0
    from langchain_core.messages.utils import count_tokens_approximately

    return int(count_tokens_approximately(messages))


def _read_context_usage_breakdown(messages: list[Any]) -> dict[str, Any] | None:
    """Return the newest validated composition snapshot persisted in the thread.

    ``ContextUsageMiddleware`` stamps each model response with the composition
    of the request that produced it. A snapshot is current only when the
    response is still the end of the context, or when the only messages after
    it are later user turns (a new request has not reached the model yet). A
    tool result or another assistant message after it means the context grew
    past what the snapshot counted, so the stale value is skipped rather than
    rendered next to a smaller message count.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, AIMessage):
            continue
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if not isinstance(additional_kwargs, dict):
            continue
        snapshot = ContextUsageSnapshot.from_dict(additional_kwargs.get(CONTEXT_USAGE_KEY))
        if snapshot is None:
            continue
        if any(not isinstance(later, HumanMessage) for later in messages[index + 1 :]):
            continue
        return snapshot.to_payload()
    return None


async def _load_checkpoint_messages(accessor: Any, config: dict[str, Any]) -> list[Any]:
    """Read materialized messages so full and delta checkpoints behave alike."""
    snapshot = await accessor.aget(config)
    values = getattr(snapshot, "values", None) or {}
    if not isinstance(values, dict):
        return []
    return list(values.get("messages") or [])


async def _resolve_thread_model_name(run_store: Any, thread_id: str, app_config: Any, user_id: str | None = None) -> str | None:
    """Prefer the latest run's model, then fall back to the first configured model.

    ``user_id`` scopes the latest-run lookup (``None`` = unfiltered, matching
    the thread-scoped aggregate semantics).
    """
    try:
        runs = await run_store.list_by_thread(thread_id, limit=1, user_id=user_id)
    except Exception:
        runs = []
    if runs:
        latest = runs[0]
        name = latest.get("model_name") if isinstance(latest, dict) else getattr(latest, "model_name", None)
        if isinstance(name, str) and name:
            return name
    models = getattr(app_config, "models", None) or []
    return models[0].name if models else None


def build_context_usage_payload(*, token_count: int, max_context_tokens: int | None, breakdown: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the stable API payload for a message count and model capacity.

    ``token_count`` keeps its messages-only meaning for the header indicator.
    ``breakdown`` is additive: it carries the composition captured at the last
    model call, and is ``None`` for threads that never ran with tracking on.
    """
    percentage: float | None = None
    if max_context_tokens and max_context_tokens > 0:
        percentage = round(token_count / max_context_tokens * 100, 1)
    return {
        "token_count": token_count,
        "max_context_tokens": max_context_tokens,
        "percentage": percentage,
        "breakdown": breakdown,
    }


async def build_context_usage(request: Request, thread_id: str, run_store: Any, user_id: str | None = None) -> dict[str, Any] | None:
    """Return approximate usage for the latest materialized thread checkpoint."""
    try:
        # ``get_config`` revalidates ``config.yaml`` and
        # ``extensions_config.json`` on every call (stat + full-file hash), so
        # reading it here would put that IO on the loop every thread view pays.
        app_config = await asyncio.to_thread(get_config)
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

    model_name = await _resolve_thread_model_name(run_store, thread_id, app_config, user_id=user_id)
    model_config = app_config.get_model_config(model_name) if model_name else None
    configured_window = getattr(model_config, "context_window", None) if model_config is not None else None
    max_context_tokens = int(configured_window) if configured_window else None
    try:
        breakdown = _read_context_usage_breakdown(messages)
    except Exception:
        logger.warning("Failed to read context usage breakdown for thread %s", thread_id, exc_info=True)
        breakdown = None
    return build_context_usage_payload(token_count=token_count, max_context_tokens=max_context_tokens, breakdown=breakdown)

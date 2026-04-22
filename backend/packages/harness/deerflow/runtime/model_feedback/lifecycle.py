"""Hooks from the run worker into model feedback counters."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from deerflow.runtime.model_feedback.names import extract_model_name_from_run_config,normalize_feedback_model_name
from deerflow.runtime.model_feedback.registry import get_model_feedback_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelFeedbackEventContext:
    thread_id: str
    run_id: str
    user_id: str | None
    event_store: Any | None


_current_event_context: ContextVar[ModelFeedbackEventContext | None] = ContextVar(
    "deerflow_model_feedback_event_context",
    default=None,
)


def set_model_feedback_event_context(
    *,
    thread_id: str,
    run_id: str,
    user_id: str | None,
    event_store: Any | None,
) -> Token[ModelFeedbackEventContext | None]:
    return _current_event_context.set(
        ModelFeedbackEventContext(
            thread_id=thread_id,
            run_id=run_id,
            user_id=user_id,
            event_store=event_store,
        )
    )


def reset_model_feedback_event_context(token: Token[ModelFeedbackEventContext | None]) -> None:
    _current_event_context.reset(token)


async def _emit_model_feedback_event(model_name: str, *, success: bool) -> None:
    ctx = _current_event_context.get()
    if ctx is None or ctx.event_store is None:
        return
    event_type = "model.call.succeeded" if success else "model.call.failed"
    metadata = {
        "model_name": model_name,
        "success": success,
    }
    if ctx.user_id is not None:
        metadata["user_id"] = ctx.user_id
    try:
        await ctx.event_store.put(
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            event_type=event_type,
            category="trace",
            content="",
            metadata=metadata,
        )
    except Exception:
        logger.warning("model_feedback: failed to emit run event for model=%s success=%s", model_name, success, exc_info=True)


async def record_model_feedback(model_name: str, *, success: bool) -> None:
    """Record one completed model call for a concrete configured model name."""
    store = get_model_feedback_store()
    try:
        name = normalize_feedback_model_name(model_name)
    except ValueError:
        return
    try:
        if store is not None:
            if success:
                await store.increment(name, call_count=1, success_count=1)
            else:
                await store.increment(name, call_count=1, failure_count=1)
        await _emit_model_feedback_event(name, success=success)
        logger.info("model_feedback: recorded model=%s success=%s", name, success)
    except Exception:
        logger.warning("model_feedback: failed to record model outcome for %r", name, exc_info=True)


def record_model_feedback_sync(model_name: str, *, success: bool) -> None:
    """Sync helper for model clients that expose only sync execution methods."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(record_model_feedback(model_name, success=success))
        return
    loop.create_task(record_model_feedback(model_name, success=success))


async def record_run_model_feedback(run_config: dict[str, Any], *, success: bool) -> None:
    """Record one completed agent run against its resolved model name."""
    name = extract_model_name_from_run_config(run_config)
    if not name:
        return
    await record_model_feedback(name, success=success)

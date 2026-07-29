"""Manual thread-context compaction helpers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace

from langgraph.types import Overwrite

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummaryGenerationError, create_summarization_middleware
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

logger = logging.getLogger(__name__)


class ContextCompactionDisabled(RuntimeError):
    """Raised when manual compaction is requested while summarization is disabled."""


class ContextCompactionFailed(RuntimeError):
    """Raised when a compressible thread cannot be summarized."""


@dataclass(frozen=True)
class ThreadCompactionResult:
    """Result returned after a manual context-compaction attempt."""

    thread_id: str
    compacted: bool
    reason: str | None = None
    removed_message_count: int = 0
    preserved_message_count: int = 0
    summary_updated: bool = False
    checkpoint_id: str | None = None
    total_tokens: int = 0


def _create_compaction_middleware(
    *,
    app_config: AppConfig,
    keep: tuple[str, int | float] | None,
    run_model_name: str | None = None,
) -> DeerFlowSummarizationMiddleware:
    middleware = create_summarization_middleware(app_config=app_config, keep=keep, run_model_name=run_model_name)
    if middleware is None:
        raise ContextCompactionDisabled("Context compaction is disabled.")
    return middleware


def _safe_load_agent_config(agent_name: str, user_id: str | None):
    """Load a custom agent's config, returning ``None`` on any failure.

    A missing / unparseable agent config must not fail compaction; the run model is a
    best-effort optimization and the default is a safe fallback. The caller runs this
    off the event loop via ``asyncio.to_thread``, so the strict blocking-IO detector
    does not flag the filesystem read and the broad ``except`` here cannot mask a
    ``BlockingError`` raised on the loop.
    """
    from deerflow.config.agents_config import load_agent_config

    try:
        return load_agent_config(agent_name, user_id=user_id)
    except Exception:
        logger.warning("Could not load agent config for %r; using the default model for summarization", agent_name, exc_info=True)
        return None


async def _aresolve_thread_model_name(
    model_name: str | None,
    agent_name: str | None,
    user_id: str | None,
    app_config: AppConfig,
) -> str | None:
    """Resolve the model a thread should summarize with, mirroring lead resolution.

    Precedence matches ``lead_agent._resolve_model_name``: an explicit request model
    override (validated against configured models) wins, else the thread's custom-agent
    configured model, else ``config.models[0]``. Manual ``/compact`` does not execute
    the agent, so there is no live runtime carrying the selected model — the caller
    (route / client) supplies it as ``model_name`` the same way a normal run submits
    ``context.model_name``. The custom-agent config read happens only when no request
    model was supplied, runs off the event loop, and passes the owning ``user_id`` so
    the per-user agent directory resolves.
    """
    default = app_config.models[0].name if getattr(app_config, "models", None) else None
    candidate = model_name
    if not candidate and agent_name:
        agent_config = await asyncio.to_thread(_safe_load_agent_config, agent_name, user_id)
        if agent_config and agent_config.model:
            candidate = agent_config.model
    if candidate and app_config.get_model_config(candidate):
        return candidate
    return default


async def compact_thread_context(
    accessor: CheckpointStateAccessor,
    thread_id: str,
    *,
    keep: tuple[str, int | float] | None = None,
    force: bool = True,
    user_id: str | None = None,
    agent_name: str | None = None,
    model_name: str | None = None,
    app_config: AppConfig | None = None,
) -> ThreadCompactionResult:
    """Summarize old messages in a thread and write a compacted checkpoint."""
    resolved_app_config = app_config or get_app_config()
    run_model_name = await _aresolve_thread_model_name(model_name, agent_name, user_id, resolved_app_config)
    middleware = _create_compaction_middleware(app_config=resolved_app_config, keep=keep, run_model_name=run_model_name)

    read_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    snapshot = await accessor.aget(read_config)
    snapshot_config = snapshot.config or {}
    checkpoint_id = snapshot_config.get("configurable", {}).get("checkpoint_id")
    if not checkpoint_id:
        raise LookupError(f"Thread {thread_id} checkpoint not found")

    channel_values = snapshot.values or {}
    messages = channel_values.get("messages")
    if not isinstance(messages, list) or not messages:
        return ThreadCompactionResult(thread_id=thread_id, compacted=False, reason="not_enough_messages")

    state = {
        "messages": list(messages),
        "summary_text": channel_values.get("summary_text"),
    }

    runtime_context = {"thread_id": thread_id, "user_id": user_id}
    if agent_name:
        runtime_context["agent_name"] = agent_name
    runtime = SimpleNamespace(context=runtime_context)
    try:
        # ``raise_on_failure`` is independent of ``force``: a manual caller always wants
        # a generation failure surfaced (even a force=False call that met the threshold),
        # so it must not collapse into the force=False "nothing to compact" branch below.
        result = await middleware.acompact_state(state, runtime, force=force, raise_on_failure=True)  # type: ignore[arg-type]
    except SummaryGenerationError as exc:
        # A compressible thread whose summary LLM failed (after the run-model fallback)
        # is a real failure, distinct from "nothing to compact". Route it to the
        # already-consumed ContextCompactionFailed path (HTTP 500 -> frontend error
        # toast) instead of a compacted=False result that reads as "does not need
        # compaction".
        raise ContextCompactionFailed("summary generation failed") from exc
    if result is None:
        return ThreadCompactionResult(thread_id=thread_id, compacted=False, reason="not_enough_messages")

    updated_config = await accessor.aupdate(
        snapshot.config,
        {
            "messages": Overwrite(list(result.preserved_messages)),
            "summary_text": result.summary_text,
        },
        as_node="manual_compaction",
    )
    new_checkpoint_id = updated_config.get("configurable", {}).get("checkpoint_id")

    return ThreadCompactionResult(
        thread_id=thread_id,
        compacted=True,
        removed_message_count=len(result.messages_to_summarize),
        preserved_message_count=len(result.preserved_messages),
        summary_updated=True,
        checkpoint_id=new_checkpoint_id,
        total_tokens=result.total_tokens,
    )

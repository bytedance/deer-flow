"""Manual thread-context compaction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from langgraph.types import Overwrite

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, create_summarization_middleware
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor


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
) -> DeerFlowSummarizationMiddleware:
    middleware = create_summarization_middleware(app_config=app_config, keep=keep)
    if middleware is None:
        raise ContextCompactionDisabled("Context compaction is disabled.")
    return middleware


async def compact_thread_context(
    accessor: CheckpointStateAccessor,
    thread_id: str,
    *,
    keep: tuple[str, int | float] | None = None,
    force: bool = True,
    user_id: str | None = None,
    agent_name: str | None = None,
    app_config: AppConfig | None = None,
) -> ThreadCompactionResult:
    """Summarize old messages in a thread and write a compacted checkpoint."""
    resolved_app_config = app_config or get_app_config()
    middleware = _create_compaction_middleware(app_config=resolved_app_config, keep=keep)

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
    result = await middleware.acompact_state(state, runtime, force=force)  # type: ignore[arg-type]
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

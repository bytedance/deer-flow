"""Manual thread-context compaction helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from langgraph.checkpoint.base import uuid6

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, create_summarization_middleware
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.goal import _call_checkpointer_method, _next_channel_version
from deerflow.utils.time import now_iso


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


def _checkpoint_namespace(checkpoint_tuple: Any) -> str:
    config = getattr(checkpoint_tuple, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    checkpoint_ns = configurable.get("checkpoint_ns", "") if isinstance(configurable, dict) else ""
    return checkpoint_ns if isinstance(checkpoint_ns, str) else ""


async def compact_thread_context(
    checkpointer: Any,
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
    checkpoint_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", read_config)
    if checkpoint_tuple is None:
        raise LookupError(f"Thread {thread_id} checkpoint not found")

    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}) or {})
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

    channel_values["messages"] = list(result.preserved_messages)
    channel_values["summary_text"] = result.summary_text
    checkpoint["channel_values"] = channel_values

    channel_versions = dict(checkpoint.get("channel_versions", {}) or {})
    new_versions: dict[str, Any] = {}
    for channel in ("messages", "summary_text"):
        next_version = _next_channel_version(checkpointer, channel_versions.get(channel))
        channel_versions[channel] = next_version
        new_versions[channel] = next_version
    checkpoint["channel_versions"] = channel_versions
    checkpoint["id"] = str(uuid6())
    checkpoint["ts"] = now_iso()

    metadata["source"] = "update"
    metadata["updated_at"] = now_iso()
    prev_step = metadata.get("step")
    metadata["step"] = (prev_step + 1) if isinstance(prev_step, int) else 1
    metadata["writes"] = {
        "manual_compaction": {
            "messages": {
                "removed": len(result.messages_to_summarize),
                "preserved": len(result.preserved_messages),
            },
            "summary_text": {
                "sha256": hashlib.sha256(result.summary_text.encode("utf-8")).hexdigest(),
                "chars": len(result.summary_text),
            },
        }
    }

    write_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": _checkpoint_namespace(checkpoint_tuple)}}
    new_config = await _call_checkpointer_method(checkpointer, "aput", "put", write_config, checkpoint, metadata, new_versions)
    new_checkpoint_id = None
    if isinstance(new_config, dict):
        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id")

    return ThreadCompactionResult(
        thread_id=thread_id,
        compacted=True,
        removed_message_count=len(result.messages_to_summarize),
        preserved_message_count=len(result.preserved_messages),
        summary_updated=True,
        checkpoint_id=new_checkpoint_id,
        total_tokens=result.total_tokens,
    )

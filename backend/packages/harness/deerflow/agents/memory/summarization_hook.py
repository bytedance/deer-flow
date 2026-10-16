"""Hooks fired before summarization removes messages from state."""

from __future__ import annotations

import asyncio
from typing import Any

from deerflow.agents.memory import get_memory_manager
from deerflow.agents.middlewares.memory_middleware import redact_queued_messages
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import get_memory_config
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.runtime.user_context import resolve_runtime_user_id


def _flush_gate(event: SummarizationEvent) -> tuple[Any, str | None] | None:
    if not get_memory_config().enabled or not event.thread_id:
        return None
    return get_memory_manager(), resolve_runtime_user_id(event.runtime)


def memory_flush_hook(event: SummarizationEvent, pii_redaction_config: PiiRedactionConfig | None = None) -> None:
    """Flush messages about to be summarized into the memory queue.

    Thin, backend-agnostic entry: only the ``enabled`` + ``thread_id`` gate
    and ``user_id`` resolution live here. The backend (via
    ``manager.add_nowait``) does the filtering, human/AI validation, and
    correction/reinforcement detection. The queued payload is redacted at
    this boundary (#3190 vector 5): compaction removes these messages from
    state right after, so the later after-agent redaction cannot repair a
    raw batch queued here.
    """
    gated = _flush_gate(event)
    if gated is None:
        return
    manager, user_id = gated
    manager.add_nowait(
        event.thread_id,
        redact_queued_messages(list(event.messages_to_summarize), pii_redaction_config),
        agent_name=event.agent_name,
        user_id=user_id,
    )


async def amemory_flush_hook(event: SummarizationEvent, pii_redaction_config: PiiRedactionConfig | None = None) -> None:
    """Async counterpart of :func:`memory_flush_hook` for the event-loop path.

    Offload the gate (including a cold ``get_memory_manager()`` backend scan)
    the same way ``MemoryMiddleware.aafter_agent`` does, then enqueue through
    the manager's async boundary. The queued payload is redacted with the same
    ``pii_redaction_config`` as the sync hook.
    """
    gated = await asyncio.to_thread(_flush_gate, event)
    if gated is None:
        return
    manager, user_id = gated
    await manager.aadd_nowait(
        event.thread_id,
        redact_queued_messages(list(event.messages_to_summarize), pii_redaction_config),
        agent_name=event.agent_name,
        user_id=user_id,
    )


memory_flush_hook.as_async = amemory_flush_hook  # type: ignore[attr-defined]

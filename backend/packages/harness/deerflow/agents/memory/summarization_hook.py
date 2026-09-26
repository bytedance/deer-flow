"""Hooks fired before summarization removes messages from state."""

from __future__ import annotations

from deerflow.agents.memory import get_memory_manager
from deerflow.agents.middlewares.memory_middleware import redact_queued_messages
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import get_memory_config
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.runtime.user_context import resolve_runtime_user_id


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
    if not get_memory_config().enabled or not event.thread_id:
        return

    user_id = resolve_runtime_user_id(event.runtime)
    get_memory_manager().add_nowait(
        event.thread_id,
        redact_queued_messages(list(event.messages_to_summarize), pii_redaction_config),
        agent_name=event.agent_name,
        user_id=user_id,
    )

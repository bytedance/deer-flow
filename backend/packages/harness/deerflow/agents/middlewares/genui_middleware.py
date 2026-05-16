"""GenUI interaction middleware — manages interactive UI block callbacks."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InteractionRecord:
    """Represents a registered interactive UI block callback."""

    callback_id: str
    thread_id: str
    checkpoint_id: str
    timeout: float
    created_at: float = field(default_factory=time.time)
    submitted: bool = False
    payload: dict | None = None

    @property
    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.timeout

    def with_submission(self, payload: dict) -> InteractionRecord:
        return InteractionRecord(
            callback_id=self.callback_id,
            thread_id=self.thread_id,
            checkpoint_id=self.checkpoint_id,
            timeout=self.timeout,
            created_at=self.created_at,
            submitted=True,
            payload=payload,
        )


class InteractionStore:
    """Thread-safe store for managing interactive UI block callbacks.

    Tracks registered callbacks, enforces idempotency (submit-once),
    and cleans up expired records.
    """

    def __init__(self) -> None:
        self._records: dict[str, InteractionRecord] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(thread_id: str, callback_id: str) -> str:
        return f"{thread_id}\x1f{callback_id}"

    def register(
        self,
        callback_id: str,
        thread_id: str,
        checkpoint_id: str,
        timeout: float = 300.0,
    ) -> InteractionRecord:
        record = InteractionRecord(
            callback_id=callback_id,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            timeout=timeout,
        )
        with self._lock:
            self._records[self._make_key(thread_id, callback_id)] = record
        logger.debug("Registered interaction callback %s for thread %s", callback_id, thread_id)
        return record

    def get(self, thread_id: str, callback_id: str) -> InteractionRecord | None:
        with self._lock:
            return self._records.get(self._make_key(thread_id, callback_id))

    def submit(
        self,
        thread_id: str,
        callback_id: str,
        payload: dict,
    ) -> InteractionRecord | None:
        """Mark a callback as submitted. Returns the updated record or None if not found."""
        with self._lock:
            key = self._make_key(thread_id, callback_id)
            record = self._records.get(key)
            if record is None:
                return None
            updated = record.with_submission(payload)
            self._records[key] = updated
            return updated

    def cleanup_expired(self) -> int:
        """Remove expired records. Returns the number of records removed."""
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, v in self._records.items() if now > v.created_at + v.timeout
            ]
            for key in expired_keys:
                del self._records[key]
                removed += 1
        if removed:
            logger.debug("Cleaned up %d expired interaction records", removed)
        return removed

    def remove(self, thread_id: str, callback_id: str) -> bool:
        with self._lock:
            return self._records.pop(self._make_key(thread_id, callback_id), None) is not None


# Global singleton instance
_interaction_store: InteractionStore | None = None
_store_lock = threading.Lock()


def get_interaction_store() -> InteractionStore:
    """Get or create the global InteractionStore singleton."""
    global _interaction_store
    if _interaction_store is None:
        with _store_lock:
            if _interaction_store is None:
                _interaction_store = InteractionStore()
    return _interaction_store


def process_interaction(
    thread_id: str,
    callback_id: str,
    payload: dict,
) -> HumanMessage | None:
    """Process an interaction submission.

    Returns a HumanMessage to inject into the graph if the submission is valid,
    or None if the callback was already submitted (idempotent).

    Raises:
        ValueError: If callback_id is not found.
        TimeoutError: If the callback has expired.
    """
    store = get_interaction_store()
    record = store.get(thread_id, callback_id)

    if record is None:
        raise ValueError(f"Unknown callback_id: {callback_id} for thread {thread_id}")

    if record.is_expired:
        store.remove(thread_id, callback_id)
        raise TimeoutError(f"Callback {callback_id} has expired")

    if record.submitted:
        return None

    updated = store.submit(thread_id, callback_id, payload)
    if updated is None:
        return None

    import json

    from deerflow.agents.genui_persistence import clear_blocks_by_callback_id

    clear_blocks_by_callback_id(thread_id, callback_id)

    content = json.dumps(
        {
            "type": "ui_interaction",
            "callback_id": callback_id,
            "payload": payload,
        },
        ensure_ascii=False,
    )

    return HumanMessage(content=content, id=f"ui-interaction:{callback_id}")


# ---------------------------------------------------------------------------
# GenUI Interrupt Middleware
# ---------------------------------------------------------------------------


class GenUIInterruptMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class GenUIInterruptMiddleware(AgentMiddleware[GenUIInterruptMiddlewareState]):
    """Intercepts render_ui calls with interactive=True and interrupts execution.

    When the model calls render_ui with interactive=True (e.g., a form or confirm
    dialog), this middleware lets the tool execute normally to create/stream/persist
    the UI block, then returns Command(goto=END) to halt the agent until the user
    submits the interaction.

    Without this, the LLM may continue executing after creating an interactive form
    because the "stop after render_ui" instruction in the system prompt is only a
    soft constraint — there is no programmatic guarantee the model will obey it.
    """

    state_schema = GenUIInterruptMiddlewareState

    def _should_interrupt(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") != "render_ui":
            return False
        return bool(request.tool_call.get("args", {}).get("interactive"))

    def _wrap_result(self, result: ToolMessage | Command) -> Command:
        if isinstance(result, Command):
            return result
        return Command(update={"messages": [result]}, goto=END)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not self._should_interrupt(request):
            return handler(request)

        logger.info(
            "GenUI interrupt: render_ui interactive=True, callback=%s",
            request.tool_call.get("args", {}).get("callback_id", ""),
        )
        return self._wrap_result(handler(request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not self._should_interrupt(request):
            return await handler(request)

        logger.info(
            "GenUI interrupt: render_ui interactive=True, callback=%s",
            request.tool_call.get("args", {}).get("callback_id", ""),
        )
        return self._wrap_result(await handler(request))

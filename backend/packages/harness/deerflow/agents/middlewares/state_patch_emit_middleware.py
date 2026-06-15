"""Middleware that emits ``state_patch`` custom events for UI-relevant state changes.

This middleware observes the state after all state-modifying middleware have run
and emits ``state_patch`` events via ``get_stream_writer()`` for fields the frontend
needs to update incrementally (``title``, ``todos``, ``artifacts``). It returns an
empty dict — it never modifies state.
"""

import logging
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

_TRACKED_FIELDS: tuple[str, ...] = ("title", "todos", "artifacts")


class StatePatchEmitMiddlewareState(AgentState):
    """Compatible with the ``ThreadState`` schema."""

    title: NotRequired[str | None]
    todos: NotRequired[list[dict[str, Any]] | None]
    artifacts: NotRequired[list[str] | None]


class StatePatchEmitMiddleware(AgentMiddleware[StatePatchEmitMiddlewareState]):
    """Emit ``state_patch`` custom events when tracked state fields change.

    The middleware uses instance-level ``_last_emitted`` cache to compare absolute
    field values across invocations. Because it is placed at the end of the middleware
    chain, it sees the post-merge state reflecting all upstream modifications.
    """

    state_schema = StatePatchEmitMiddlewareState

    def __init__(self) -> None:
        super().__init__()
        self._last_emitted: dict[str, Any] = {}

    def _emit_patches(self, state: StatePatchEmitMiddlewareState) -> None:
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
        except Exception:
            return

        for field in _TRACKED_FIELDS:
            current = state.get(field)
            last = self._last_emitted.get(field)
            if current != last:
                try:
                    writer({"type": "state_patch", "patch": {field: current}})
                except Exception:
                    logger.debug("Failed to emit state_patch for %s", field, exc_info=True)
                    continue
                self._last_emitted[field] = current

    @override
    def after_model(self, state: StatePatchEmitMiddlewareState, runtime: Runtime) -> dict | None:
        self._emit_patches(state)
        return None

    @override
    async def aafter_model(self, state: StatePatchEmitMiddlewareState, runtime: Runtime) -> dict | None:
        self._emit_patches(state)
        return None

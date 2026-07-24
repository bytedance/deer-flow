"""Compatibility helpers for DeerFlow custom stream events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import adispatch_custom_event, dispatch_custom_event
from langgraph.errors import GraphBubbleUp

logger = logging.getLogger(__name__)

StreamWriter = Callable[[Any], None]


def _event_name(payload: dict[str, Any]) -> str | None:
    event_type = payload.get("type")
    if isinstance(event_type, str) and event_type:
        return event_type
    logger.debug("Custom stream payload has no non-empty string 'type'; skipping callback dispatch")
    return None


def emit_custom_event(payload: dict[str, Any], *, writer: StreamWriter) -> None:
    """Emit one event to LangGraph's custom stream and callback APIs.

    The writer remains the primary compatibility path. Callback dispatch is
    best-effort so an optional ``astream_events`` consumer cannot break an
    existing DeerFlow run.
    """

    writer(payload)
    event_name = _event_name(payload)
    if event_name is None:
        return
    try:
        dispatch_custom_event(event_name, payload)
    except GraphBubbleUp:
        raise
    except Exception:
        logger.debug("Failed to dispatch custom callback event %s", event_name, exc_info=True)


async def aemit_custom_event(payload: dict[str, Any], *, writer: StreamWriter) -> None:
    """Async counterpart to :func:`emit_custom_event`."""

    writer(payload)
    event_name = _event_name(payload)
    if event_name is None:
        return
    try:
        await adispatch_custom_event(event_name, payload)
    except GraphBubbleUp:
        raise
    except Exception:
        logger.debug("Failed to dispatch async custom callback event %s", event_name, exc_info=True)

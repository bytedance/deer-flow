"""Execution-local stream processing helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamItem:
    """Normalized stream item from LangGraph."""

    mode: str
    chunk: Any


_FILTERED_NODES = frozenset({"__start__", "__end__"})
_VALID_LG_MODES = {"values", "updates", "checkpoints", "tasks", "debug", "messages", "custom"}


def normalize_stream_modes(requested_modes: list[str] | None) -> list[str]:
    """Normalize requested stream modes to valid LangGraph modes."""
    input_modes: list[str] = list(requested_modes or ["values"])

    lg_modes: list[str] = []
    for mode in input_modes:
        if mode == "messages-tuple":
            lg_modes.append("messages")
        elif mode == "events":
            logger.info("'events' stream_mode not supported (requires astream_events). Skipping.")
            continue
        elif mode in _VALID_LG_MODES:
            lg_modes.append(mode)

    if not lg_modes:
        lg_modes = ["values"]

    seen: set[str] = set()
    deduped: list[str] = []
    for mode in lg_modes:
        if mode not in seen:
            seen.add(mode)
            deduped.append(mode)

    return deduped


def unpack_stream_item(
    item: Any,
    lg_modes: list[str],
    *,
    stream_subgraphs: bool,
) -> tuple[str | None, Any]:
    """Unpack a multi-mode or subgraph stream item into ``(mode, chunk)``."""
    if stream_subgraphs:
        if isinstance(item, tuple) and len(item) == 3:
            _namespace, mode, chunk = item
            return str(mode), chunk
        if isinstance(item, tuple) and len(item) == 2:
            mode, chunk = item
            return str(mode), chunk
        return None, None

    if isinstance(item, tuple) and len(item) == 2:
        mode, chunk = item
        return str(mode), chunk

    return lg_modes[0] if lg_modes else None, item


def should_filter_event(mode: str, chunk: Any) -> bool:
    """Determine whether a stream event should be filtered before publish."""
    if mode == "updates" and isinstance(chunk, dict):
        node_names = set(chunk.keys())
        if node_names & _FILTERED_NODES:
            return True

    if mode == "messages" and isinstance(chunk, tuple) and len(chunk) == 2:
        _, metadata = chunk
        if isinstance(metadata, dict):
            node = metadata.get("langgraph_node", "")
            if node in _FILTERED_NODES:
                return True

    return False


def external_stream_event_name(mode: str) -> str:
    """Map LangGraph internal modes to the external SSE event contract."""
    return mode

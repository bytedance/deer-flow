"""Push helper — programmatically inject a GenUI block into the current SSE stream.

This validates Phase 0.1 of the report-template design: runtime helpers can push
``ui_block`` events into the LangGraph stream **without** going through the LLM's
``render_ui`` tool-call boundary. The implementation reuses the exact mechanism
``render_ui_tool`` already relies on:

    1. ``get_stream_writer()`` to enqueue an SSE event on the active run.
    2. ``persist_block(thread_id, block)`` to fold the block into the per-thread
       snapshot so reconnecting clients recover it.
    3. ``get_persisted_blocks(thread_id)`` + a follow-up ``ui_blocks_folded``
       event so the frontend's recovery store sees the new folded state.

The helper does **not** register interactive callbacks; callers that need
interactive forms should still go through ``render_ui_tool`` so the
``GenUIInterruptMiddleware`` can interrupt execution. This helper is suited to
non-interactive sections (``markdown / table / echart / card / card_group``)
rendered by the runtime when assembling a report.

Used by:
    - ``report_template_render_report`` (Phase 4) — pushes one block per section
    - Future runtime helpers that need to emit GenUI blocks outside a tool call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Final

from langgraph.config import get_config, get_stream_writer

SCHEMA_VERSION: Final[str] = "1.0"

# Subset of ``ALLOWED_COMPONENTS`` from render_ui_tool — only non-interactive
# components are pushable here. Interactive forms must go through render_ui_tool.
_PUSHABLE_COMPONENTS: Final[frozenset[str]] = frozenset(
    {"markdown", "table", "echart", "chart", "card", "code", "timeline", "image", "layout"}
)


class PushBlockError(Exception):
    """Raised when push_block_to_sse cannot deliver the block."""


def build_ui_block_marker(block: dict[str, Any]) -> str:
    """Encode a block as the same marker format used by ``render_ui_tool``.

    Historical GenUI recovery scans message content for ``<!--ui_block:...-->``
    markers. Report runtime helpers bypass ``render_ui_tool``, so they must
    synthesize the same marker format explicitly when they want the block to be
    recoverable from tool-message history.
    """
    block_json = json.dumps(block, ensure_ascii=False, separators=(",", ":"))
    return f"<!--ui_block:{block_json}-->"


def push_block_to_sse(
    component: str,
    props: dict[str, Any],
    *,
    block_id: str | None = None,
    parent_id: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Push a non-interactive GenUI block to the active LangGraph SSE stream.

    Args:
        component: One of the non-interactive component types in ``_PUSHABLE_COMPONENTS``.
        props: Component properties — schema depends on component type.
        block_id: Optional stable block identifier. Generated if omitted.
        parent_id: Optional parent block_id for layout nesting.
        sequence: Optional ordering hint (lower = earlier).

    Returns:
        The block dict actually pushed (with ``block_id`` filled in).

    Raises:
        PushBlockError: If the component is not pushable, no active stream
            writer exists, or persistence fails.
    """
    if component not in _PUSHABLE_COMPONENTS:
        raise PushBlockError(
            f"component {component!r} is not pushable; use render_ui_tool for interactive types "
            f"or extend _PUSHABLE_COMPONENTS for new non-interactive types"
        )

    config = get_config()
    thread_id = config.get("configurable", {}).get("thread_id", "")
    if not thread_id:
        raise PushBlockError("no thread_id in RunnableConfig; cannot push block")

    try:
        writer = get_stream_writer()
    except Exception as e:  # noqa: BLE001 — propagate runtime context errors clearly
        raise PushBlockError(f"no active stream writer: {e}") from e

    resolved_block_id = block_id or str(uuid.uuid4())
    block: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "ui_block",
        "action": "create",
        "block_id": resolved_block_id,
        "component": component,
        "props": props,
        "interactive": False,
    }
    if parent_id:
        block["parent_id"] = parent_id
    if sequence is not None:
        block["sequence"] = sequence

    writer(block)

    # Persist + emit a folded snapshot so reconnecting clients recover state.
    # Import inline to avoid a hard import cycle with genui_persistence helpers.
    from deerflow.agents.genui_persistence import get_persisted_blocks, persist_block

    persist_block(thread_id, block)
    writer({"type": "ui_blocks_folded", "blocks": get_persisted_blocks(thread_id)})

    return block

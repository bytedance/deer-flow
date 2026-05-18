"""Report renderer — push each ``report_payload.sections[]`` as a GenUI block.

Used by ``report_template_render_report``. Each section becomes one
``ui_block`` SSE event via the Phase 0 ``push_block_to_sse`` helper.

We **do not** retain the GenUI store-side ``functional_interaction`` flag here
because rendered reports are non-interactive (they're consumed visually, and
any "edit" gesture goes through a fresh tool call).
"""

from __future__ import annotations

from typing import Any

from deerflow.report_templates.push_block import (
    PushBlockError,
    push_block_to_sse,
)


class RenderReportError(Exception):
    """Raised when at least one section fails to push (the run is failed)."""


def render_report_blocks(
    *,
    payload: dict[str, Any],
    base_sequence: int = 0,
) -> list[dict[str, Any]]:
    """Push one GenUI block per section, in DSL order.

    Args:
        payload: A ``report_payload.json``-shaped dict.
        base_sequence: Starting ``sequence`` number for ordering. Each section
            gets ``base_sequence + index`` to keep them visually ordered.

    Returns:
        The list of dicts actually pushed.

    Raises:
        RenderReportError: If any section is not pushable (an interactive
            component, or stream writer unavailable).
    """
    blocks: list[dict[str, Any]] = []
    for index, section in enumerate(payload.get("sections", [])):
        component = section.get("component")
        props = dict(section.get("props") or {})
        # Inject a synthetic title so the frontend can show a header without
        # relying on Markdown content.
        if section.get("title"):
            props.setdefault("title", section["title"])

        try:
            pushed = push_block_to_sse(
                component=component,
                props=props,
                block_id=f"report-{payload.get('run', {}).get('id', 'rr')}-{section.get('id', index)}",
                sequence=base_sequence + index,
            )
        except PushBlockError as e:
            raise RenderReportError(
                f"section {section.get('id')!r} failed to render: {e}"
            ) from e
        blocks.append(pushed)
    return blocks

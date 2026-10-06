"""Shared citation numbering for the retrieval tools.

The model cites ``[n]`` copied from each evidence item's ``citation_no``
field. All three retrieval tools (hybrid/wiki/graph) must draw numbers from
ONE per-run counter so a multi-path answer never faces three colliding
``[1]``s — the numbering-space collision behind the observed citation drift
(answers repeating ``[1]`` everywhere). The counter rides the runtime
context dict; tool calls within one agent run share it, and each new run
starts from zero again.
"""

from __future__ import annotations

from typing import Any

#: Context key holding the number of citation numbers already allocated.
CITATION_OFFSET_KEY = "citation_offset"


def claim_citation_range(runtime: Any, count: int) -> int:
    """Allocate ``count`` contiguous citation numbers; return the 0-based start.

    Adds the counter to ``runtime.context`` when it is a mutable dict. Any
    other runtime shape (or a non-positive ``count``) degrades to start 0,
    i.e. per-call numbering from 1 — the pre-counter status quo.
    """
    ctx = getattr(runtime, "context", None)
    if not isinstance(ctx, dict) or count <= 0:
        return 0
    start = int(ctx.get(CITATION_OFFSET_KEY) or 0)
    ctx[CITATION_OFFSET_KEY] = start + count
    return start

"""Compatibility patches for third-party checkpoint savers.

Lives at the top-level package (not ``deerflow.runtime``) so it can be
imported from ``deerflow.agents.thread_state`` without pulling in the heavy
``deerflow.runtime`` package __init__ (which eagerly imports the runs
machinery). Anchored from ``deerflow.agents.thread_state`` so every process
that builds a DeerFlow graph (gateway, workers, in-process LangGraph
runtime, tests) runs with the fixes in place.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from packaging.version import Version

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_deerflow_delta_history_patched"
# The patch was authored and verified against langgraph 1.2.9
# (langgraph/checkpoint/memory/__init__.py::InMemorySaver.get_delta_channel_history).
# On any newer LangGraph the override must be re-inspected before keeping the
# patch: if upstream fixed or removed it, this module must stand down.
_PATCH_VALIDATED_LANGGRAPH_VERSION = Version("1.2.9")


def _get_delta_channel_history_via_base(self: Any, *, config: Any, channels: Any) -> Any:
    return BaseCheckpointSaver.get_delta_channel_history(self, config=config, channels=channels)


async def _aget_delta_channel_history_via_base(self: Any, *, config: Any, channels: Any) -> Any:
    return await BaseCheckpointSaver.aget_delta_channel_history(self, config=config, channels=channels)


def _upstream_override_present() -> bool:
    """True while InMemorySaver still ships its own (buggy) override."""
    return (
        getattr(InMemorySaver, "get_delta_channel_history", None) is not None
        and InMemorySaver.get_delta_channel_history is not BaseCheckpointSaver.get_delta_channel_history
        and InMemorySaver.aget_delta_channel_history is not BaseCheckpointSaver.aget_delta_channel_history
    )


def ensure_inmemory_delta_history_patch() -> None:
    """Fix InMemorySaver dropping writes on full -> delta migrated threads.

    ``InMemorySaver.get_delta_channel_history`` overrides the base walk with a
    single-pass version that, upon reaching the first checkpoint carrying a
    non-empty plain-value blob for a channel, skips that checkpoint's *own*
    pending writes as "subsumed" by the blob. That is only true when the blob
    was written by that same checkpoint. When the version was carried forward
    from an older ancestor - exactly the first superstep after a full -> delta
    migration, where the input write lands on a checkpoint still referencing
    the pre-delta blob version - those pending writes postdate the blob and
    are silently dropped: the first message appended after migration vanishes
    from materialized state.

    Both the base implementation (used by the SQLite savers) and the Postgres
    override collect the terminating checkpoint's writes *before* treating its
    blob as the seed, which is the correct order. This patch delegates
    InMemorySaver to the base implementation - one ``get_tuple`` per ancestor
    instead of a single fused walk, which is fine for dict-backed storage.

    Idempotent. Guarded: stands down when the upstream override disappears or
    the assignment fails, and warns once LangGraph moves past the validated
    version so the patch is re-inspected instead of silently overriding an
    upstream fix. Remove once LangGraph fixes the override upstream (no
    upstream issue exists yet; re-check ``InMemorySaver.get_delta_channel_history``
    on every langgraph upgrade).
    """
    if getattr(InMemorySaver, _PATCH_FLAG, False):
        return
    try:
        langgraph_version = Version(importlib.metadata.version("langgraph"))
    except Exception:
        langgraph_version = _PATCH_VALIDATED_LANGGRAPH_VERSION
    if langgraph_version > _PATCH_VALIDATED_LANGGRAPH_VERSION:
        logger.warning(
            "langgraph %s is newer than the version (%s) the InMemorySaver delta-history patch was validated against; re-inspect the upstream override before relying on the patch.",
            langgraph_version,
            _PATCH_VALIDATED_LANGGRAPH_VERSION,
        )
    try:
        if not _upstream_override_present():
            # Upstream removed its override (fixed or refactored): the base
            # implementation is already in use, nothing to patch.
            return
        InMemorySaver.get_delta_channel_history = _get_delta_channel_history_via_base  # type: ignore[method-assign]
        InMemorySaver.aget_delta_channel_history = _aget_delta_channel_history_via_base  # type: ignore[method-assign]
        InMemorySaver._deerflow_delta_history_patched = True  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        logger.warning("Failed to apply the InMemorySaver delta-history patch; leaving the upstream implementation untouched.", exc_info=True)


ensure_inmemory_delta_history_patch()

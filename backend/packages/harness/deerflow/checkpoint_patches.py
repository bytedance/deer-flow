"""Compatibility patches for third-party checkpoint machinery.

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
from collections.abc import Sequence
from typing import Any

from langgraph.channels.binop import BinaryOperatorAggregate
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import ErrorCode, InvalidUpdateError, create_error_message
from langgraph.types import Overwrite
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
        setattr(InMemorySaver, _PATCH_FLAG, True)
    except (AttributeError, TypeError):
        logger.warning("Failed to apply the InMemorySaver delta-history patch; leaving the upstream implementation untouched.", exc_info=True)


_BINOP_PATCH_FLAG = "_deerflow_overwrite_first_write_patched"
_unpatched_binop_update = BinaryOperatorAggregate.update


def _as_overwrite(value: Any) -> tuple[bool, Any]:
    """Local stand-in for langgraph's private ``_get_overwrite``.

    Matches only the public ``Overwrite`` *class* form - the sole form
    DeerFlow's write paths produce for these Union channels (the branch and
    ``/state`` routes wrap replace-style writes in ``Overwrite(...)``).
    Avoiding the underscored ``_get_overwrite`` import keeps an upstream
    refactor that drops it - plausibly the very release that fixes the bug -
    from failing this module's import and crashing startup before the probe
    can stand the patch down. The dict sentinel form upstream also accepts is
    an internal serialization detail DeerFlow never emits into these channels.
    """
    if isinstance(value, Overwrite):
        return True, value.value
    return False, None


def _binop_first_write_stores_overwrite_wrapper() -> bool:
    """Probe whether upstream still stores an Overwrite first write literally.

    Uses a Union-typed channel (no constructible default, so it starts
    MISSING) - the same shape as ``ThreadState``'s ``sandbox`` / ``goal`` /
    ``todos`` / ``promoted`` channels.
    """
    channel = BinaryOperatorAggregate(dict | None, lambda existing, new: new)
    channel.key = "deerflow-overwrite-probe"
    channel.update([Overwrite({"probe": True})])
    return isinstance(channel.get(), Overwrite)


def _binop_update_unwrapping_empty_channel(self: Any, values: Sequence[Any]) -> bool:
    """``BinaryOperatorAggregate.update`` that unwraps an Overwrite first write.

    Only intercepts the empty-channel + leading-Overwrite case; everything
    else delegates to the upstream implementation. The intercepted case
    mirrors upstream's own post-Overwrite batch semantics: later plain values
    are skipped and a second Overwrite raises ``InvalidUpdateError``.
    """
    if not self.is_available() and values:
        is_overwrite, overwrite_value = _as_overwrite(values[0])
        if is_overwrite:
            self.value = overwrite_value
            for value in values[1:]:
                if _as_overwrite(value)[0]:
                    msg = create_error_message(
                        message="Can receive only one Overwrite value per super-step.",
                        error_code=ErrorCode.INVALID_CONCURRENT_GRAPH_UPDATE,
                    )
                    raise InvalidUpdateError(msg)
            return True
    return _unpatched_binop_update(self, values)


def ensure_binop_overwrite_first_write_patch() -> None:
    """Fix ``Overwrite`` first writes being stored literally on empty channels.

    Upstream ``BinaryOperatorAggregate.update`` seeds an empty channel
    (``self.value is MISSING``) with ``values[0]`` verbatim - without the
    Overwrite unwrapping the rest of the method applies. Channels whose type
    is a Union (``SandboxState | None``, ``GoalState | None``, ...) have no
    constructible default, so they start MISSING; a replace-style write into
    a fresh thread (thread branching) or a never-written channel (state
    update) then persists the ``Overwrite`` wrapper itself into the
    checkpoint, and the next consumer crashes with ``TypeError: 'Overwrite'
    object is not subscriptable`` (#4380). ``DeltaChannel.update`` already
    unwraps in the same situation, so this also removes a behavioral
    inconsistency between the two reducer channel types.

    Idempotent. Guarded by a behavioral probe instead of a version pin: if a
    future LangGraph unwraps the first write itself, the probe reports the
    bug as absent and the patch stands down.
    """
    if getattr(BinaryOperatorAggregate, _BINOP_PATCH_FLAG, False):
        return
    try:
        if not _binop_first_write_stores_overwrite_wrapper():
            # Upstream unwraps the first write itself: nothing to patch.
            return
        BinaryOperatorAggregate.update = _binop_update_unwrapping_empty_channel  # type: ignore[method-assign]
        setattr(BinaryOperatorAggregate, _BINOP_PATCH_FLAG, True)
    except Exception:
        logger.warning("Failed to apply the BinaryOperatorAggregate Overwrite first-write patch; leaving the upstream implementation untouched.", exc_info=True)


ensure_inmemory_delta_history_patch()
ensure_binop_overwrite_first_write_patch()

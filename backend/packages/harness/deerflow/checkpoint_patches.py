"""Compatibility patches for third-party checkpoint machinery.

Lives at the top-level package (not ``deerflow.runtime``) so it can be
imported from ``deerflow.agents.thread_state`` without pulling in the heavy
``deerflow.runtime`` package __init__ (which eagerly imports the runs
machinery). Anchored from ``deerflow.agents.thread_state`` so every process
that builds a DeerFlow graph (gateway, workers, in-process LangGraph
runtime, tests) runs with the fixes in place.

One patch remains: ``BinaryOperatorAggregate`` unwrapping an ``Overwrite``
first write into an empty (MISSING) channel (#4380). The former
``InMemorySaver`` delta-history patch was removed: upstream fixed the dropped
first post-migration write in ``langgraph-checkpoint`` 4.2.0 (upstream #8526)
while keeping its own override, so a behavioural probe cannot see the fix.
The harness dependency floor (``langgraph-checkpoint>=4.2.0``) is what keeps
that bug out, and
``tests/test_delta_channel_checkpointers.py::test_full_to_delta_migration_replays_on_same_thread``
is the regression gate that fails when the fix is absent. Do not re-add a
version-guarded saver patch: the guard that used to live here read
``langgraph``'s version, but ``InMemorySaver`` ships in the independently
released ``langgraph-checkpoint`` distribution.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from langgraph.channels.binop import BinaryOperatorAggregate
from langgraph.errors import ErrorCode, InvalidUpdateError, create_error_message
from langgraph.types import Overwrite

logger = logging.getLogger(__name__)


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


ensure_binop_overwrite_first_write_patch()

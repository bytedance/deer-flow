"""Guards for the BinaryOperatorAggregate first-write Overwrite patch (#4380).

Upstream ``BinaryOperatorAggregate.update`` has a fast path for empty channels
(``self.value is MISSING``) that stores the first incoming value without
unwrapping ``Overwrite``. Reducer channels whose type is a Union
(``SandboxState | None``, ``GoalState | None``, ...) have no constructible
default, so they start MISSING — a replace-style write into a fresh thread
(thread branching) or a never-written channel (state update) persists the
wrapper literally, and the next consumer crashes with ``TypeError:
'Overwrite' object is not subscriptable``. ``DeltaChannel`` already unwraps in
the same situation; the patch aligns ``BinaryOperatorAggregate`` with it.
"""

import pytest
from langgraph.channels.binop import BinaryOperatorAggregate
from langgraph.errors import InvalidUpdateError
from langgraph.types import Overwrite

import deerflow.agents.thread_state  # noqa: F401 - applies checkpoint patches at import
from deerflow import checkpoint_patches


def _replace(existing, new):
    return new


def _empty_union_channel() -> BinaryOperatorAggregate:
    """A channel shaped like ``sandbox``/``goal``/``todos``: Union type, starts MISSING."""
    channel = BinaryOperatorAggregate(dict | None, _replace)
    channel.key = "probe"
    return channel


def test_first_write_overwrite_unwraps_into_empty_channel() -> None:
    channel = _empty_union_channel()
    channel.update([Overwrite({"sandbox_id": "local:thread-2"})])

    stored = channel.get()
    assert not isinstance(stored, Overwrite)
    # The exact read that crashed in #4380 (SandboxMiddleware.aafter_agent).
    assert stored["sandbox_id"] == "local:thread-2"


def test_overwrite_into_populated_channel_still_replaces() -> None:
    channel = _empty_union_channel()
    channel.update([{"sandbox_id": "old"}])
    channel.update([Overwrite({"sandbox_id": "new"})])

    assert channel.get() == {"sandbox_id": "new"}


def test_plain_first_write_still_seeds_then_reduces() -> None:
    channel = _empty_union_channel()
    channel.update([{"sandbox_id": "first"}])
    assert channel.get() == {"sandbox_id": "first"}

    channel.update([{"sandbox_id": "second"}])
    assert channel.get() == {"sandbox_id": "second"}


def test_values_after_first_write_overwrite_are_ignored() -> None:
    """Upstream semantics: after an Overwrite, later plain values in the batch are skipped."""
    channel = _empty_union_channel()
    channel.update([Overwrite({"sandbox_id": "kept"}), {"sandbox_id": "ignored"}])

    assert channel.get() == {"sandbox_id": "kept"}


def test_double_overwrite_in_one_batch_raises_on_empty_channel() -> None:
    channel = _empty_union_channel()
    with pytest.raises(InvalidUpdateError):
        channel.update([Overwrite({"sandbox_id": "a"}), Overwrite({"sandbox_id": "b"})])


def test_binop_overwrite_patch_is_active() -> None:
    """The compatibility patch must be applied in every test/app process."""
    assert getattr(BinaryOperatorAggregate, checkpoint_patches._BINOP_PATCH_FLAG, False) is True
    assert BinaryOperatorAggregate.update is checkpoint_patches._binop_update_unwrapping_empty_channel


def test_binop_overwrite_patch_stands_down_when_upstream_fixed(monkeypatch) -> None:
    """If upstream unwraps the first write itself, the patch must not reinstall."""
    monkeypatch.setattr(checkpoint_patches, "_binop_first_write_stores_overwrite_wrapper", lambda: False)
    monkeypatch.delattr(BinaryOperatorAggregate, checkpoint_patches._BINOP_PATCH_FLAG, raising=False)
    sentinel = object()
    monkeypatch.setattr(BinaryOperatorAggregate, "update", sentinel)

    checkpoint_patches.ensure_binop_overwrite_first_write_patch()

    assert getattr(BinaryOperatorAggregate, checkpoint_patches._BINOP_PATCH_FLAG, False) is False
    assert BinaryOperatorAggregate.update is sentinel

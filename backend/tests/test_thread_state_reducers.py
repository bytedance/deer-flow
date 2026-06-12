"""Unit tests for ThreadState reducers.

Regression coverage for issue #3123: todos list disappearing after streaming
completes because a downstream node's partial state update with `todos=None`
overwrites the previously accumulated value.
"""

from typing import get_type_hints

import pytest

from deerflow.agents.thread_state import (
    ThreadState,
    merge_artifacts,
    merge_sandbox,
    merge_todos,
    merge_viewed_images,
)


class TestMergeSandbox:
    """Reducer for ThreadState.sandbox - allows idempotent concurrent writes."""

    def test_none_new_preserves_existing(self):
        existing = {"sandbox_id": "sandbox-1"}
        assert merge_sandbox(existing, None) == existing

    def test_none_existing_accepts_new(self):
        new = {"sandbox_id": "sandbox-1"}
        assert merge_sandbox(None, new) == new

    def test_same_sandbox_id_is_idempotent(self):
        existing = {"sandbox_id": "sandbox-1"}
        new = {"sandbox_id": "sandbox-1"}
        assert merge_sandbox(existing, new) == existing

    def test_both_none_sandbox_id_is_idempotent(self):
        existing = {"sandbox_id": None}
        new = {"sandbox_id": None}
        assert merge_sandbox(existing, new) == existing

    def test_omitted_sandbox_id_is_idempotent(self):
        """An omitted sandbox_id represents uninitialized sandbox state."""
        existing = {}
        new = {}
        assert merge_sandbox(existing, new) == existing

    def test_conflicting_sandbox_ids_raise(self):
        existing = {"sandbox_id": "sandbox-1"}
        new = {"sandbox_id": "sandbox-2"}
        with pytest.raises(ValueError, match="Conflicting sandbox state updates"):
            merge_sandbox(existing, new)


class TestMergeTodos:
    """Reducer for ThreadState.todos - keeps last non-None value."""

    def test_new_value_overrides_existing(self):
        existing = [{"id": 1, "text": "old", "done": False}]
        new = [{"id": 1, "text": "old", "done": True}]
        assert merge_todos(existing, new) == new

    def test_none_new_preserves_existing(self):
        """THE KEY FIX for #3123: a node that doesn't touch todos must NOT
        wipe them out by returning an implicit None."""
        existing = [{"id": 1, "text": "task", "done": False}]
        assert merge_todos(existing, None) == existing

    def test_none_existing_accepts_new(self):
        new = [{"id": 1, "text": "first todo"}]
        assert merge_todos(None, new) == new

    def test_both_none_returns_none(self):
        assert merge_todos(None, None) is None

    def test_empty_list_is_explicit_clear(self):
        """An explicit empty list means 'user cleared all todos' and must
        win over the previous list."""
        existing = [{"id": 1, "text": "task"}]
        assert merge_todos(existing, []) == []


class TestMergeArtifacts:
    """Sanity check for the existing artifacts reducer."""

    def test_dedupes_and_preserves_order(self):
        assert merge_artifacts(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_none_new_preserves_existing(self):
        assert merge_artifacts(["a"], None) == ["a"]

    def test_none_existing_accepts_new(self):
        assert merge_artifacts(None, ["a"]) == ["a"]


class TestMergeViewedImages:
    """Sanity check for the existing viewed_images reducer."""

    def test_merges_dicts(self):
        existing = {"k1": {"base64": "x", "mime_type": "image/png"}}
        new = {"k2": {"base64": "y", "mime_type": "image/jpeg"}}
        merged = merge_viewed_images(existing, new)
        assert set(merged.keys()) == {"k1", "k2"}

    def test_empty_dict_clears(self):
        existing = {"k1": {"base64": "x", "mime_type": "image/png"}}
        assert merge_viewed_images(existing, {}) == {}


class TestThreadStateAnnotations:
    """Regression guards: ensure reducer wiring on ThreadState fields.

    These tests protect against silent regressions where a field's
    ``Annotated[..., reducer]`` is reverted to a plain type, which would
    re-introduce bugs even when the reducer functions themselves remain
    correct.
    """

    def test_todos_field_is_wired_to_merge_todos(self):
        """ThreadState.todos must use merge_todos.

        Without this Annotated binding, LangGraph falls back to last-value-wins
        behavior, and partial state updates that omit todos will silently clear
        previously streamed values.
        """
        hints = get_type_hints(ThreadState, include_extras=True)
        todos_hint = hints["todos"]
        assert hasattr(todos_hint, "__metadata__"), "ThreadState.todos must be Annotated with a reducer"
        assert merge_todos in todos_hint.__metadata__, "ThreadState.todos must be wired to merge_todos reducer (see #3123)"

    def test_artifacts_field_is_wired_to_merge_artifacts(self):
        """Sanity check that existing reducer wiring is preserved."""
        hints = get_type_hints(ThreadState, include_extras=True)
        assert merge_artifacts in hints["artifacts"].__metadata__

    def test_sandbox_field_is_wired_to_merge_sandbox(self):
        """ThreadState.sandbox must merge idempotent lazy-init updates.

        Without this Annotated binding, concurrent sandbox tools that all
        persist the same lazily acquired sandbox_id can trigger LangGraph's
        INVALID_CONCURRENT_GRAPH_UPDATE error.
        """
        hints = get_type_hints(ThreadState, include_extras=True)
        assert merge_sandbox in hints["sandbox"].__metadata__

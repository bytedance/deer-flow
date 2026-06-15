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
from deerflow.sandbox.middleware import SandboxMiddlewareState


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


class TestSandboxMiddlewareStateAnnotation:
    """Regression tests for the #3518 follow-up.

    langchain's ``create_agent`` calls ``_resolve_schemas`` to merge every
    middleware's ``state_schema`` together with the user-supplied
    ``state_schema`` (``ThreadState``). The merge uses last-write-wins
    semantics on the field name, so when ``SandboxMiddlewareState.sandbox``
    is declared without the ``merge_sandbox`` reducer annotation, the
    reducer wired on ``ThreadState.sandbox`` is silently dropped from the
    resolved schema. The graph then builds a ``LastValueChannel`` for
    ``sandbox`` instead of a reducer channel, and concurrent tool-call
    sandbox writes raise ``INVALID_CONCURRENT_GRAPH_UPDATE``.

    Tests here guard both ends of that merge:
      1. The middleware's ``state_schema`` carries the reducer binding.
      2. The resolved schema (what the runtime actually consumes) preserves
         the reducer binding.
    """

    def test_sandbox_middleware_state_sandbox_is_wired_to_merge_sandbox(self):
        """``SandboxMiddlewareState.sandbox`` must carry the same reducer
        binding as ``ThreadState.sandbox`` so it survives the langchain
        schema merge.
        """
        hints = get_type_hints(SandboxMiddlewareState, include_extras=True)
        sandbox_hint = hints["sandbox"]
        assert hasattr(sandbox_hint, "__metadata__"), "SandboxMiddlewareState.sandbox must be Annotated with a reducer so the langchain schema merge does not silently drop the ThreadState.sandbox reducer (regression for #3518 follow-up)"
        assert merge_sandbox in sandbox_hint.__metadata__, "SandboxMiddlewareState.sandbox must be wired to merge_sandbox to survive the langchain schema merge (regression for #3518 follow-up)"

    def test_resolved_schema_preserves_sandbox_reducer_when_middleware_merged_last(self):
        """End-to-end regression test that exercises the actual langchain
        merge path. The merge in ``_resolve_schema`` is
        ``last-write-wins`` over ``schema_hints.values()``, so the bug
        only manifests when the middleware's ``state_schema`` is processed
        after ``ThreadState`` (which is non-deterministic in the runtime
        because langchain passes a ``set``). This test pins down the bug
        condition by ordering the dict explicitly with
        ``SandboxMiddlewareState`` last, which is the same condition that
        triggered the production ``INVALID_CONCURRENT_GRAPH_UPDATE`` in
        the user's reported run.
        """
        from langchain.agents.factory import _resolve_schema

        # Order matters: SandboxMiddlewareState is inserted LAST so its
        # ``sandbox`` field overwrites ThreadState's. This is the
        # iteration order that triggers the bug.
        schema_hints = {
            ThreadState: get_type_hints(ThreadState, include_extras=True),
            SandboxMiddlewareState: get_type_hints(SandboxMiddlewareState, include_extras=True),
        }
        resolved = _resolve_schema(schema_hints, "StateSchema", None)
        hints = get_type_hints(resolved, include_extras=True)
        sandbox_hint = hints["sandbox"]
        assert hasattr(sandbox_hint, "__metadata__"), (
            "Resolved schema's sandbox lost its Annotated metadata during the langchain schema merge — concurrent tool-call sandbox writes will raise INVALID_CONCURRENT_GRAPH_UPDATE (regression for #3518 follow-up)"
        )
        assert merge_sandbox in sandbox_hint.__metadata__, "Resolved schema's sandbox must preserve the merge_sandbox reducer so the graph channel is a reducer channel rather than LastValueChannel (regression for #3518 follow-up)"

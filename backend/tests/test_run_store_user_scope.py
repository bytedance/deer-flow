"""Legacy user_id auth-compat regression tests (problem H-compat).

Rows persisted before user-scoping was added have an empty ``user_id``.
Such rows must not be hard-filtered out of ``RunStore.get`` when a caller
supplies a ``user_id`` — only rows whose stored ``user_id`` is non-empty and
mismatches should be rejected.
"""

from __future__ import annotations

import pytest

from deerflow.runtime.runs.store.memory import MemoryRunStore

RUN_ID = "11111111-2222-3333-4444-555555555555"


@pytest.mark.anyio
async def test_legacy_empty_user_id_row_is_not_filtered():
    store = MemoryRunStore()
    await store.put(RUN_ID, thread_id="t-1", user_id=None)  # legacy row

    # A scoped caller must still be able to read the legacy row.
    row = await store.get(RUN_ID, user_id="alice")
    assert row is not None
    assert row["run_id"] == RUN_ID


@pytest.mark.anyio
async def test_matching_user_id_row_is_returned():
    store = MemoryRunStore()
    await store.put(RUN_ID, thread_id="t-1", user_id="alice")

    row = await store.get(RUN_ID, user_id="alice")
    assert row is not None


@pytest.mark.anyio
async def test_mismatched_nonempty_user_id_row_is_filtered():
    store = MemoryRunStore()
    await store.put(RUN_ID, thread_id="t-1", user_id="alice")

    assert await store.get(RUN_ID, user_id="bob") is None


@pytest.mark.anyio
async def test_unscoped_caller_reads_any_row():
    store = MemoryRunStore()
    await store.put(RUN_ID, thread_id="t-1", user_id="alice")

    row = await store.get(RUN_ID, user_id=None)
    assert row is not None

"""Regression tests for issue #4488: concurrent thread metadata patches must
not lose keys to a read-modify-write race.

The SQL-backed ``ThreadMetaRepository.update_metadata`` performs a
read-modify-write on ``metadata_json``. Without row locking two concurrent
calls that patch disjoint keys silently clobber each other on commit (the
second commit overwrites the first). The in-memory store hides this because
it does not yield control between its get and put; the SQL path does, so
this module exercises the repository with genuinely concurrent calls
(``asyncio.gather``) and asserts both keys survive -- across many rounds to
catch the interleavings a single shot would miss.
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.persistence.thread_meta import THREAD_PINNED_METADATA_KEY, ThreadMetaRepository


@pytest.fixture
async def repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    yield ThreadMetaRepository(get_session_factory())
    await close_engine()


@pytest.mark.anyio
async def test_concurrent_disjoint_metadata_patches_preserve_both_keys(repo):
    """Two concurrent ``update_metadata`` calls merging disjoint keys must
    both land -- no lost update.

    The race window is scheduler-dependent, so a single shot can pass by
    luck even on the buggy implementation (issue #4488 measured ~4/100
    accidental passes). Iterating many rounds with fresh threads makes the
    interleaving deterministic enough to fail reliably without the fix.
    """
    rounds = 20
    for i in range(rounds):
        thread_id = f"t-{i}"
        await repo.create(thread_id, metadata={"seed": i})

        await asyncio.gather(
            repo.update_metadata(thread_id, {"left": 1}),
            repo.update_metadata(thread_id, {"right": 2}),
        )

        record = await repo.get(thread_id)
        assert record["metadata"] == {"seed": i, "left": 1, "right": 2}, (
            f"round {i}: concurrent disjoint patches must both survive "
            f"(got {record['metadata']!r})"
        )


@pytest.mark.anyio
async def test_concurrent_touch_false_patch_does_not_lose_keys(repo):
    """Pin/unpin (``touch=False``) racing another metadata write must still
    merge both payloads without losing keys, while ``updated_at`` stays
    pinned.

    This is the user-visible symptom reported in issue #4488: a pin toggle
    raced with another metadata write and one of them disappeared.
    """
    rounds = 10
    for i in range(rounds):
        thread_id = f"pin-{i}"
        await repo.create(thread_id, metadata={"keep": i})
        original = (await repo.get(thread_id))["updated_at"]

        await asyncio.gather(
            repo.update_metadata(thread_id, {THREAD_PINNED_METADATA_KEY: True}, touch=False),
            repo.update_metadata(thread_id, {"note": f"n{i}"}, touch=False),
        )

        record = await repo.get(thread_id)
        assert record["metadata"] == {
            "keep": i,
            THREAD_PINNED_METADATA_KEY: True,
            "note": f"n{i}",
        }, f"round {i}: {record['metadata']!r}"
        # touch=False must continue to preserve updated_at under concurrency.
        assert record["updated_at"] == original, f"round {i}: updated_at moved unexpectedly"

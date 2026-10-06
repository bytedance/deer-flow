"""Tests for the projection cache (spec §6 P3).

Behavioral contract: the fingerprint decides — a matching fingerprint serves
the cached entry without recomputing; any change (or ``refresh=True``)
recomputes and replaces; concurrent misses collapse into one computation
behind a per-key lock. The fingerprint itself is a cheap DB-side digest over
per-table count + max-timestamp signals.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from deerflow.knowledge.projection.cache import (
    CachedProjection,
    ProjectionCache,
    content_fingerprint,
)
from deerflow.knowledge.store import KnowledgeStore


def _entry(tag: str) -> CachedProjection:
    return CachedProjection(coords=tag, points=(tag,), computed_ms=1)


def _stats(*, chunks=(0, None), wiki=(0, None), cards=(0, None), entities=0):
    return {"chunks": chunks, "wiki": wiki, "cards": cards, "entities": entities}


async def test_same_fingerprint_hits_without_recompute() -> None:
    cache = ProjectionCache()
    calls = 0

    async def compute() -> CachedProjection:
        nonlocal calls
        calls += 1
        return _entry("v1")

    first = await cache.get_or_compute(("kb-1", "pca", 2), fingerprint="fp", compute=compute)
    second = await cache.get_or_compute(("kb-1", "pca", 2), fingerprint="fp", compute=compute)

    assert calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.coords == "v1"
    assert second.fingerprint == "fp"
    assert second.created_at > 0


async def test_fingerprint_change_recomputes_and_replaces() -> None:
    cache = ProjectionCache()
    calls = 0

    async def compute() -> CachedProjection:
        nonlocal calls
        calls += 1
        return _entry(f"v{calls}")

    await cache.get_or_compute(("kb-1",), fingerprint="fp1", compute=compute)
    changed = await cache.get_or_compute(("kb-1",), fingerprint="fp2", compute=compute)
    third = await cache.get_or_compute(("kb-1",), fingerprint="fp2", compute=compute)

    assert calls == 2
    assert changed.coords == "v2"
    assert changed.cached is False
    assert third.cached is True
    assert third.coords == "v2"  # the replacement is what later hits see


async def test_refresh_skips_fingerprint_match() -> None:
    cache = ProjectionCache()
    calls = 0

    async def compute() -> CachedProjection:
        nonlocal calls
        calls += 1
        return _entry(f"v{calls}")

    await cache.get_or_compute(("kb-1",), fingerprint="fp", compute=compute)
    refreshed = await cache.get_or_compute(("kb-1",), fingerprint="fp", refresh=True, compute=compute)

    assert calls == 2
    assert refreshed.coords == "v2"
    assert refreshed.cached is False


async def test_concurrent_misses_collapse_to_one_compute() -> None:
    cache = ProjectionCache()
    calls = 0

    async def compute() -> CachedProjection:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _entry("v1")

    results = await asyncio.gather(*[cache.get_or_compute(("kb-1",), fingerprint="fp", compute=compute) for _ in range(10)])

    assert calls == 1
    assert all(r.coords == "v1" for r in results)
    # one request computes; the other nine hit the fresh entry under the lock.
    assert sum(1 for r in results if r.cached) == 9


async def test_distinct_keys_are_independent() -> None:
    cache = ProjectionCache()
    calls = 0

    async def compute() -> CachedProjection:
        nonlocal calls
        calls += 1
        return _entry(f"v{calls}")

    await cache.get_or_compute(("kb-1", "pca", 2), fingerprint="fp", compute=compute)
    await cache.get_or_compute(("kb-1", "pca", 3), fingerprint="fp", compute=compute)

    assert calls == 2


def test_fingerprint_stable_and_sensitive_to_each_signal() -> None:
    edited = datetime(2026, 8, 15, tzinfo=UTC)
    base = _stats(chunks=(5, edited), wiki=(2, None), cards=(1, None), entities=7)
    fp = content_fingerprint(base)

    assert fp.startswith("sha1:")
    assert content_fingerprint(base) == fp  # deterministic
    # every single signal flips the digest
    assert content_fingerprint(_stats(chunks=(6, edited), wiki=(2, None), cards=(1, None), entities=7)) != fp
    assert content_fingerprint(_stats(chunks=(5, datetime(2026, 8, 16, tzinfo=UTC)), wiki=(2, None), cards=(1, None), entities=7)) != fp
    assert content_fingerprint(_stats(chunks=(5, edited), wiki=(3, None), cards=(1, None), entities=7)) != fp
    assert content_fingerprint(_stats(chunks=(5, edited), wiki=(2, None), cards=(2, datetime(2026, 8, 15, tzinfo=UTC)), entities=7)) != fp
    assert content_fingerprint(_stats(chunks=(5, edited), wiki=(2, None), cards=(1, None), entities=8)) != fp
    # None vs a real timestamp differs (first edit flips the fingerprint)
    assert content_fingerprint(_stats(chunks=(5, None), wiki=(2, None), cards=(1, None), entities=7)) != fp


async def test_get_kb_content_stats_aggregates_per_table(session_factory) -> None:
    """The fingerprint's DB side: per-table count + max-timestamp, scoped to one kb."""
    from deerflow.knowledge.models import GraphEntityRow, ManualKnowledgeRow, WikiEntryRow

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="u", name="库")
    await store.insert_chunks(
        [
            {"chunk_id": "d#0000", "doc_id": "d", "kb_id": "kb-1", "chunk_index": 0, "text": "甲"},
            {"chunk_id": "d#0001", "doc_id": "d", "kb_id": "kb-1", "chunk_index": 1, "text": "乙"},
        ]
    )
    edited = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    async with session_factory() as session:
        session.add_all(
            [
                WikiEntryRow(id="w1", kb_id="kb-1", title="条目", content="正文", source_chunk_ids=[], updated_at=edited),
                ManualKnowledgeRow(id="c1", kb_id="kb-1", owner_id="u", title="卡", content="容", updated_at=edited),
                GraphEntityRow(id="e1", kb_id="kb-1", name="实体", type="概念", description=""),
                GraphEntityRow(id="e2", kb_id="kb-2", name="别库实体", type="概念", description=""),
            ]
        )
        await session.commit()

    stats = await store.get_kb_content_stats("kb-1")

    assert stats["chunks"][0] == 2
    assert stats["chunks"][1] is None  # no manual edit yet
    assert stats["wiki"][0] == 1
    assert stats["wiki"][1] is not None
    assert stats["cards"][0] == 1
    assert stats["entities"] == 1  # kb-2's entity is excluded
    # a manual chunk edit flips the max timestamp signal
    await store.update_chunk_text("d#0000", "甲改", 1)
    after = await store.get_kb_content_stats("kb-1")
    assert after["chunks"][1] is not None
    # an empty kb yields zeroed signals without erroring
    empty = await store.get_kb_content_stats("kb-empty")
    assert empty == {"chunks": (0, None), "wiki": (0, None), "cards": (0, None), "entities": 0}

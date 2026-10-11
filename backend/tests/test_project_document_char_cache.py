"""Character-count cache invariants across real file-IO worker threads."""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict

import pytest

from deerflow.projects import documents

pytestmark = pytest.mark.anyio


@pytest.fixture
def cache(monkeypatch):
    cache = OrderedDict()
    monkeypatch.setattr(documents, "_CHAR_COUNT_CACHE", cache)
    monkeypatch.setattr(documents, "_CHAR_COUNT_CACHE_MAX", 2)
    return cache


async def test_hit_promotion_cannot_race_with_eviction(tmp_path, monkeypatch):
    hit_ready = threading.Event()
    writer_progress = threading.Event()
    release_hit = threading.Event()
    hot_key = ("hot", "sha-hot")

    class PausingCache(OrderedDict):
        def get(self, key, default=None):
            value = super().get(key, default)
            if key == hot_key:
                hit_ready.set()
                assert release_hit.wait(5), "cache hit was not released"
            return value

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if hit_ready.is_set():
                # Signal before acquiring: a correct implementation holds the
                # lock across the paused lookup and subsequent promotion.
                writer_progress.set()
            self.lock.acquire()

        def __exit__(self, *exc):
            self.lock.release()

    cache = PausingCache({hot_key: 8})
    monkeypatch.setattr(documents, "_CHAR_COUNT_CACHE", cache)
    monkeypatch.setattr(documents, "_CHAR_COUNT_CACHE_MAX", 1)
    monkeypatch.setattr(documents, "_CHAR_COUNT_CACHE_LOCK", ObservedLock(), raising=False)
    hot_path = tmp_path / "hot.txt"
    hot_path.write_text("abcdefgh", encoding="utf-8")
    other_path = tmp_path / "other.txt"
    other_path.write_text("other", encoding="utf-8")

    async def insert_other():
        try:
            return await documents.document_char_count(document_id="other", sha256="sha-other", path=other_path)
        finally:
            # Without the lock, insertion completes and evicts the paused hit.
            writer_progress.set()

    tasks = [asyncio.create_task(documents.document_char_count(document_id=hot_key[0], sha256=hot_key[1], path=hot_path))]
    try:
        assert await asyncio.to_thread(hit_ready.wait, 5), "cache hit did not start"
        tasks.append(asyncio.create_task(insert_other()))
        assert await asyncio.to_thread(writer_progress.wait, 5), "competing cache operation did not start"
        release_hit.set()
        assert await asyncio.gather(*tasks) == [8, 5]
        assert list(cache.items()) == [(("other", "sha-other"), 5)]
    finally:
        release_hit.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_full_scan_does_not_hold_cache_lock(tmp_path, monkeypatch, cache):
    cache[("hot", "sha-hot")] = 8
    scan_started = threading.Event()
    release_scan = threading.Event()
    slow_path = tmp_path / "slow.txt"
    slow_path.write_text("slow scan", encoding="utf-8")
    real_count = documents._count_text_chars

    def paused_count(path):
        scan_started.set()
        assert release_scan.wait(5), "file scan was not released"
        return real_count(path)

    monkeypatch.setattr(documents, "_count_text_chars", paused_count)
    tasks = [asyncio.create_task(documents.document_char_count(document_id="slow", sha256="sha-slow", path=slow_path))]
    try:
        assert await asyncio.to_thread(scan_started.wait, 5), "file scan did not start"
        tasks.append(asyncio.create_task(documents.document_char_count(document_id="hot", sha256="sha-hot", path=tmp_path / "unused.txt")))
        assert await asyncio.wait_for(asyncio.shield(tasks[-1]), 5) == 8
        release_scan.set()
        assert await tasks[0] == 9
    finally:
        release_scan.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_zero_counts_content_identity_and_lru_bound(tmp_path, monkeypatch, cache):
    calls = []
    real_count = documents._count_text_chars

    def counted(path):
        calls.append(path)
        return real_count(path)

    monkeypatch.setattr(documents, "_count_text_chars", counted)
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    text = tmp_path / "text.txt"
    text.write_text("\u4f60\u597d", encoding="utf-8")
    assert await documents.document_char_count(document_id="a", sha256="empty", path=empty) == 0
    assert await documents.document_char_count(document_id="b", sha256="text", path=text) == 2
    assert await documents.document_char_count(document_id="a", sha256="empty", path=empty) == 0
    assert calls == [empty, text]
    assert await documents.document_char_count(document_id="c", sha256="text", path=text) == 2
    assert list(cache) == [("a", "empty"), ("c", "text")]
    assert await documents.document_char_count(document_id="a", sha256="changed", path=text) == 2
    assert list(cache) == [("c", "text"), ("a", "changed")]
    assert len(cache) == 2
